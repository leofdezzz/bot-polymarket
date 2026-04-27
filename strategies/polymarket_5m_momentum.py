"""
Polymarket 5-minute BTC Up/Down Trading Bot
Aggressive momentum: follows window delta + tick trend.
Buys YES when BTC up vs window open, NO when down.
"""
import logging
import time

from api.polymarket_client import Market, PolymarketClient, BinancePrice
from engine.portfolio import Portfolio
from strategies.base import BaseStrategy, TradeSignal

logger = logging.getLogger(__name__)


class Polymarket5MomentumStrategy(BaseStrategy):
    name = "polymarket_5m_momentum"
    description = "5min BTC Momentum: window delta + tick trend"
    MIN_CONFIDENCE = 0.25
    WINDOW_SECONDS = 300
    SNIPE_OFFSET = 10

    def run(self):
        window_ts = self._get_window_ts()
        secs_to_close = self._secs_to_close(window_ts)

        # Resolve all expired positions first
        self.client.resolve_all_expired_positions(self.portfolio)

        market = self._find_window_market(window_ts)
        if market:
            self.portfolio.check_and_close_expired(market.id, "5min", market.minutes_to_expiry)

        logger.info(f"[5m_momentum] window_ts={window_ts} secs_to_close={secs_to_close}")

        if secs_to_close <= 0:
            return

        if secs_to_close > self.SNIPE_OFFSET + 30:
            logger.info(f"[5m_momentum] Too early ({secs_to_close}s remaining)")
            return

        if not market:
            market = self._find_window_market(window_ts)
        if not market:
            logger.info(f"[5m_momentum] No market found")
            return

        open_ids = {p.market_id for p in self.portfolio.open_positions()}
        if market.id in open_ids:
            self.portfolio.update_prices(market.id, market.yes_price)
            return

        bp = BinancePrice.get_instance()
        best_score = None
        best_signal = None
        deadline = time.time() + max(secs_to_close - 5, 1)

        while time.time() < deadline:
            open_price, current_price, _ = bp.get_window_info()
            if open_price > 0:
                score = self._calculate_score(open_price, current_price, bp)
                if best_score is None or abs(score) > abs(best_score):
                    best_score = score
                    best_signal = self._build_signal(market, score)
                    if abs(score) >= 4:
                        break

            remaining = self._secs_to_close(window_ts)
            if remaining <= 5:
                break
            time.sleep(2)

        if best_signal and best_signal.confidence >= self.MIN_CONFIDENCE:
            logger.info(f"[5m_momentum] BUY {best_signal.outcome} @ {best_signal.price:.3f} conf={best_signal.confidence:.2f} reason={best_signal.reason}")
            self.portfolio.buy(
                market_id=best_signal.market.id,
                question=best_signal.market.question,
                outcome=best_signal.outcome,
                price=best_signal.price,
                market_type=best_signal.market_type,
                end_date=best_signal.end_date,
            )

    def generate_signals(self, markets: list[Market]) -> list[TradeSignal]:
        return []

    def _get_window_ts(self) -> int:
        return int(time.time()) - (int(time.time()) % self.WINDOW_SECONDS)

    def _secs_to_close(self, window_ts: int) -> int:
        return (window_ts + self.WINDOW_SECONDS) - int(time.time())

    def _find_window_market(self, window_ts: int) -> Market | None:
        slug = f"btc-updown-5m-{window_ts}"
        return self.client.get_fast_market_by_slug(slug)

    def _calculate_score(self, open_price: float, current_price: float, bp: BinancePrice) -> float:
        if open_price == 0:
            return 0.0
        delta_pct = (current_price - open_price) / open_price * 100

        if delta_pct > 0.10:
            window_weight = 7
        elif delta_pct > 0.05:
            window_weight = 5
        elif delta_pct > 0.02:
            window_weight = 3
        elif delta_pct > 0.005:
            window_weight = 1
        else:
            window_weight = 0

        score = window_weight if delta_pct > 0 else -window_weight

        tick_trend = bp.get_tick_trend()
        if abs(tick_trend) > 0.2:
            score += tick_trend * 2

        return score

    def _build_signal(self, m: Market, score: float) -> TradeSignal:
        direction = "UP" if score > 0 else "DOWN"
        conf = min(abs(score) / 7.0, 1.0)
        outcome = "YES" if score > 0 else "NO"
        price = m.yes_price if score > 0 else m.no_price
        reason = f"MOM {direction} score={score:.1f}"
        return TradeSignal(m, outcome, price, conf, reason)