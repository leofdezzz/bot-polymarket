"""
Polymarket 5-minute RSI Strategy for Crypto:
Operates ONLY on 5-minute Polymarket markets related to BTC/ETH.
Buys YES when oversold (expecting bounce), NO when overbought.
"""
from api.polymarket_client import Market, PolymarketClient
from engine.portfolio import Portfolio
from strategies.base import BaseStrategy, TradeSignal

CRYPTO_KEYWORDS = ['btc', 'bitcoin', 'eth', 'ethereum', 'crypto']


def is_crypto_market(market: Market) -> bool:
    q = market.question.lower()
    return any(k in q for k in CRYPTO_KEYWORDS)


class Polymarket5RSIStrategy(BaseStrategy):
    name = "polymarket_5m_rsi"
    description = "5min RSI Crypto: reversal en extremos crypto"
    MIN_CONFIDENCE = 0.25
    MIN_HISTORY = 3
    MIN_VOLUME = 10
    RSI_OVERSOLD = 0.35
    RSI_OVERBOUGHT = 0.65

    def run(self):
        markets = self.client.get_all_markets()
        open_ids = {p.market_id for p in self.portfolio.open_positions()}

        for market in markets:
            if market.id in open_ids and market.is_fast_market:
                self.portfolio.update_prices(market.id, market.yes_price)

        signals = self.generate_signals(markets)
        signals.sort(key=lambda s: s.confidence, reverse=True)

        for signal in signals:
            if signal.confidence < self.MIN_CONFIDENCE:
                continue
            if signal.market.id in open_ids:
                continue
            self.portfolio.buy(
                market_id=signal.market.id,
                question=signal.market.question,
                outcome=signal.outcome,
                price=signal.price,
                market_type=signal.market_type,
                end_date=signal.end_date,
            )

    def _calculate_rsi(self, prices: list[float]) -> float:
        if len(prices) < 2:
            return 0.5
        changes = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        if not changes:
            return 0.5
        gains = [c for c in changes if c > 0]
        losses = [-c for c in changes if c < 0]
        avg_gain = sum(gains) / len(changes) if gains else 0
        avg_loss = sum(losses) / len(changes) if losses else 0
        if avg_loss == 0:
            return 100 if avg_gain > 0 else 50
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi / 100

    def generate_signals(self, markets: list[Market]) -> list[TradeSignal]:
        signals = []
        for m in markets:
            if m.market_type != "5min":
                continue
            if not is_crypto_market(m):
                continue
            if not m.is_tradeable_fast(min_volume=self.MIN_VOLUME, min_liquidity=10):
                continue

            history = self.client.history.get(m.id)
            if len(history) < self.MIN_HISTORY:
                continue

            prices = [h[1] for h in history]
            rsi = self._calculate_rsi(prices)

            if rsi < self.RSI_OVERSOLD:
                conf = (self.RSI_OVERSOLD - rsi) / self.RSI_OVERSOLD * 0.7
                signals.append(TradeSignal(m, "YES", m.yes_price, conf,
                                           f"RSI {rsi:.0%} oversold"))

            elif rsi > self.RSI_OVERBOUGHT:
                conf = (rsi - self.RSI_OVERBOUGHT) / (1 - self.RSI_OVERBOUGHT) * 0.7
                signals.append(TradeSignal(m, "NO", m.no_price, conf,
                                           f"RSI {rsi:.0%} overbought"))

        signals.sort(key=lambda s: s.confidence, reverse=True)
        return signals
