"""
Polymarket 15-minute Mean Reversion Strategy:
Buys when current price is significantly below/above historical average.
For medium-resolving markets (15 min).
"""
from api.polymarket_client import Market, PolymarketClient
from engine.portfolio import Portfolio
from strategies.base import BaseStrategy, TradeSignal


class Polymarket15MeanRevStrategy(BaseStrategy):
    name = "polymarket_15m_mean_rev"
    description = "15min MeanRev: reversión a la media"
    DEVIATION_THRESHOLD = 0.15
    MIN_HISTORY = 5
    MIN_VOLUME = 200

    def _calculate_stats(self, market_id: str) -> tuple[float, float, float]:
        history = self.client.history.get(market_id)
        if len(history) < self.MIN_HISTORY:
            return 0.5, 0.5, 0.0

        prices = [h[1] for h in history]

        avg_price = sum(prices) / len(prices)
        max_price = max(prices)
        min_price = min(prices)
        price_range = max_price - min_price if max_price > min_price else 0.01

        deviation = (prices[-1] - avg_price) / price_range if price_range > 0 else 0.0

        return avg_price, deviation, price_range

    def generate_signals(self, markets: list[Market]) -> list[TradeSignal]:
        signals = []
        for m in markets:
            if m.volume < self.MIN_VOLUME:
                continue

            avg_price, deviation, price_range = self._calculate_stats(m.id)

            if abs(deviation) >= self.DEVIATION_THRESHOLD:
                if deviation < 0:
                    conf = abs(deviation) / 0.3 * 0.7
                    signals.append(TradeSignal(m, "YES", m.yes_price, conf,
                                               f"REV15m price<avg {abs(deviation):.0%}"))
                else:
                    conf = abs(deviation) / 0.3 * 0.7
                    signals.append(TradeSignal(m, "NO", m.no_price, conf,
                                               f"REV15m price>avg {abs(deviation):.0%}"))

            if m.yes_price < 0.25 and avg_price > 0.35:
                conf = (avg_price - m.yes_price) / avg_price * 0.6
                signals.append(TradeSignal(m, "YES", m.yes_price, conf,
                                           f"LOW15m {m.yes_price:.0%}<avg{avg_price:.0%}"))

            elif m.yes_price > 0.75 and avg_price < 0.65:
                conf = (m.yes_price - avg_price) / (1 - avg_price) * 0.6
                signals.append(TradeSignal(m, "NO", m.no_price, conf,
                                           f"HIGH15m {m.yes_price:.0%}>avg{avg_price:.0%}"))

        return signals
