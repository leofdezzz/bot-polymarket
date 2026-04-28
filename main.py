#!/usr/bin/env python3
"""
Polymarket Trading Bot
Supports both paper trading (simulated) and live trading (real money).

Usage:
    python main.py                                             # Paper only, $50 balance
    python main.py --live --private-key 0x... --live-balance 10  # Live trading
    python main.py --balance 100 --live --private-key 0x... --live-balance 10  # Both modes
"""
import logging
import signal
import sys
import threading
import time

import config
from api.polymarket_client import PolymarketClient
from api.clob_client import CLOBClient
from engine.paper_trader import PaperTrader
from engine.live_trader import LiveTrader
from engine.portfolio import Portfolio
from engine.live_portfolio import LivePortfolio
from engine.persistence import (
    save_all, load_portfolios, load_history,
    restore_portfolio, reset_state,
)
from strategies.contrarian import ContrarianStrategy
from strategies.polymarket_5m_momentum import Polymarket5MomentumStrategy
from strategies.polymarket_5m_rsi import Polymarket5RSIStrategy
from strategies.polymarket_15m_momentum import Polymarket15MomentumStrategy
from strategies.polymarket_15m_mean_rev import Polymarket15MeanRevStrategy
import web.app as web_app

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: [%(name)s] %(message)s",
    handlers=[
        logging.FileHandler("trading.log"),
        logging.StreamHandler(sys.stdout),
    ],
)

PAPER_STRATEGY_CLASSES = [
    Polymarket15MomentumStrategy,
    Polymarket15MeanRevStrategy,
]

LIVE_STRATEGY_CLASSES = [
    Polymarket15MeanRevStrategy,
]

_client: PolymarketClient | None = None
_clob_client: CLOBClient | None = None
_paper_traders: list[PaperTrader] = []
_live_traders: list[LiveTrader] = []
_initial_balance: float = 50.0
_live_balance: float = 10.0
_interval: int = config.UPDATE_INTERVAL
_stop_event = threading.Event()


def build_paper_traders(initial_balance: float, client: PolymarketClient) -> list[PaperTrader]:
    traders = []
    for cls in PAPER_STRATEGY_CLASSES:
        portfolio = Portfolio(initial_balance=initial_balance, bot_name=cls.name + " (PAPER)")
        strategy = cls(client=client, portfolio=portfolio)
        trader = PaperTrader(strategy=strategy, interval=_interval)
        traders.append(trader)
    return traders


def build_live_traders(initial_balance: float, client: PolymarketClient, clob: CLOBClient) -> list[LiveTrader]:
    traders = []
    for cls in LIVE_STRATEGY_CLASSES:
        portfolio = LivePortfolio(initial_balance=initial_balance, bot_name=cls.name + " (LIVE)", clob_client=clob)
        strategy = cls(client=client, portfolio=portfolio)
        trader = LiveTrader(strategy=strategy, interval=_interval)
        traders.append(trader)
    return traders


def start_traders(traders):
    for t in traders:
        t.start()


def stop_traders(traders):
    for t in traders:
        t.stop()


def save_loop():
    while not _stop_event.is_set():
        _stop_event.wait(timeout=60)
        if not _stop_event.is_set():
            all_traders = _paper_traders + _live_traders
            save_all(all_traders, web_app.get_history())


def resolve_loop():
    while not _stop_event.is_set():
        _stop_event.wait(timeout=15)
        if not _stop_event.is_set():
            for t in _paper_traders:
                try:
                    t.strategy.client.resolve_all_expired_positions(t.portfolio)
                except Exception as e:
                    logger.warning(f"[{t.name}] resolve error: {e}")
            for t in _live_traders:
                try:
                    t.strategy.client.resolve_all_expired_positions(t.portfolio)
                except Exception as e:
                    logger.warning(f"[{t.name}] resolve error: {e}")


def history_loop():
    while not _stop_event.is_set():
        web_app.record_history()
        _stop_event.wait(timeout=5)


def restart_callback(new_balance: float, new_live_balance: float, clear: bool = False):
    global _paper_traders, _live_traders, _initial_balance, _live_balance
    _initial_balance = new_balance
    _live_balance = new_live_balance
    stop_traders(_paper_traders)
    stop_traders(_live_traders)
    if clear:
        reset_state()
    _paper_traders = build_paper_traders(new_balance, _client)
    if _clob_client:
        _live_traders = build_live_traders(new_live_balance, _client, _clob_client)
    saved = {} if clear else load_portfolios()
    for t in _paper_traders:
        if t.name in saved:
            restore_portfolio(t.portfolio, saved[t.name])
    history = {} if clear else load_history()
    web_app.init(_paper_traders + _live_traders, new_balance, new_live_balance, restart_callback, history)
    for t in _paper_traders:
        try:
            t.strategy.run()
        except Exception:
            pass
    for t in _live_traders:
        try:
            t.strategy.run()
        except Exception:
            pass
    start_traders(_paper_traders)
    start_traders(_live_traders)
    mode = "reset" if clear else "restart"
    print(f"[{mode}] Paper balance: ${new_balance:,.2f} | Live balance: ${new_live_balance:,.2f}")


def main():
    global _client, _clob_client, _paper_traders, _live_traders
    global _interval, _initial_balance, _live_balance

    args = config.parse_args()
    _interval = args.interval
    _initial_balance = args.balance
    _live_balance = args.live_balance

    is_live_mode = args.live and bool(args.private_key)

    print(f"\nPolymarket Trading Bot")
    print(f"  Mode: {'DUAL (paper + live)' if is_live_mode else 'PAPER ONLY'}")
    print(f"  Conectando a Polymarket API...")

    _client = PolymarketClient()
    markets = _client.get_markets(force_refresh=True)
    if not markets:
        print("Error: no se pudieron obtener mercados. Verifica internet.")
        sys.exit(1)
    print(f"  {len(markets)} mercados activos")

    print(f"  Precalentando historial de precios...")
    for _ in range(3):
        _client.get_markets()
        time.sleep(0.5)

    if args.reset:
        print("  Limpiando estado guardado...")
        reset_state()
        saved_portfolios = {}
        saved_history = {}
    else:
        saved_portfolios = load_portfolios()
        saved_history = load_history()

    if saved_portfolios:
        first = next(iter(saved_portfolios.values()), {})
        _initial_balance = first.get("initial_balance", args.balance)
        print(f"  Estado anterior restaurado (paper balance: ${_initial_balance:,.2f})")
    else:
        print(f"  Sin estado previo — paper balance: ${_initial_balance:,.2f}")

    _paper_traders = build_paper_traders(_initial_balance, _client)

    for t in _paper_traders:
        if t.name in saved_portfolios:
            restore_portfolio(t.portfolio, saved_portfolios[t.name])

    if is_live_mode:
        print(f"  Iniciando modo LIVE")
        try:
            _clob_client = CLOBClient(private_key=args.private_key)
            live_bal = _clob_client.get_balance()
            print(f"  Balance on-chain detectado: ${live_bal:.2f} USDC")
            if live_bal > 0:
                _live_balance = live_bal
                print(f"  Usando balance real: ${_live_balance:.2f}")
            elif args.live_balance > 0:
                _live_balance = args.live_balance
                print(f"  Usando balance override: ${_live_balance:.2f}")
            else:
                print(f"  WARNING: No se detecto balance, usando 0")
            _live_traders = build_live_traders(_live_balance, _client, _clob_client)
        except Exception as e:
            print(f"  ERROR inicializando CLOB client: {e}")
            print(f"  Continuando en modo PAPER ONLY")
            _live_traders = []
            is_live_mode = False
    else:
        _live_traders = []

    web_app.init(_paper_traders + _live_traders, _initial_balance, _live_balance, restart_callback, saved_history)

    def shutdown(signum, frame):
        print("\nGuardando estado...")
        _stop_event.set()
        stop_traders(_paper_traders)
        stop_traders(_live_traders)
        save_all(_paper_traders + _live_traders, web_app.get_history())
        print("Estado guardado. Hasta luego.")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    threading.Thread(target=history_loop, daemon=True, name="history").start()
    threading.Thread(target=save_loop, daemon=True, name="saver").start()
    threading.Thread(target=resolve_loop, daemon=True, name="resolver").start()

    print(f"  Ejecutando estrategias...")
    for t in _paper_traders:
        try:
            t.strategy.run()
        except Exception as e:
            print(f"    {t.name}: {e}")

    for t in _live_traders:
        try:
            t.strategy.run()
        except Exception as e:
            print(f"    {t.name}: {e}")

    start_traders(_paper_traders)
    start_traders(_live_traders)
    print(f"  {len(_paper_traders)} bots paper | {len(_live_traders)} bots live activos")
    print(f"\n  Dashboard: http://localhost:{args.port}")
    print(f"  Ctrl+C para guardar y salir\n")

    web_app.run_flask(host="0.0.0.0", port=args.port)


if __name__ == "__main__":
    main()
