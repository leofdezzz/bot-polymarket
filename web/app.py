import time
import threading
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

_traders = []
_initial_balance = 1000.0
_initial_live_balance = 10.0
_pnl_history: dict[str, list[dict]] = {}
_history_lock = threading.Lock()
_start_time = time.time()
_restart_callback = None

MAX_HISTORY = 2000

BOT_COLORS = {
    "contrarian_ace":            "#f43f5e",
    "polymarket_5m_momentum":   "#10b981",
    "polymarket_5m_rsi":         "#06b6d4",
    "polymarket_15m_momentum":   "#f97316",
    "polymarket_15m_mean_rev":    "#8b5cf6",
}


def init(traders, initial_balance, initial_live_balance=10.0, restart_cb=None, initial_history: dict | None = None):
    global _traders, _initial_balance, _initial_live_balance, _start_time, _restart_callback, _pnl_history
    _traders = traders
    _initial_balance = initial_balance
    _initial_live_balance = initial_live_balance
    _restart_callback = restart_cb
    _start_time = time.time()
    with _history_lock:
        if initial_history:
            _pnl_history = {
                name: pts[-MAX_HISTORY:]
                for name, pts in initial_history.items()
            }
        else:
            _pnl_history = {t.name: [] for t in traders}


def get_history() -> dict:
    with _history_lock:
        return dict(_pnl_history)


def record_history():
    with _history_lock:
        ts = round(time.time() * 1000)
        for t in _traders:
            entry = {"ts": ts, "pnl_pct": round(t.portfolio.total_pnl_pct(), 3)}
            _pnl_history.setdefault(t.name, []).append(entry)
            if len(_pnl_history[t.name]) > MAX_HISTORY:
                _pnl_history[t.name] = _pnl_history[t.name][-MAX_HISTORY:]


def _base_name(name: str) -> str:
    return name.replace(" (PAPER)", "").replace(" (LIVE)", "")


def _bot_data(t) -> dict:
    pf = t.portfolio
    base = _base_name(t.name)
    positions = []
    for pos in sorted(pf.open_positions(), key=lambda p: p.unrealized_pnl, reverse=True):
        positions.append({
            "question":      pos.question[:60],
            "outcome":       pos.outcome,
            "entry_price":   round(pos.entry_price, 4),
            "current_price": round(pos.current_price, 4),
            "pnl":           round(pos.unrealized_pnl, 2),
            "pnl_pct":       round(pos.pnl_pct, 1),
            "cost":          round(pos.cost, 2),
            "age_h":         round(pos.age_hours, 1),
        })
    closed = pf.closed_positions()
    realized = sum(p.realized_pnl for p in closed)
    return {
        "name":        pf.bot_name,
        "description": t.strategy.description,
        "color":       BOT_COLORS.get(base, "#ffffff"),
        "status":      t.status,
        "total_value": round(pf.total_value(), 2),
        "cash":        round(pf.cash, 2),
        "pnl":         round(pf.total_pnl(), 2),
        "pnl_pct":     round(pf.total_pnl_pct(), 2),
        "realized":    round(realized, 2),
        "trades":      pf.trades_count,
        "closed":      len(closed),
        "win_rate":    round(pf.win_rate(), 1),
        "open_count":  len(pf.open_positions()),
        "positions":   positions,
    }


@app.route("/")
def index():
    return render_template("dashboard.html")


@app.route("/api/state")
def state():
    bots = [_bot_data(t) for t in _traders]
    bots.sort(key=lambda b: b["pnl"], reverse=True)
    uptime = int(time.time() - _start_time)
    h, m, s = uptime // 3600, (uptime % 3600) // 60, uptime % 60
    market_count = 0
    if _traders:
        try:
            market_count = len(_traders[0].strategy.client.get_markets())
        except Exception:
            pass
    return jsonify({
        "initial_balance": _initial_balance,
        "initial_live_balance": _initial_live_balance,
        "uptime":          f"{h:02d}:{m:02d}:{s:02d}",
        "market_count":    market_count,
        "bots":            bots,
    })


@app.route("/api/history")
def history():
    with _history_lock:
        return jsonify(dict(_pnl_history))


@app.route("/api/restart", methods=["POST"])
def restart():
    data = request.get_json(silent=True) or {}
    new_balance = float(data.get("balance", _initial_balance))
    new_live_balance = float(data.get("live_balance", _initial_live_balance))
    if _restart_callback:
        _restart_callback(new_balance, new_live_balance, clear=False)
        return jsonify({"ok": True, "balance": new_balance, "live_balance": new_live_balance})
    return jsonify({"ok": False, "error": "no callback"}), 500


@app.route("/api/reset-paper", methods=["POST"])
def reset_paper():
    """Resetea solo los bots paper."""
    if _restart_callback:
        _restart_callback(_initial_balance, _initial_live_balance, clear=True)
        with _history_lock:
            for key in list(_pnl_history.keys()):
                if "(PAPER)" in key:
                    _pnl_history[key] = []
        return jsonify({"ok": True, "message": "Paper traders reset"})
    return jsonify({"ok": False, "error": "no callback"}), 500


@app.route("/api/reset", methods=["POST"])
def reset():
    """Borra todos los datos y reinicia desde cero."""
    data = request.get_json(silent=True) or {}
    new_balance = float(data.get("balance", _initial_balance))
    new_live_balance = float(data.get("live_balance", _initial_live_balance))
    if _restart_callback:
        _restart_callback(new_balance, new_live_balance, clear=True)
        with _history_lock:
            _pnl_history.clear()
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "no callback"}), 500


def run_flask(host="0.0.0.0", port=5000):
    import logging
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    app.run(host=host, port=port, debug=False, threaded=True, use_reloader=False)
