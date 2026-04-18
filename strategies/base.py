from abc import ABC, abstractmethod
from typing import Optional

from api.polymarket_client import Market, PolymarketClient
from engine.portfolio import Portfolio


class TradeSignal:
    def __init__(self, market: Market, outcome: str, price: float, confidence: float, reason: str):
        self.market = market
        self.outcome = outcome     # "YES" or "NO"
        self.price = price         # entry price
        self.confidence = confidence  # 0-1, used to filter weak signals
        self.reason = reason


class BaseStrategy(ABC):
    """Abstract base for all paper trading strategies."""

    name: str = "base"
    description: str = ""
    MIN_CONFIDENCE = 0.3

    def __init__(self, client: PolymarketClient, portfolio: Portfolio):
        self.client = client
        self.portfolio = portfolio

    def run(self):
        """Fetch markets, generate signals, execute trades, update prices."""
        markets = self.client.get_markets()
        open_ids = {p.market_id for p in self.portfolio.open_positions()}

        # Update prices of open positions
        for market in markets:
            if market.id in open_ids:
                self.portfolio.update_prices(market.id, market.yes_price)

        # Generate and execute new signals
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
            )

    @abstractmethod
    def generate_signals(self, markets: list[Market]) -> list[TradeSignal]:
        """Return list of trade signals for the given markets."""
        ...
