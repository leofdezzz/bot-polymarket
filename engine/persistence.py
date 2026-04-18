import json
import logging
from pathlib import Path

from engine.portfolio import Portfolio, Position

logger = logging.getLogger(__name__)

STATE_DIR      = Path("state")
PORTFOLIOS_FILE = STATE_DIR / "portfolios.json"
HISTORY_FILE    = STATE_DIR / "pnl_history.json"


# ── Serialización de Position ────────────────────────────────────────────────

def _pos_to_dict(p: Position) -> dict:
    return {
        "market_id":    p.market_id,
        "question":     p.question,
        "outcome":      p.outcome,
        "shares":       p.shares,
        "entry_price":  p.entry_price,
        "entry_time":   p.entry_time,
        "current_price": p.current_price,
        "closed":       p.closed,
        "close_price":  p.close_price,
        "close_time":   p.close_time,
        "close_reason": p.close_reason,
    }


def _pos_from_dict(d: dict) -> Position:
    return Position(**d)


# ── Portfolio ────────────────────────────────────────────────────────────────

def portfolio_to_dict(pf: Portfolio) -> dict:
    with pf._lock:
        return {
            "bot_name":       pf.bot_name,
            "initial_balance": pf.initial_balance,
            "cash":           pf.cash,
            "trades_count":   pf.trades_count,
            "wins":           pf.wins,
            "positions":      {mid: _pos_to_dict(p)
                               for mid, p in pf._positions.items()},
            "closed":         [_pos_to_dict(p) for p in pf._closed[-100:]],
        }


def restore_portfolio(pf: Portfolio, data: dict):
    """Carga estado guardado en un portfolio existente."""
    with pf._lock:
        pf.cash         = data["cash"]
        pf.trades_count = data["trades_count"]
        pf.wins         = data["wins"]
        pf._positions   = {mid: _pos_from_dict(pd)
                           for mid, pd in data.get("positions", {}).items()}
        pf._closed      = [_pos_from_dict(pd)
                           for pd in data.get("closed", [])]


# ── Guardar / cargar ─────────────────────────────────────────────────────────

def save_all(traders, pnl_history: dict):
    try:
        STATE_DIR.mkdir(exist_ok=True)
        portfolios = {t.name: portfolio_to_dict(t.portfolio) for t in traders}
        PORTFOLIOS_FILE.write_text(json.dumps(portfolios, indent=2))
        HISTORY_FILE.write_text(json.dumps(pnl_history))
        logger.debug("Estado guardado")
    except Exception as e:
        logger.error(f"Error guardando estado: {e}")


def load_portfolios() -> dict:
    """Retorna {bot_name: dict} o {} si no hay estado guardado."""
    if not PORTFOLIOS_FILE.exists():
        return {}
    try:
        return json.loads(PORTFOLIOS_FILE.read_text())
    except Exception as e:
        logger.error(f"Error cargando portfolios: {e}")
        return {}


def load_history() -> dict:
    """Retorna {bot_name: [{ts, pnl_pct}]} o {} si no hay historial."""
    if not HISTORY_FILE.exists():
        return {}
    try:
        return json.loads(HISTORY_FILE.read_text())
    except Exception as e:
        logger.error(f"Error cargando historial: {e}")
        return {}


def reset_state():
    """Borra todos los archivos de estado guardado."""
    for f in [PORTFOLIOS_FILE, HISTORY_FILE]:
        if f.exists():
            f.unlink()
            logger.info(f"Borrado: {f}")
