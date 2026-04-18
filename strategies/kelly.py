"""
Kelly Master: Kelly Criterion con estimación de edge.
- Con historial REAL: ajusta fair value con señales de momentum y volumen
- Sin historial real: pull del 30% hacia 0.5 genera edge suficiente para operar
"""
import math

from api.polymarket_client import Market, PolymarketClient
from engine.portfolio import Portfolio
from strategies.base import BaseStrategy, TradeSignal


class KellyStrategy(BaseStrategy):
    name = "kelly_master"
    description = "Kelly Criterion: sizing optimo"
    MIN_KELLY = 0.01
    MAX_KELLY = 0.25
    MIN_VOLUME = 1000
    MIN_DAYS, MAX_DAYS = 1, 365  # Kelly no restringe horizonte temporal

    def _has_real_history(self, market_id: str) -> bool:
        history = self.client.history.get(market_id)
        if len(history) < 2:
            return False
        prices = [h[1] for h in history]
        return max(prices) - min(prices) > 0.001

    def _kelly_fraction(self, market_price: float, p_win: float) -> float:
        if market_price <= 0 or market_price >= 1:
            return 0.0
        b = (1 - market_price) / market_price
        q = 1 - p_win
        return max(0.0, min((b * p_win - q) / b, self.MAX_KELLY))

    def _estimate_edge(self, m: Market) -> tuple[str, float, float]:
        if self._has_real_history(m.id):
            price_change = self.client.history.price_change(m.id, lookback=4)
            vol_ratio = self.client.history.volume_ratio(m.id)
            vol_nudge = math.log1p(max(vol_ratio - 1, 0)) * 0.015
            direction = 1 if price_change >= 0 else -1
            fair_yes = m.yes_price + vol_nudge * direction + price_change * 0.25
        else:
            # Pull 30% hacia 0.5: genera edge > MIN_KELLY para mercados no extremos
            fair_yes = m.yes_price * 0.70 + 0.5 * 0.30

        fair_yes = max(0.02, min(0.98, fair_yes))

        if fair_yes > m.yes_price:
            outcome, p_win, market_price = "YES", fair_yes, m.yes_price
        else:
            outcome, p_win, market_price = "NO", 1 - fair_yes, m.no_price

        kelly = self._kelly_fraction(market_price, p_win)
        return outcome, market_price, kelly

    def generate_signals(self, markets: list[Market]) -> list[TradeSignal]:
        signals = []
        for m in markets:
            if not (self.MIN_DAYS <= m.days_to_expiry <= self.MAX_DAYS):
                continue
            if m.volume < self.MIN_VOLUME:
                continue
            if not (0.15 < m.yes_price < 0.85):
                continue
            outcome, price, kelly = self._estimate_edge(m)
            if kelly < self.MIN_KELLY:
                continue
            conf = min(kelly / self.MAX_KELLY, 1.0)
            signals.append(TradeSignal(m, outcome, price, conf,
                                       f"KELLY {kelly:.1%}"))
        return signals
