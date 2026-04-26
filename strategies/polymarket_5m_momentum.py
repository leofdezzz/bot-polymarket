"""
Polymarket 5-minute Momentum + Volume Strategy:
Buys when price change > threshold with volume confirmation.
For fast-resolving markets (5 min).
"""
from api.polymarket_client import Market, PolymarketClient
from engine.portfolio import Portfolio
from strategies.base import BaseStrategy, TradeSignal


class Polymarket5MomentumStrategy(BaseStrategy):
    name = "polymarket_5m_momentum"
    description = "5min Momentum+Vol: sigue tendencias con volumen"
    PRICE_CHANGE_THRESHOLD = 0.008
    VOLUME_RATIO_MIN = 1.15
    MIN_HISTORY = 2
    MIN_VOLUME = 100

    def _has_momentum(self, market_id: str) -> tuple[bool, float, float]:
        history = self.client.history.get(market_id)
        if len(history) < self.MIN_HISTORY:
            return False, 0.0, 0.0
        prices = [h[1] for h in history]
        volumes = [h[2] for h in history]

        price_change = (prices[-1] - prices[0]) / prices[0] if prices[0] > 0 else 0.0

        if len(volumes) >= 2:
            vol_ratio = volumes[-1] / max(volumes[0], 1) if volumes[0] > 0 else 1.0
        else:
            vol_ratio = 1.0

        return abs(price_change) >= self.PRICE_CHANGE_THRESHOLD, price_change, vol_ratio

    def generate_signals(self, markets: list[Market]) -> list[TradeSignal]:
        signals = []
        for m in markets:
            if m.volume < self.MIN_VOLUME:
                continue

            has_momentum, change, vol_ratio = self._has_momentum(m.id)

            if has_momentum and vol_ratio >= self.VOLUME_RATIO_MIN:
                conf = min(abs(change) / 0.03, 1.0) * min(vol_ratio / 2.0, 1.0)
                outcome = "YES" if change > 0 else "NO"
                price = m.yes_price if outcome == "YES" else m.no_price
                signals.append(TradeSignal(m, outcome, price, conf,
                                           f"MOM5m {change:+.1%} vol:{vol_ratio:.1f}"))
            elif vol_ratio >= self.VOLUME_RATIO_MIN * 1.5:
                conf = min(vol_ratio / 3.0, 1.0) * 0.4
                outcome = "YES" if m.yes_price < 0.5 else "NO"
                price = m.yes_price if outcome == "YES" else m.no_price
                signals.append(TradeSignal(m, outcome, price, conf,
                                           f"VOL5m {vol_ratio:.1f}"))

        return signals
