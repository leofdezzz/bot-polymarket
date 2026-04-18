"""
Volume Hawk: dos modos.
- Con historial REAL (volumen con variación real): detecta picos 1.3x + movimiento precio
- Fallback: mercados equilibrados (35–65%) con alta liquidez
"""
from api.polymarket_client import Market, PolymarketClient
from engine.portfolio import Portfolio
from strategies.base import BaseStrategy, TradeSignal


class VolumeSpikeStrategy(BaseStrategy):
    name = "volume_hawk"
    description = "Volumen: señales de dinero inteligente"
    VOLUME_RATIO_MIN = 1.3
    PRICE_CHANGE_MIN = 0.003
    MIN_VOLUME_FALLBACK = 5000
    BALANCE_MIN = 0.35
    MIN_DAYS, MAX_DAYS = 7, 60   # señales de volumen relevantes a medio plazo

    def _has_real_history(self, market_id: str) -> bool:
        history = self.client.history.get(market_id)
        if len(history) < 3:
            return False
        volumes = [h[2] for h in history]
        return max(volumes) - min(volumes) > 10  # alguna variación de volumen real

    def generate_signals(self, markets: list[Market]) -> list[TradeSignal]:
        signals = []
        for m in markets:
            if not (self.MIN_DAYS <= m.days_to_expiry <= self.MAX_DAYS):
                continue
            if self._has_real_history(m.id):
                vol_ratio = self.client.history.volume_ratio(m.id)
                price_change = self.client.history.price_change(m.id, lookback=2)
                if vol_ratio < self.VOLUME_RATIO_MIN or abs(price_change) < self.PRICE_CHANGE_MIN:
                    continue
                conf = min((vol_ratio - 1) / 3, 1.0) * min(abs(price_change) / 0.05, 1.0)
                outcome = "YES" if price_change > 0 else "NO"
                price = m.yes_price if outcome == "YES" else m.no_price
                signals.append(TradeSignal(m, outcome, price, conf,
                                           f"VOL x{vol_ratio:.1f} {price_change:+.2%}"))
            else:
                # Fallback: mercados equilibrados de alta liquidez
                if m.volume < self.MIN_VOLUME_FALLBACK:
                    continue
                if not (self.BALANCE_MIN <= m.yes_price <= 1 - self.BALANCE_MIN):
                    continue
                outcome = "YES" if m.yes_price >= 0.5 else "NO"
                price = m.yes_price if outcome == "YES" else m.no_price
                conf = min(m.volume / 100_000, 1.0) * 0.55
                signals.append(TradeSignal(m, outcome, price, conf,
                                           f"LIQ {m.yes_price:.0%} v={m.volume/1000:.0f}k"))
        return signals
