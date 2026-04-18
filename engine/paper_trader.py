import logging
import threading
import time

from api.polymarket_client import PolymarketClient
from engine.portfolio import Portfolio
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)


class PaperTrader:
    """Runs a single strategy on a loop in a background thread."""

    def __init__(self, strategy: BaseStrategy, interval: int = 30):
        self.strategy = strategy
        self.interval = interval
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self.last_run: float = 0.0
        self.error_count = 0
        self.status = "idle"

    @property
    def portfolio(self) -> Portfolio:
        return self.strategy.portfolio

    @property
    def name(self) -> str:
        return self.strategy.name

    def start(self):
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name=self.name)
        self._thread.start()
        self.status = "running"
        logger.info(f"Started bot: {self.name}")

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        self.status = "stopped"

    def _loop(self):
        while not self._stop_event.is_set():
            try:
                self.status = "analyzing"
                self.strategy.run()
                self.last_run = time.time()
                self.error_count = 0
                self.status = "running"
            except Exception as e:
                self.error_count += 1
                self.status = f"error({self.error_count})"
                logger.error(f"[{self.name}] Error: {e}", exc_info=True)

            self._stop_event.wait(timeout=self.interval)
