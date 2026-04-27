import json
import time
import logging
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Optional

import requests
try:
    import websocket
except ImportError:
    websocket = None

import config

logger = logging.getLogger(__name__)

HEADERS = {"User-Agent": "polymarket-paper-trader/1.0"}
CACHE_TTL = 25

BINANCE_WS_URL = "wss://stream.binance.com:9443/ws/btcusdt@kline_1m"
BINANCE_REST_URL = "https://api.binance.com/api/v3"


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

    @property
    def minutes_to_expiry(self) -> float:
        return self.days_to_expiry * 1440

    @property
    def market_type(self) -> str:
        mins = self.minutes_to_expiry
        if mins <= 0:
            return "expired"
        elif mins <= 7:
            return "5min"
        elif mins <= 20:
            return "15min"
        else:
            return "regular"

    @property
    def is_fast_market(self) -> bool:
        return self.market_type in ("5min", "15min")

    def is_tradeable(self) -> bool:
        return (
            self.active
            and not self.closed
            and self.volume >= config.MIN_VOLUME
            and self.liquidity >= config.MIN_LIQUIDITY
            and 0.01 < self.yes_price < 0.99
        )

    def is_tradeable_fast(self, min_volume: float = 10, min_liquidity: float = 10) -> bool:
        return (
            self.active
            and not self.closed
            and self.volume >= min_volume
            and self.liquidity >= min_liquidity
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
        self._all_cache: list[Market] = []
        self._cache_time: float = 0.0
        self._lock = threading.Lock()
        self.history = PriceHistory()
        self._slug_cache: dict[str, tuple[Optional[Market], float]] = {}
        self._slug_cache_ttl: float = 30.0

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

    def _fetch_event_by_slug(self, slug: str) -> dict | None:
        try:
            resp = requests.get(
                f"{config.GAMMA_API}/events",
                params={"slug": slug},
                headers=HEADERS,
                timeout=10,
            )
            resp.raise_for_status()
            events = resp.json()
            if events:
                return events[0]
            return None
        except Exception as e:
            logger.warning(f"Error fetching event {slug}: {e}")
            return None

    def get_markets(self, force_refresh: bool = False) -> list[Market]:
        with self._lock:
            now = time.time()
            if force_refresh or now - self._cache_time > CACHE_TTL:
                raw = self._fetch_markets()
                if raw:
                    markets = [Market(m) for m in raw]
                    self._all_cache = markets
                    tradeable = [m for m in markets if m.is_tradeable()]
                    self._cache = tradeable
                    self._cache_time = now
                    logger.info(f"Fetched {len(self._cache)} tradeable, {len(self._all_cache)} total")

            for m in self._cache:
                self.history.record(m.id, m.yes_price, m.volume)

            return list(self._cache)

    def get_all_markets(self, force_refresh: bool = False) -> list[Market]:
        with self._lock:
            now = time.time()
            if force_refresh or now - self._cache_time > CACHE_TTL:
                raw = self._fetch_markets()
                if raw:
                    markets = [Market(m) for m in raw]
                    self._all_cache = markets
                    tradeable = [m for m in markets if m.is_tradeable()]
                    self._cache = tradeable
                    self._cache_time = now

            for m in self._all_cache:
                self.history.record(m.id, m.yes_price, m.volume)

            return list(self._all_cache)

    def get_fast_markets(self, force_refresh: bool = False) -> list[Market]:
        all_markets = self.get_all_markets(force_refresh)
        return [m for m in all_markets if m.is_fast_market and m.is_tradeable_fast()]

    def get_market(self, market_id: str) -> Optional[Market]:
        markets = self.get_markets()
        for m in markets:
            if m.id == market_id:
                return m
        return None

    def get_fast_market_by_slug(self, slug: str) -> Optional[Market]:
        now = time.time()
        if slug in self._slug_cache:
            cached_market, cached_time = self._slug_cache[slug]
            if now - cached_time < self._slug_cache_ttl:
                return cached_market
        event = self._fetch_event_by_slug(slug)
        if not event:
            self._slug_cache[slug] = (None, now)
            return None
        markets_in_event = event.get("markets", [])
        if not markets_in_event:
            self._slug_cache[slug] = (None, now)
            return None
        raw = markets_in_event[0]

        def pf(v):
            try:
                return float(v)
            except (TypeError, ValueError):
                return 0.0

        def pl(v):
            try:
                if isinstance(v, str):
                    return json.loads(v)
                return v
            except Exception:
                return []

        market = Market.__new__(Market)
        market.id = str(raw.get("id", ""))
        market.question = raw.get("question", "")
        market.active = raw.get("active", False)
        market.closed = raw.get("closed", False)
        market.volume = pf(raw.get("volume", 0))
        market.liquidity = pf(raw.get("liquidity", 0))
        market.end_date = event.get("endDate", "")
        prices_raw = pl(raw.get("outcomePrices", "[]"))
        try:
            market.yes_price = float(prices_raw[0]) if len(prices_raw) >= 2 else 0.5
            market.no_price = float(prices_raw[1]) if len(prices_raw) >= 2 else 0.5
        except (ValueError, TypeError, IndexError):
            market.yes_price = 0.5
            market.no_price = 0.5
        clob_ids = pl(raw.get("clobTokenIds", "[]"))
        market.yes_token = clob_ids[0] if len(clob_ids) >= 1 else ""
        market.no_token = clob_ids[1] if len(clob_ids) >= 2 else ""
        market._days_cache = None
        self._slug_cache[slug] = (market, now)
        return market

    def resolve_market(self, window_ts: int, window_seconds: int) -> str | None:
        """Returns 'UP' if BTC closed higher than open, 'DOWN' otherwise. None on error."""
        open_price, close_price = self.fetch_window_open_price(window_ts)
        if open_price == 0 or close_price == 0:
            return None
        if close_price >= open_price:
            return "UP"
        return "DOWN"

    def fetch_window_open_price(self, window_ts: int, window_seconds: int = 300) -> tuple[float, float]:
        try:
            resp = requests.get(
                f"{BINANCE_REST_URL}/klines",
                params={
                    "symbol": "BTCUSDT",
                    "interval": "1m",
                    "startTime": int(window_ts * 1000),
                    "endTime": int((window_ts + window_seconds) * 1000),
                    "limit": 5,
                },
                timeout=5,
            )
            data = resp.json()
            for k in data:
                open_time = int(k[0])
                if abs(open_time - window_ts * 1000) < 60000:
                    return float(k[1]), float(k[4])
        except Exception as e:
            logger.warning(f"Binance window open error: {e}")
        return 0.0, 0.0

    def resolve_all_expired_positions(self, portfolio: "Portfolio"):
        """Check and close all expired fast-market positions by resolving via Binance."""
        now = time.time()
        for pos in list(portfolio.open_positions()):
            if pos.market_type not in ("5min", "15min"):
                continue
            if not pos.end_date:
                continue
            try:
                end = datetime.fromisoformat(pos.end_date.replace("Z", "+00:00"))
                if end.timestamp() > now:
                    continue
            except Exception:
                continue

            if pos.market_type == "5min":
                window_seconds = 300
            else:
                window_seconds = 900

            window_ts = int(end.timestamp()) - (int(end.timestamp()) % window_seconds)
            outcome = self.resolve_market(window_ts, window_seconds)
            if outcome:
                expected = "YES" if outcome == "UP" else "NO"
                won = pos.outcome == expected
                reason = f"resolved-{outcome}"
                portfolio.resolve_position(pos.market_id, won, reason)
                logger.info(f"[{portfolio.bot_name}] RESOLVED {pos.market_id[:8]} expected={expected} outcome={outcome} won={won}")


class BinancePrice:
    _instance: Optional["BinancePrice"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._current_price: float = 0.0
        self._window_open_price: float = 0.0
        self._window_ts: int = 0
        self._ticks: list[float] = []
        self._price_history: deque[float] = deque(maxlen=100)
        self._ws_started = False
        self._ws_thread: threading.Thread | None = None
        self._ws_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "BinancePrice":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def _get_window_ts(self) -> int:
        now = int(time.time())
        return now - (now % 300)

    def _start_ws(self):
        if self._ws_started:
            return
        try:
            import websocket
            self._ws_started = True

            def on_message(ws, msg):
                import json as j
                data = j.loads(msg)
                k = data.get("k", {})
                self._current_price = float(k.get("c", 0))
                self._price_history.append(self._current_price)
                window_ts = self._get_window_ts()
                if window_ts != self._window_ts:
                    self._window_ts = window_ts
                    self._window_open_price = float(k.get("o", self._current_price))
                    self._ticks = []
                self._ticks.append(self._current_price)

            def on_error(ws, err):
                self._ws_started = False

            def on_close(ws, code, reason):
                self._ws_started = False

            ws = websocket.WebSocketApp(
                BINANCE_WS_URL,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close,
            )
            t = threading.Thread(target=ws.run_forever, daemon=True)
            t.start()
            self._ws_thread = t
        except ImportError:
            logger.warning("websocket-client not installed, using REST fallback")
            self._ws_started = False
        except Exception as e:
            logger.warning(f"Binance WS error: {e}")
            self._ws_started = False

    def get_price(self) -> float:
        if not self._ws_started:
            self._start_ws()
        return self._current_price

    def get_window_info(self) -> tuple[float, float, int]:
        if not self._ws_started:
            self._start_ws()
        window_ts = self._get_window_ts()
        open_price = self._window_open_price
        current_price = self._current_price
        if current_price == 0 or open_price == 0:
            open_price, current_price = self.fetch_window_open_price(window_ts)
            if current_price == 0:
                current_price = self.fetch_rest_price()
                open_price = current_price
        return open_price, current_price, window_ts

    def resolve_market(self, window_ts: int, window_seconds: int) -> str | None:
        """Returns 'UP' if BTC closed higher than open, 'DOWN' otherwise. None on error."""
        open_price, close_price = self.fetch_window_open_price(window_ts)
        if open_price == 0 or close_price == 0:
            return None
        if close_price >= open_price:
            return "UP"
        return "DOWN"

    def resolve_all_expired_positions(self, portfolio: "Portfolio"):
        """Check and close all expired fast-market positions by resolving via Binance."""
        now = time.time()
        for pos in list(portfolio.open_positions()):
            if pos.market_type not in ("5min", "15min"):
                continue
            if not pos.end_date:
                continue
            try:
                end = datetime.fromisoformat(pos.end_date.replace("Z", "+00:00"))
                if end.timestamp() > now:
                    continue
            except Exception:
                continue

            if pos.market_type == "5min":
                window_seconds = 300
            else:
                window_seconds = 900

            window_ts = int(end.timestamp()) - (int(end.timestamp()) % window_seconds)
            outcome = self.resolve_market(window_ts, window_seconds)
            if outcome:
                expected = "YES" if outcome == "UP" else "NO"
                won = pos.outcome == expected
                reason = f"resolved-{outcome}"
                portfolio.resolve_position(pos.market_id, won, reason)
                logger.info(f"[{portfolio.bot_name}] RESOLVED {pos.market_id[:8]} expected={expected} outcome={outcome} won={won}")

    def get_tick_trend(self) -> float:
        if len(self._ticks) < 10:
            return 0.0
        recent = self._ticks[-10:]
        up = sum(1 for i in range(1, len(recent)) if recent[i] > recent[i - 1])
        return (up / (len(recent) - 1)) * 2 - 1

    def get_rsi(self, period: int = 14) -> float:
        history = list(self._price_history)
        if len(history) < period + 1:
            return 50.0
        gains = []
        losses = []
        for i in range(1, len(history)):
            delta = history[i] - history[i - 1]
            if delta > 0:
                gains.append(delta)
            else:
                losses.append(abs(delta))
        if not gains or not losses:
            return 50.0
        avg_gain = sum(gains[-period:]) / period if len(gains) >= period else sum(gains) / len(gains)
        avg_loss = sum(losses[-period:]) / period if len(losses) >= period else sum(losses) / len(losses)
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def fetch_rest_price(self) -> float:
        try:
            resp = requests.get(
                f"{BINANCE_REST_URL}/klines",
                params={"symbol": "BTCUSDT", "interval": "1m", "limit": 2},
                timeout=5,
            )
            data = resp.json()
            if data:
                return float(data[-1][4])
        except Exception as e:
            logger.warning(f"Binance REST error: {e}")
        return 0.0

    def fetch_window_open_price(self, window_ts: int) -> tuple[float, float]:
        try:
            start_iso = datetime.fromtimestamp(window_ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            end_iso = datetime.fromtimestamp(window_ts + 300, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            resp = requests.get(
                f"{BINANCE_REST_URL}/klines",
                params={
                    "symbol": "BTCUSDT",
                    "interval": "1m",
                    "startTime": int(window_ts * 1000),
                    "endTime": int((window_ts + 300) * 1000),
                    "limit": 5,
                },
                timeout=5,
            )
            data = resp.json()
            for k in data:
                open_time = int(k[0])
                if abs(open_time - window_ts * 1000) < 60000:
                    return float(k[1]), float(k[4])
        except Exception as e:
            logger.warning(f"Binance window open error: {e}")
        return 0.0, 0.0
