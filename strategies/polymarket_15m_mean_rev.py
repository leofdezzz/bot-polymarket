"""
Polymarket 15-minute Mean Reversion Strategy:
Contrarian - bets against strong momentum when BTC moves > 0.1% from open.
Thesis: in 15min windows, sharp moves often overextend and reverse.
Supports both paper and live trading modes.
"""
import logging
import time

from api.polymarket_client import Market, PolymarketClient, BinancePrice
from engine.portfolio import Portfolio
from strategies.base import BaseStrategy, TradeSignal

logger = logging.getLogger(__name__)


class Polymarket15MeanRevStrategy(BaseStrategy):
    name = "polymarket_15m_mean_rev"
    description = "15min MeanRev: contrarian fade extreme moves"
    MIN_CONFIDENCE = 0.30
    WINDOW_SECONDS = 900
    SNIPE_OFFSET = 10

    def run(self):
        window_ts = self._get_window_ts()
        secs_to_close = self._secs_to_close(window_ts)

        self.client.resolve_all_expired_positions(self.portfolio)

        market = self._find_window_market(window_ts)
        if market:
            self.portfolio.check_and_close_expired(market.id, "15min", market.minutes_to_expiry)

        logger.info(f"[15m_mean] window_ts={window_ts} secs_to_close={secs_to_close}")

        if secs_to_close <= 0:
            return

        if secs_to_close > self.SNIPE_OFFSET + 30:
            logger.info(f"[15m_mean] Too early ({secs_to_close}s remaining)")
            return

        if not market:
            market = self._find_window_market(window_ts)
        if not market:
            logger.info(f"[15m_mean] No market found")
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
                    if abs(score) >= 5:
                        break

            remaining = self._secs_to_close(window_ts)
            if remaining <= 5:
                break
            time.sleep(2)

        if best_signal and best_signal.confidence >= self.MIN_CONFIDENCE:
            logger.info(f"[15m_mean] BUY {best_signal.outcome} @ {best_signal.price:.3f} conf={best_signal.confidence:.2f} reason={best_signal.reason}")
            self._execute_buy(best_signal)

    def _execute_buy(self, signal: TradeSignal):
        is_live = hasattr(self.portfolio, 'clob') and self.portfolio.clob is not None
        if is_live:
            self.portfolio.buy(
                market_id=signal.market.id,
                question=signal.market.question,
                outcome=signal.outcome,
                price=signal.price,
                market_type=signal.market_type,
                end_date=signal.end_date,
                yes_token=signal.market.yes_token,
                no_token=signal.market.no_token,
            )
        else:
            self.portfolio.buy(
                market_id=signal.market.id,
                question=signal.market.question,
                outcome=signal.outcome,
                price=signal.price,
                market_type=signal.market_type,
                end_date=signal.end_date,
            )

    def generate_signals(self, markets: list[Market]) -> list[TradeSignal]:
        return []

    def _get_window_ts(self) -> int:
        return int(time.time()) - (int(time.time()) % self.WINDOW_SECONDS)

    def _secs_to_close(self, window_ts: int) -> int:
        return (window_ts + self.WINDOW_SECONDS) - int(time.time())

    def _find_window_market(self, window_ts: int) -> Market | None:
        slug = f"btc-updown-15m-{window_ts}"
        return self.client.get_fast_market_by_slug(slug)

    def _calculate_score(self, open_price: float, current_price: float, bp: BinancePrice) -> float:
        if open_price == 0:
            return 0.0

        delta_pct = (current_price - open_price) / open_price * 100

        if abs(delta_pct) < 0.05:
            return 0.0

        if delta_pct > 0.10:
            contrarian_score = -7
        elif delta_pct > 0.05:
            contrarian_score = -5
        elif delta_pct > 0.02:
            contrarian_score = -3
        else:
            contrarian_score = 0

        if delta_pct < -0.10:
            contrarian_score = 7
        elif delta_pct < -0.05:
            contrarian_score = 5
        elif delta_pct < -0.02:
            contrarian_score = 3

        return contrarian_score

    def _build_signal(self, m: Market, score: float) -> TradeSignal:
        direction = "UP" if score > 0 else "DOWN"
        conf = min(abs(score) / 7.0, 1.0)
        outcome = "YES" if score > 0 else "NO"
        price = m.yes_price if score > 0 else m.no_price
        reason = f"MEAN_REV {direction} score={score:.1f}"
        return TradeSignal(m, outcome, price, conf, reason)
