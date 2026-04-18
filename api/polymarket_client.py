import json
import time
import logging
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Optional

import requests

import config

logger = logging.getLogger(__name__)

HEADERS = {"User-Agent": "polymarket-paper-trader/1.0"}
CACHE_TTL = 25  # segundos — menor que el intervalo del bot para siempre tener datos frescos


class Market:
    """Represents a single Polymarket market with parsed data."""

    def __init__(self, raw: dict):
        self.id: str = str(raw.get("id", ""))
        self.question: str = raw.get("question", "Unknown")
        self.active: bool = raw.get("active", False)
        self.closed: bool = raw.get("closed", True)
        self.volume: float = self._parse_float(raw.get("volume", 0))
        self.liquidity: float = self._parse_float(raw.get("liquidity", 0))
        self.end_date: str = raw.get("endDate", "")

        prices = self._parse_prices(raw.get("outcomePrices", "[]"))
        self.yes_price: float = prices[0] if len(prices) >= 2 else 0.5
        self.no_price: float = prices[1] if len(prices) >= 2 else 0.5

        clob_ids = self._parse_list(raw.get("clobTokenIds", "[]"))
        self.yes_token: str = clob_ids[0] if len(clob_ids) >= 1 else ""
        self._days_cache: float | None = None
        self.no_token: str = clob_ids[1] if len(clob_ids) >= 2 else ""

    @staticmethod
    def _parse_float(val) -> float:
        try:
            return float(val)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _parse_prices(raw) -> list[float]:
        try:
            if isinstance(raw, str):
                parsed = json.loads(raw)
            else:
                parsed = raw
            return [float(p) for p in parsed]
        except Exception:
            return [0.5, 0.5]

    @staticmethod
    def _parse_list(raw) -> list[str]:
        try:
            if isinstance(raw, str):
                parsed = json.loads(raw)
            else:
                parsed = raw
            return [str(x) for x in parsed]
        except Exception:
            return []

    @property
    def days_to_expiry(self) -> float:
        if not self.end_date:
            return 999.0
        try:
            end = datetime.fromisoformat(self.end_date.replace("Z", "+00:00"))
            return max(0.0, (end - datetime.now(timezone.utc)).total_seconds() / 86400)
        except Exception:
            return 999.0

    @property
    def price_sum(self) -> float:
        return self.yes_price + self.no_price

    def is_tradeable(self) -> bool:
        return (
            self.active
            and not self.closed
            and self.volume >= config.MIN_VOLUME
            and self.liquidity >= config.MIN_LIQUIDITY
            and 0.01 < self.yes_price < 0.99
        )


class PriceHistory:
    """Rolling window of (timestamp, yes_price, volume) per market."""

    def __init__(self, maxlen: int = 20):
        self._data: dict[str, deque] = {}
        self._lock = threading.Lock()

    def record(self, market_id: str, yes_price: float, volume: float):
        with self._lock:
            if market_id not in self._data:
                self._data[market_id] = deque(maxlen=20)
            self._data[market_id].append((time.time(), yes_price, volume))

    def get(self, market_id: str) -> list[tuple]:
        with self._lock:
            return list(self._data.get(market_id, []))

    def price_change(self, market_id: str, lookback: int = 3) -> float:
        """Returns % price change over last `lookback` observations."""
        history = self.get(market_id)
        if len(history) < 2:
            return 0.0
        window = history[-min(lookback, len(history)):]
        oldest_price = window[0][1]
        newest_price = window[-1][1]
        if oldest_price == 0:
            return 0.0
        return (newest_price - oldest_price) / oldest_price

    def volume_ratio(self, market_id: str) -> float:
        """Ratio of latest volume delta vs average volume delta."""
        history = self.get(market_id)
        if len(history) < 3:
            return 1.0
        deltas = [
            abs(history[i][2] - history[i - 1][2])
            for i in range(1, len(history))
        ]
        avg = sum(deltas[:-1]) / max(len(deltas) - 1, 1)
        if avg == 0:
            return 1.0
        return deltas[-1] / avg


class PolymarketClient:
    """Fetches and caches market data from the Gamma API."""

    def __init__(self):
        self._cache: list[Market] = []
        self._cache_time: float = 0.0
        self._lock = threading.Lock()
        self.history = PriceHistory()

    def _fetch_markets(self, limit: int = 200) -> list[dict]:
        params = {"closed": "false", "active": "true", "limit": limit}
        try:
            resp = requests.get(
                f"{config.GAMMA_API}/markets",
                params=params,
                headers=HEADERS,
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else data.get("markets", [])
        except Exception as e:
            logger.warning(f"Error fetching markets: {e}")
            return []

    def get_markets(self, force_refresh: bool = False) -> list[Market]:
        with self._lock:
            now = time.time()
            if force_refresh or now - self._cache_time > CACHE_TTL:
                raw = self._fetch_markets()
                if raw:  # solo actualiza cache si la petición tuvo éxito
                    markets = [Market(m) for m in raw]
                    tradeable = [m for m in markets if m.is_tradeable()]
                    self._cache = tradeable
                    self._cache_time = now
                    logger.info(f"Fetched {len(self._cache)} tradeable markets")

            # Registra historial en cada llamada (incluso cache hit) para acumular señales
            for m in self._cache:
                self.history.record(m.id, m.yes_price, m.volume)

            return list(self._cache)

    def get_market(self, market_id: str) -> Optional[Market]:
        markets = self.get_markets()
        for m in markets:
            if m.id == market_id:
                return m
        return None
