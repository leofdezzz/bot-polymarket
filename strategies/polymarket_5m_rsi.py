"""
Polymarket 5-minute RSI Strategy for Crypto:
Uses RSI on Binance BTC price to find oversold/overbought reversals.
Buys YES when RSI oversold (expecting bounce), NO when RSI overbought.
"""
import logging
import time

from api.polymarket_client import Market, PolymarketClient, BinancePrice
from engine.portfolio import Portfolio
from strategies.base import BaseStrategy, TradeSignal

logger = logging.getLogger(__name__)


class Polymarket5RSIStrategy(BaseStrategy):
    name = "polymarket_5m_rsi"
    description = "5min RSI: oversold bounce / overbought fade"
    MIN_CONFIDENCE = 0.25
    WINDOW_SECONDS = 300
    SNIPE_OFFSET = 10
    RSI_PERIOD = 14
    RSI_OVERSOLD = 30
    RSI_OVERBOUGHT = 70

    def run(self):
        window_ts = self._get_window_ts()
        secs_to_close = self._secs_to_close(window_ts)

        self.client.resolve_all_expired_positions(self.portfolio)

        market = self._find_window_market(window_ts)
        if market:
            self.portfolio.check_and_close_expired(market.id, "5min", market.minutes_to_expiry)

        logger.info(f"[5m_rsi] window_ts={window_ts} secs_to_close={secs_to_close}")

        if secs_to_close <= 0:
            return

        if secs_to_close > self.SNIPE_OFFSET + 30:
            logger.info(f"[5m_rsi] Too early ({secs_to_close}s remaining)")
            return

        if not market:
            market = self._find_window_market(window_ts)
        if not market:
            logger.info(f"[5m_rsi] No market found")
            return

        open_ids = {p.market_id for p in self.portfolio.open_positions()}
        if market.id in open_ids:
            self.portfolio.update_prices(market.id, market.yes_price)
            return

        bp = BinancePrice.get_instance()
        best_signal = None
        best_score = None
        deadline = time.time() + max(secs_to_close - 5, 1)

        while time.time() < deadline:
            open_price, current_price, _ = bp.get_window_info()
            if open_price > 0:
                score = self._calculate_score(open_price, current_price, bp)
                if best_score is None or abs(score) > abs(best_score):
                    best_score = score
                    best_signal = self._build_signal(market, score)
                    if abs(score) >= 3:
                        break

            remaining = self._secs_to_close(window_ts)
            if remaining <= 5:
                break
            time.sleep(2)

        if best_signal and best_signal.confidence >= self.MIN_CONFIDENCE:
            logger.info(f"[5m_rsi] BUY {best_signal.outcome} @ {best_signal.price:.3f} conf={best_signal.confidence:.2f} reason={best_signal.reason}")
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

        window_delta = (current_price - open_price) / open_price * 100

        rsi = bp.get_rsi()
        conf_from_rsi = 0.0

        if rsi < self.RSI_OVERSOLD:
            conf_from_rsi = (self.RSI_OVERSOLD - rsi) / self.RSI_OVERSOLD
            score = 5 + conf_from_rsi * 2
        elif rsi > self.RSI_OVERBOUGHT:
            conf_from_rsi = (rsi - self.RSI_OVERBOUGHT) / (100 - self.RSI_OVERBOUGHT)
            score = -(5 + conf_from_rsi * 2)
        else:
            score = window_delta / 0.02 * 2

        return score

    def _build_signal(self, m: Market, score: float) -> TradeSignal:
        direction = "UP" if score > 0 else "DOWN"
        conf = min(abs(score) / 7.0, 1.0)
        outcome = "YES" if score > 0 else "NO"
        price = m.yes_price if score > 0 else m.no_price
        reason = f"RSI {direction} score={score:.1f}"
        return TradeSignal(m, outcome, price, conf, reason)