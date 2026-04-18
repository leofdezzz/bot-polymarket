"""
Contrarian Ace: Fades extreme consensus.
Buys YES when market says <12% chance (underdog longshots).
Buys NO when market says >88% chance (fades heavy favorites).
Thesis: prediction markets overestimate certainty at extremes.
"""
from api.polymarket_client import Market, PolymarketClient
from engine.portfolio import Portfolio
from strategies.base import BaseStrategy, TradeSignal


class ContrarianStrategy(BaseStrategy):
    name = "contrarian_ace"
    description = "Contrarian: fade extreme consensus"
    LONGSHOT_MAX = 0.12
    FAVORITE_MIN = 0.88
    MIN_VOLUME = 2000
    MIN_DAYS, MAX_DAYS = 14, 180  # longshots necesitan tiempo para materializarse

    def generate_signals(self, markets: list[Market]) -> list[TradeSignal]:
        signals = []
        for m in markets:
            if not (self.MIN_DAYS <= m.days_to_expiry <= self.MAX_DAYS):
                continue
            if m.volume < self.MIN_VOLUME:
                continue

            if m.yes_price < self.LONGSHOT_MAX:
                confidence = (self.LONGSHOT_MAX - m.yes_price) / self.LONGSHOT_MAX
                signals.append(TradeSignal(m, "YES", m.yes_price, confidence,
                                           f"LONGSHOT {m.yes_price:.2%}"))

            elif m.yes_price > self.FAVORITE_MIN:
                confidence = (m.yes_price - self.FAVORITE_MIN) / (1 - self.FAVORITE_MIN)
                signals.append(TradeSignal(m, "NO", m.no_price, confidence,
                                           f"FADE {m.yes_price:.2%}"))
        return signals
