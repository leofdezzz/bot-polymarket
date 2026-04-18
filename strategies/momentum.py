"""
Momentum Surfer: dos modos.
- Con historial REAL (precios distintos entre observaciones): sigue tendencias >0.5%
- Fallback: mercados con alta convicción (precio >62% o <38%) + volumen alto
"""
from api.polymarket_client import Market, PolymarketClient
from engine.portfolio import Portfolio
from strategies.base import BaseStrategy, TradeSignal


class MomentumStrategy(BaseStrategy):
    name = "momentum_surfer"
    description = "Momentum: tendencias de precio"
    THRESHOLD = 0.005
    CONVICTION_MIN = 0.62
    MIN_VOLUME = 3000
    MIN_DAYS, MAX_DAYS = 7, 45   # tendencias de corto/medio plazo

    def _has_real_history(self, market_id: str) -> bool:
        history = self.client.history.get(market_id)
        if len(history) < 2:
            return False
        # Solo cuenta si los precios han cambiado de verdad
        prices = [h[1] for h in history]
        return max(prices) - min(prices) > 0.001

    def generate_signals(self, markets: list[Market]) -> list[TradeSignal]:
        signals = []
        for m in markets:
            if not (self.MIN_DAYS <= m.days_to_expiry <= self.MAX_DAYS):
                continue
            if self._has_real_history(m.id):
                change = self.client.history.price_change(m.id, lookback=3)
                if abs(change) >= self.THRESHOLD:
                    conf = min(abs(change) / 0.05, 1.0)
                    outcome = "YES" if change > 0 else "NO"
                    price = m.yes_price if outcome == "YES" else m.no_price
                    signals.append(TradeSignal(m, outcome, price, conf,
                                               f"MOM {change:+.2%}"))
            else:
                # Fallback: convicción establecida por precio + volumen
                if m.volume < self.MIN_VOLUME:
                    continue
                if m.yes_price > self.CONVICTION_MIN:
                    conf = (m.yes_price - self.CONVICTION_MIN) / (1 - self.CONVICTION_MIN) * 0.7
                    signals.append(TradeSignal(m, "YES", m.yes_price, conf,
                                               f"CONV YES {m.yes_price:.0%}"))
                elif m.yes_price < (1 - self.CONVICTION_MIN):
                    conf = ((1 - self.CONVICTION_MIN) - m.yes_price) / (1 - self.CONVICTION_MIN) * 0.7
                    signals.append(TradeSignal(m, "NO", m.no_price, conf,
                                               f"CONV NO {m.no_price:.0%}"))
        return signals
