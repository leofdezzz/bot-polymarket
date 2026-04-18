"""
Arbitrage Hunter: dos modos.
- Primario: compra cuando YES+NO < 0.97 (garantía matemática)
- Fallback: "harvest" — compra mercados casi resueltos (>88%) con alta liquidez.
  Son apuestas de baja volatilidad que casi siempre ganan.
  En Polymarket real, el arb casi no existe; este fallback simula capital eficiente.
"""
from api.polymarket_client import Market, PolymarketClient
from engine.portfolio import Portfolio
from strategies.base import BaseStrategy, TradeSignal


class ArbitrageStrategy(BaseStrategy):
    name = "arb_hunter"
    description = "Arbitrage / Harvest baja volatilidad"
    ARB_THRESHOLD = 0.97
    HARVEST_MIN = 0.88
    HARVEST_VOLUME = 2000
    MIN_DAYS, MAX_DAYS = 1, 14   # apuestas rápidas de baja volatilidad

    def generate_signals(self, markets: list[Market]) -> list[TradeSignal]:
        signals = []
        arb_found = False

        for m in markets:
            if not (self.MIN_DAYS <= m.days_to_expiry <= self.MAX_DAYS):
                continue
            price_sum = m.yes_price + m.no_price
            if price_sum < self.ARB_THRESHOLD:
                arb_found = True
                gap = self.ARB_THRESHOLD - price_sum
                conf = min(gap / 0.10, 1.0)
                outcome = "YES" if m.yes_price <= m.no_price else "NO"
                price = m.yes_price if outcome == "YES" else m.no_price
                signals.append(TradeSignal(m, outcome, price, conf,
                                           f"ARB sum={price_sum:.3f}"))

        if not arb_found:
            # Fallback harvest: mercados casi resueltos con alta liquidez
            for m in markets:
                if not (self.MIN_DAYS <= m.days_to_expiry <= self.MAX_DAYS):
                    continue
                if m.volume < self.HARVEST_VOLUME:
                    continue
                if m.yes_price >= self.HARVEST_MIN:
                    conf = (m.yes_price - self.HARVEST_MIN) / (1 - self.HARVEST_MIN) * 0.8
                    signals.append(TradeSignal(m, "YES", m.yes_price, conf,
                                               f"HARVEST YES {m.yes_price:.0%}"))
                elif m.yes_price <= (1 - self.HARVEST_MIN):
                    conf = ((1 - self.HARVEST_MIN) - m.yes_price) / (1 - self.HARVEST_MIN) * 0.8
                    signals.append(TradeSignal(m, "NO", m.no_price, conf,
                                               f"HARVEST NO {m.no_price:.0%}"))

        return signals
