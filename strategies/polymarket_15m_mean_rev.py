"""
Polymarket 15-minute Crypto Mean Reversion Strategy:
Operates ONLY on 15-minute Polymarket markets related to BTC/ETH.
Buys when price deviates significantly from average.
"""
from api.polymarket_client import Market, PolymarketClient
from engine.portfolio import Portfolio
from strategies.base import BaseStrategy, TradeSignal

CRYPTO_KEYWORDS = ['btc', 'bitcoin', 'eth', 'ethereum', 'crypto']


def is_crypto_market(market: Market) -> bool:
    q = market.question.lower()
    return any(k in q for k in CRYPTO_KEYWORDS)


class Polymarket15MeanRevStrategy(BaseStrategy):
    name = "polymarket_15m_mean_rev"
    description = "15min Crypto MeanRev: reversión crypto"
    MIN_CONFIDENCE = 0.3
    MIN_HISTORY = 5
    MIN_VOLUME = 10
    DEVIATION_THRESHOLD = 0.10

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

    def generate_signals(self, markets: list[Market]) -> list[TradeSignal]:
        signals = []
        for m in markets:
            if m.market_type != "15min":
                continue
            if not is_crypto_market(m):
                continue
            if not m.is_tradeable_fast(min_volume=self.MIN_VOLUME, min_liquidity=10):
                continue

            history = self.client.history.get(m.id)
            if len(history) < self.MIN_HISTORY:
                continue

            prices = [h[1] for h in history]
            avg_price = sum(prices) / len(prices)

            if avg_price < 0.1 or avg_price > 0.9:
                continue

            deviation = (prices[-1] - avg_price) / avg_price if avg_price > 0 else 0.0

            if abs(deviation) < self.DEVIATION_THRESHOLD:
                continue

            conf = min(abs(deviation) / 0.25, 1.0) * 0.7

            if deviation < 0:
                outcome = "YES"
                price = m.yes_price
                reason = f"REV-UP {deviation:+.0%}"
            else:
                outcome = "NO"
                price = m.no_price
                reason = f"REV-DOWN {deviation:+.0%}"

            signals.append(TradeSignal(m, outcome, price, conf, reason))

        signals.sort(key=lambda s: s.confidence, reverse=True)
        return signals
