import time
import threading
import logging
from dataclasses import dataclass, field
from typing import Optional

import config
from api.clob_client import CLOBClient

logger = logging.getLogger(__name__)


@dataclass
class LivePosition:
    market_id: str
    question: str
    outcome: str
    shares: float
    entry_price: float
    entry_time: float = field(default_factory=time.time)
    current_price: float = 0.0
    closed: bool = False
    close_price: float = 0.0
    close_time: float = 0.0
    close_reason: str = ""
    market_type: str = ""
    end_date: str = ""
    order_id: str = ""
    token_id: str = ""

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


class LivePortfolio:
    MAX_POSITION_AGE_DAYS = 7

    def __init__(self, initial_balance: float, bot_name: str, clob_client: CLOBClient):
        self.bot_name = bot_name
        self.initial_balance = initial_balance
        self.cash = initial_balance
        self._positions: dict[str, LivePosition] = {}
        self._closed: list[LivePosition] = []
        self._lock = threading.Lock()
        self.clob = clob_client
        self.trades_count = 0
        self.wins = 0

    def open_positions(self) -> list[LivePosition]:
        with self._lock:
            return [p for p in self._positions.values() if not p.closed]

    def closed_positions(self) -> list[LivePosition]:
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

    def buy(self, market_id: str, question: str, outcome: str, price: float,
            market_type: str = "", end_date: str = "", yes_token: str = "", no_token: str = "") -> Optional[LivePosition]:
        with self._lock:
            if market_id in self._positions and not self._positions[market_id].closed:
                logger.info(f"[{self.bot_name}] SKIP {market_id[:8]} - already in position")
                return None

            trade_cash = self.cash * config.TRADE_SIZE_PCT
            open_count = len([p for p in self._positions.values() if not p.closed])

            if self.cash < trade_cash:
                logger.info(f"[{self.bot_name}] SKIP {market_id[:8]} - insufficient cash ${self.cash:.2f} < ${trade_cash:.2f}")
                return None
            if open_count >= config.MAX_POSITIONS:
                logger.debug(f"[{self.bot_name}] SKIP {market_id[:8]} - max positions reached ({open_count})")
                return None
            if price <= 0:
                logger.info(f"[{self.bot_name}] SKIP {market_id[:8]} - invalid price {price}")
                return None

            token_id = yes_token if outcome == "YES" else no_token
            if not token_id:
                logger.error(f"[{self.bot_name}] No token_id for {outcome} in market {market_id[:8]}")
                return None

            shares = trade_cash / price
            order_id = None
            try:
                if outcome == "YES":
                    order_id = self.clob.place_market_buy(token_id, trade_cash)
                else:
                    order_id = self.clob.place_market_sell(token_id, trade_cash)
            except Exception as e:
                logger.error(f"[{self.bot_name}] Failed to place order: {e}")
                return None

            if not order_id:
                logger.error(f"[{self.bot_name}] No order_id returned for {market_id[:8]}")
                return None

            pos = LivePosition(
                market_id=market_id,
                question=question,
                outcome=outcome,
                shares=shares,
                entry_price=price,
                current_price=price,
                market_type=market_type,
                end_date=end_date,
                order_id=order_id,
                token_id=token_id,
            )
            self._positions[market_id] = pos
            self.cash -= trade_cash
            self.trades_count += 1
            logger.info(f"[{self.bot_name}] LIVE BUY {outcome} {market_id[:8]} {shares:.2f} @ {price:.3f} cost=${trade_cash:.2f} order={order_id}")
            return pos

    def update_prices(self, market_id: str, yes_price: float):
        with self._lock:
            pos = self._positions.get(market_id)
            if pos is None or pos.closed:
                return None

            pos.current_price = yes_price if pos.outcome == "YES" else (1.0 - yes_price)

            reason = None
            if pos.current_price < pos.entry_price * (1 - config.STOP_LOSS_PCT):
                reason = "stop-loss"
            elif pos.current_price > pos.entry_price * (1 + config.TAKE_PROFIT_PCT):
                reason = "take-profit"
            elif pos.outcome == "YES" and yes_price >= 0.97:
                reason = "resolved-YES"
            elif pos.outcome == "NO" and yes_price <= 0.03:
                reason = "resolved-NO"
            elif pos.age_hours >= self.MAX_POSITION_AGE_DAYS * 24:
                reason = "max-age"

            if reason:
                self._close_position(pos, reason)
            return reason

    def check_and_close_expired(self, market_id: str, market_type: str, minutes_to_expiry: float):
        with self._lock:
            pos = self._positions.get(market_id)
            if pos is None or pos.closed:
                return
            if pos.market_type != market_type:
                return
            if minutes_to_expiry > 0:
                return
            self._close_position(pos, "expired")

    def resolve_position(self, market_id: str, won: bool, reason: str):
        with self._lock:
            pos = self._positions.get(market_id)
            if pos is None or pos.closed:
                return
            pos.closed = True
            pos.close_price = 1.0 if won else 0.0
            pos.close_time = time.time()
            pos.close_reason = reason
            if won:
                self.wins += 1
            self.cash += pos.current_value
            logger.info(f"[{self.bot_name}] LIVE RESOLVED {market_id[:8]} outcome={'WIN' if won else 'LOSS'} pnl={pos.unrealized_pnl:.2f} cash={self.cash:.2f}")
            self._closed.append(pos)
            del self._positions[market_id]

    def _close_position(self, pos: LivePosition, reason: str):
        pos.closed = True
        pos.close_price = pos.current_price
        pos.close_time = time.time()
        pos.close_reason = reason
        pnl = pos.realized_pnl
        self.cash += pos.current_value
        if pnl > 0:
            self.wins += 1
        if pos.order_id:
            try:
                self.clob.cancel_order(pos.order_id)
            except Exception as e:
                logger.warning(f"[{self.bot_name}] Failed to cancel order {pos.order_id}: {e}")
        logger.info(f"[{self.bot_name}] LIVE CLOSED {pos.market_id[:8]} {pos.outcome} {reason} pnl={pnl:.2f} value={pos.current_value:.2f}")
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

    def get_live_balance(self) -> float:
        try:
            return self.clob.get_balance()
        except Exception as e:
            logger.error(f"Error fetching live balance: {e}")
            return self.cash
