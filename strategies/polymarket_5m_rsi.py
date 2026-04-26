"""
Polymarket 5-minute RSI-like Strategy:
Buys when market is oversold (YES very low) or overbought (YES very high).
Expects reversal at extremes for fast-resolving markets (5 min).
"""
from api.polymarket_client import Market, PolymarketClient
from engine.portfolio import Portfolio
from strategies.base import BaseStrategy, TradeSignal


class Polymarket5RSIStrategy(BaseStrategy):
    name = "polymarket_5m_rsi"
    description = "5min RSI: reversal en extremos"
    RSI_OVERSOLD = 0.15
    RSI_OVERBOUGHT = 0.85
    MIN_VOLUME = 100
    MIN_HISTORY = 3

    def _calculate_rsi(self, market_id: str) -> float:
        history = self.client.history.get(market_id)
        if len(history) < self.MIN_HISTORY:
            return 0.5

        prices = [h[1] for h in history]
        if len(prices) < 2:
            return 0.5

        changes = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        if not changes:
            return 0.5

        gains = [c for c in changes if c > 0]
        losses = [-c for c in changes if c < 0]

        avg_gain = sum(gains) / len(changes) if gains else 0
        avg_loss = sum(losses) / len(changes) if losses else 0

        if avg_loss == 0:
            return 100

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi / 100

    def generate_signals(self, markets: list[Market]) -> list[TradeSignal]:
        signals = []
        for m in markets:
            if m.volume < self.MIN_VOLUME:
                continue

            rsi = self._calculate_rsi(m.id)

            if rsi < self.RSI_OVERSOLD:
                conf = (self.RSI_OVERSOLD - rsi) / self.RSI_OVERSOLD * 0.8
                signals.append(TradeSignal(m, "YES", m.yes_price, conf,
                                           f"RSI5m {rsi:.0%} OVERSOLD"))

            elif rsi > self.RSI_OVERBOUGHT:
                conf = (rsi - self.RSI_OVERBOUGHT) / (1 - self.RSI_OVERBOUGHT) * 0.8
                signals.append(TradeSignal(m, "NO", m.no_price, conf,
                                           f"RSI5m {rsi:.0%} OVERBOUGHT"))

            elif m.yes_price < 0.20:
                conf = (self.RSI_OVERSOLD - m.yes_price) / self.RSI_OVERSOLD * 0.5
                signals.append(TradeSignal(m, "YES", m.yes_price, conf,
                                           f"PRICE5m {m.yes_price:.0%} low"))

            elif m.yes_price > 0.80:
                conf = (m.yes_price - self.RSI_OVERBOUGHT) / (1 - self.RSI_OVERBOUGHT) * 0.5
                signals.append(TradeSignal(m, "NO", m.no_price, conf,
                                           f"PRICE5m {m.yes_price:.0%} high"))

        return signals
