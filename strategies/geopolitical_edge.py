"""
Geopolitical Edge: combina Volume Hawk (dónde apostar) + Kelly Master (cuánto apostar).
Especializado en mercados de conflictos, elecciones y política global.
Horizonte: 7–120 días.
"""
import math

from api.polymarket_client import Market, PolymarketClient
from engine.portfolio import Portfolio
from strategies.base import BaseStrategy, TradeSignal

GEO_KEYWORDS = [
    # Elecciones y política
    "election", "president", "prime minister", "senator", "congress", "parliament",
    "democrat", "republican", "vote", "ballot", "poll", "campaign", "coalition",
    "government", "minister", "chancellor", "mayor", "governor",
    # Conflictos y geopolítica
    "war", "conflict", "ceasefire", "invasion", "troops", "military", "nato",
    "sanctions", "treaty", "coup", "referendum", "nuclear", "missile",
    "ukraine", "russia", "china", "taiwan", "iran", "north korea",
    "israel", "gaza", "hamas", "middle east", "hezbollah",
    # Defensa y seguridad
    "defense", "defence", "army", "navy", "air force", "weapon", "attack",
    "terrorism", "alliance", "security council", "un ", "united nations",
]


def _is_geopolitical(question: str) -> bool:
    q = question.lower()
    return any(kw in q for kw in GEO_KEYWORDS)


class GeopoliticalEdgeStrategy(BaseStrategy):
    name = "geopolitical_edge"
    description = "Geo/Politica: volume + Kelly"
    MIN_DAYS = 7
    MAX_DAYS = 120
    MIN_VOLUME = 2000
    MIN_KELLY = 0.008

    def _has_real_history(self, market_id: str) -> bool:
        history = self.client.history.get(market_id)
        if len(history) < 2:
            return False
        prices = [h[1] for h in history]
        return max(prices) - min(prices) > 0.001

    def _volume_score(self, m: Market) -> float:
        """0–1: cuánto signal de volumen inteligente hay."""
        history = self.client.history.get(m.id)
        if len(history) >= 3:
            vol_ratio = self.client.history.volume_ratio(m.id)
            if vol_ratio >= 1.2:
                return min((vol_ratio - 1) / 3, 1.0)
        # Fallback: score por liquidez absoluta
        return min(m.volume / 200_000, 0.6)

    def _kelly_edge(self, m: Market) -> tuple[str, float, float]:
        """Retorna (outcome, price, kelly_fraction)."""
        if self._has_real_history(m.id):
            change = self.client.history.price_change(m.id, lookback=4)
            vol_ratio = self.client.history.volume_ratio(m.id)
            vol_nudge = math.log1p(max(vol_ratio - 1, 0)) * 0.02
            direction = 1 if change >= 0 else -1
            fair_yes = m.yes_price + vol_nudge * direction + change * 0.3
        else:
            fair_yes = m.yes_price * 0.72 + 0.5 * 0.28

        fair_yes = max(0.02, min(0.98, fair_yes))

        if fair_yes > m.yes_price:
            outcome, p_win, mkt_price = "YES", fair_yes, m.yes_price
        else:
            outcome, p_win, mkt_price = "NO", 1 - fair_yes, m.no_price

        if mkt_price <= 0 or mkt_price >= 1:
            return outcome, mkt_price, 0.0
        b = (1 - mkt_price) / mkt_price
        q = 1 - p_win
        kelly = max(0.0, min((b * p_win - q) / b, 0.25))
        return outcome, mkt_price, kelly

    def generate_signals(self, markets: list[Market]) -> list[TradeSignal]:
        signals = []
        for m in markets:
            if not _is_geopolitical(m.question):
                continue
            if m.volume < self.MIN_VOLUME:
                continue
            dte = m.days_to_expiry
            if not (self.MIN_DAYS <= dte <= self.MAX_DAYS):
                continue

            vol_score = self._volume_score(m)
            outcome, price, kelly = self._kelly_edge(m)

            if kelly < self.MIN_KELLY:
                continue

            # Confianza combinada: volumen * kelly
            conf = (vol_score * 0.4 + min(kelly / 0.15, 1.0) * 0.6)
            dte_label = f"{dte:.0f}d"
            signals.append(TradeSignal(
                m, outcome, price, conf,
                f"GEO kelly={kelly:.1%} vol={vol_score:.2f} {dte_label}"
            ))
        return signals
