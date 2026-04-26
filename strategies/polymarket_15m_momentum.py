"""
Polymarket 15-minute Crypto Momentum Strategy:
Operates ONLY on 15-minute Polymarket markets related to BTC/ETH.
Buys YES when price going up, NO when going down.
"""
from api.polymarket_client import Market, PolymarketClient
from engine.portfolio import Portfolio
from strategies.base import BaseStrategy, TradeSignal

CRYPTO_KEYWORDS = ['btc', 'bitcoin', 'eth', 'ethereum', 'crypto']


def is_crypto_market(market: Market) -> bool:
    q = market.question.lower()
    return any(k in q for k in CRYPTO_KEYWORDS)


class Polymarket15MomentumStrategy(BaseStrategy):
    name = "polymarket_15m_momentum"
    description = "15min Crypto Momentum: BTC/ETH direction"
    MIN_CONFIDENCE = 0.3
    MIN_HISTORY = 3
    MIN_VOLUME = 10

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
            price_change = (prices[-1] - prices[0]) / prices[0] if prices[0] > 0 else 0.0

            if abs(price_change) < 0.005:
                continue

            conf = min(abs(price_change) / 0.03, 1.0)

            outcome = "YES" if price_change > 0 else "NO"
            price = m.yes_price if price_change > 0 else m.no_price
            reason = f"CRYPTO {'UP' if price_change > 0 else 'DOWN'} {price_change:+.1%}"

            signals.append(TradeSignal(m, outcome, price, conf, reason))

        signals.sort(key=lambda s: s.confidence, reverse=True)
        return signals
