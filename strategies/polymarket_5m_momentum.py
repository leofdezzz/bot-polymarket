"""
Polymarket 5-minute Crypto Direction Strategy:
Operates ONLY on 5-minute Polymarket markets about BTC/ETH price direction.
Buys YES when price going up, NO when going down.
"""
import logging

from api.polymarket_client import Market, PolymarketClient
from engine.portfolio import Portfolio
from strategies.base import BaseStrategy, TradeSignal

logger = logging.getLogger(__name__)

CRYPTO_KEYWORDS = ['btc', 'bitcoin', 'eth', 'ethereum', 'crypto']
DIRECTION_KEYWORDS = ['up', 'down', 'higher', 'lower', 'above', 'below', 'increase', 'decrease', 'rise', 'fall']


def is_crypto_direction_market(market: Market) -> bool:
    q = market.question.lower()
    has_crypto = any(k in q for k in CRYPTO_KEYWORDS)
    has_direction = any(k in q for k in DIRECTION_KEYWORDS)
    return has_crypto and has_direction


class Polymarket5MomentumStrategy(BaseStrategy):
    name = "polymarket_5m_momentum"
    description = "5min Crypto: BTC/ETH up/down"
    MIN_CONFIDENCE = 0.3
    MIN_HISTORY = 2
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
            if m.market_type != "5min":
                continue
            if not is_crypto_direction_market(m):
                continue
            if not m.is_tradeable_fast(min_volume=self.MIN_VOLUME, min_liquidity=10):
                continue

            history = self.client.history.get(m.id)
            if len(history) < self.MIN_HISTORY:
                continue

            prices = [h[1] for h in history]
            price_change = (prices[-1] - prices[0]) / prices[0] if prices[0] > 0 else 0.0

            if abs(price_change) < 0.003:
                continue

            conf = min(abs(price_change) / 0.02, 1.0)

            q = m.question.lower()
            if any(w in q for w in ['up', 'higher', 'above', 'increase', 'rise']):
                outcome = "YES"
                price = m.yes_price
                reason = f"UP {price_change:+.1%}"
            elif any(w in q for w in ['down', 'lower', 'below', 'decrease', 'fall']):
                outcome = "NO"
                price = m.no_price
                reason = f"DOWN {price_change:+.1%}"
            else:
                outcome = "YES" if price_change > 0 else "NO"
                price = m.yes_price if price_change > 0 else m.no_price
                reason = f"DIR {price_change:+.1%}"

            signals.append(TradeSignal(m, outcome, price, conf, reason))

        signals.sort(key=lambda s: s.confidence, reverse=True)
        return signals
