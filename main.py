#!/usr/bin/env python3
"""
Polymarket Paper Trading Simulator
6 bots con estrategias distintas + dashboard web + persistencia de estado.

Uso:
    python main.py                     # $1000 balance, puerto 5000
    python main.py --balance 5000
    python main.py --balance 500 --port 8080 --interval 60
"""
import logging
import signal
import sys
import threading
import time

import config
from api.polymarket_client import PolymarketClient
from engine.paper_trader import PaperTrader
from engine.portfolio import Portfolio
from engine.persistence import (
    save_all, load_portfolios, load_history,
    restore_portfolio, reset_state,
)
from strategies.arbitrage import ArbitrageStrategy
from strategies.contrarian import ContrarianStrategy
from strategies.kelly import KellyStrategy
from strategies.momentum import MomentumStrategy
from strategies.volume_spike import VolumeSpikeStrategy
from strategies.geopolitical_edge import GeopoliticalEdgeStrategy
import web.app as web_app

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[logging.FileHandler("paper_trader.log")],
)

STRATEGY_CLASSES = [
    GeopoliticalEdgeStrategy,
    ArbitrageStrategy,
    MomentumStrategy,
    ContrarianStrategy,
    VolumeSpikeStrategy,
    KellyStrategy,
]

_client: PolymarketClient | None = None
_traders: list[PaperTrader] = []
_initial_balance: float = 1000.0
_interval: int = config.UPDATE_INTERVAL
_stop_event = threading.Event()


def build_traders(initial_balance: float, client: PolymarketClient) -> list[PaperTrader]:
    traders = []
    for cls in STRATEGY_CLASSES:
        portfolio = Portfolio(initial_balance=initial_balance, bot_name=cls.name)
        strategy = cls(client=client, portfolio=portfolio)
        trader = PaperTrader(strategy=strategy, interval=_interval)
        traders.append(trader)
    return traders


def start_traders(traders: list[PaperTrader]):
    for t in traders:
        t.start()


def stop_traders(traders: list[PaperTrader]):
    for t in traders:
        t.stop()


def save_loop():
    """Guarda estado en disco cada 60 segundos."""
    while not _stop_event.is_set():
        _stop_event.wait(timeout=60)
        if not _stop_event.is_set():
            save_all(_traders, web_app.get_history())


def history_loop():
    """Registra snapshot de P&L cada 5 segundos."""
    while not _stop_event.is_set():
        web_app.record_history()
        _stop_event.wait(timeout=5)


def restart_callback(new_balance: float, clear: bool = False):
    global _traders, _initial_balance
    _initial_balance = new_balance
    stop_traders(_traders)
    if clear:
        reset_state()
    _traders = build_traders(new_balance, _client)
    saved = {} if clear else load_portfolios()
    for t in _traders:
        if t.name in saved:
            restore_portfolio(t.portfolio, saved[t.name])
    history = {} if clear else load_history()
    web_app.init(_traders, new_balance, restart_callback, history)
    for t in _traders:
        try:
            t.strategy.run()
        except Exception:
            pass
    start_traders(_traders)
    print(f"[{'reset' if clear else 'restart'}] Balance: ${new_balance:,.2f}")


def parse_args():
    import argparse
    parser = argparse.ArgumentParser(description="Polymarket Paper Trading Simulator")
    parser.add_argument("--balance", type=float, default=config.DEFAULT_BALANCE,
                        help=f"Balance inicial por bot en USDC (default: {config.DEFAULT_BALANCE})")
    parser.add_argument("--interval", type=int, default=config.UPDATE_INTERVAL,
                        help=f"Segundos entre actualizaciones (default: {config.UPDATE_INTERVAL})")
    parser.add_argument("--port", type=int, default=5000,
                        help="Puerto del dashboard web (default: 5000)")
    args, unknown = parser.parse_known_args()
    if unknown:
        print(f"  Aviso: argumentos ignorados: {unknown}")
    return args


def main():
    global _client, _traders, _interval, _initial_balance

    args = parse_args()
    _interval = args.interval
    _initial_balance = args.balance

    print(f"\nPolymarket Paper Trading Simulator")
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

    # Carga estado guardado
    saved_portfolios = load_portfolios()
    saved_history    = load_history()

    if saved_portfolios:
        # Usa el balance guardado del primer bot que tenga estado
        first = next(iter(saved_portfolios.values()), {})
        _initial_balance = first.get("initial_balance", args.balance)
        print(f"  Estado anterior restaurado (balance: ${_initial_balance:,.2f})")
    else:
        print(f"  Sin estado previo — balance inicial: ${_initial_balance:,.2f}")

    _traders = build_traders(_initial_balance, _client)

    # Restaura portfolios guardados
    for t in _traders:
        if t.name in saved_portfolios:
            restore_portfolio(t.portfolio, saved_portfolios[t.name])

    web_app.init(_traders, _initial_balance, restart_callback, saved_history)

    def shutdown(signum, frame):
        print("\nGuardando estado...")
        _stop_event.set()
        stop_traders(_traders)
        save_all(_traders, web_app.get_history())
        print("Estado guardado. Hasta luego.")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Hilos de background
    threading.Thread(target=history_loop, daemon=True, name="history").start()
    threading.Thread(target=save_loop,    daemon=True, name="saver").start()

    # Primera ronda de estrategias
    print(f"  Ejecutando estrategias...")
    for t in _traders:
        try:
            t.strategy.run()
        except Exception as e:
            print(f"    {t.name}: {e}")

    start_traders(_traders)
    print(f"  {len(_traders)} bots activos")
    print(f"\n  Dashboard: http://localhost:{args.port}")
    print(f"  Ctrl+C para guardar y salir\n")

    web_app.run_flask(host="0.0.0.0", port=args.port)


if __name__ == "__main__":
    main()
