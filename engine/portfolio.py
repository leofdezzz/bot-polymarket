import time
import threading
from dataclasses import dataclass, field
from typing import Optional

import config


@dataclass
class Position:
    market_id: str
    question: str
    outcome: str          # "YES" or "NO"
    shares: float
    entry_price: float    # price paid per share
    entry_time: float = field(default_factory=time.time)
    current_price: float = 0.0
    closed: bool = False
    close_price: float = 0.0
    close_time: float = 0.0
    close_reason: str = ""

    @property
    def cost(self) -> float:
        return self.shares * self.entry_price

    @property
    def current_value(self) -> float:
        if self.closed:
            return self.shares * self.close_price
        return self.shares * self.current_price

    @property
    def unrealized_pnl(self) -> float:
        if self.closed:
            return 0.0
        return self.current_value - self.cost

    @property
    def realized_pnl(self) -> float:
        if not self.closed:
            return 0.0
        return self.current_value - self.cost

    @property
    def pnl_pct(self) -> float:
        if self.cost == 0:
            return 0.0
        pnl = self.realized_pnl if self.closed else self.unrealized_pnl
        return pnl / self.cost * 100

    @property
    def age_hours(self) -> float:
        ref = self.close_time if self.closed else time.time()
        return (ref - self.entry_time) / 3600


class Portfolio:
    """Thread-safe portfolio tracker for one bot."""

    MAX_POSITION_AGE_DAYS = 7

    def __init__(self, initial_balance: float, bot_name: str):
        self.bot_name = bot_name
        self.initial_balance = initial_balance
        self.cash = initial_balance
        self._positions: dict[str, Position] = {}  # market_id -> Position
        self._closed: list[Position] = []
        self._lock = threading.Lock()
        self.trades_count = 0
        self.wins = 0

    def open_positions(self) -> list[Position]:
        with self._lock:
            return [p for p in self._positions.values() if not p.closed]

    def closed_positions(self) -> list[Position]:
        with self._lock:
            return list(self._closed)

    def can_open(self, cost: float) -> bool:
        with self._lock:
            open_count = len([p for p in self._positions.values() if not p.closed])
            return (
                self.cash >= cost
                and open_count < config.MAX_POSITIONS
                and cost <= self.cash * config.MAX_POSITION_SIZE_PCT * 3
            )

    def buy(self, market_id: str, question: str, outcome: str, price: float) -> Optional[Position]:
        """Open a position using TRADE_SIZE_PCT of available cash."""
        with self._lock:
            if market_id in self._positions and not self._positions[market_id].closed:
                return None  # already have this market open

            trade_cash = self.cash * config.TRADE_SIZE_PCT
            open_count = len([p for p in self._positions.values() if not p.closed])

            if self.cash < trade_cash or open_count >= config.MAX_POSITIONS or price <= 0:
                return None

            shares = trade_cash / price
            pos = Position(
                market_id=market_id,
                question=question,
                outcome=outcome,
                shares=shares,
                entry_price=price,
                current_price=price,
            )
            self._positions[market_id] = pos
            self.cash -= trade_cash
            self.trades_count += 1
            return pos

    def update_prices(self, market_id: str, yes_price: float):
        """Update position mark-to-market and check stop-loss/take-profit."""
        with self._lock:
            pos = self._positions.get(market_id)
            if pos is None or pos.closed:
                return None

            pos.current_price = yes_price if pos.outcome == "YES" else (1.0 - yes_price)

            reason = None
            # Stop loss
            if pos.current_price < pos.entry_price * (1 - config.STOP_LOSS_PCT):
                reason = "stop-loss"
            # Take profit
            elif pos.current_price > pos.entry_price * (1 + config.TAKE_PROFIT_PCT):
                reason = "take-profit"
            # Market near resolution YES
            elif pos.outcome == "YES" and yes_price >= 0.97:
                reason = "resolved-YES"
            # Market near resolution NO
            elif pos.outcome == "NO" and yes_price <= 0.03:
                reason = "resolved-NO"
            # Max age
            elif pos.age_hours >= self.MAX_POSITION_AGE_DAYS * 24:
                reason = "max-age"

            if reason:
                self._close_position(pos, reason)
            return reason

    def _close_position(self, pos: Position, reason: str):
        """Internal close — caller holds lock."""
        pos.closed = True
        pos.close_price = pos.current_price
        pos.close_time = time.time()
        pos.close_reason = reason
        self.cash += pos.current_value
        if pos.realized_pnl > 0:
            self.wins += 1
        self._closed.append(pos)
        del self._positions[pos.market_id]

    def total_value(self) -> float:
        with self._lock:
            open_val = sum(p.current_value for p in self._positions.values() if not p.closed)
            return self.cash + open_val

    def total_pnl(self) -> float:
        return self.total_value() - self.initial_balance

    def total_pnl_pct(self) -> float:
        return self.total_pnl() / self.initial_balance * 100

    def win_rate(self) -> float:
        if self.trades_count == 0:
            return 0.0
        closed = len(self._closed)
        if closed == 0:
            return 0.0
        return self.wins / closed * 100
