import time
from datetime import datetime

from rich import box
from rich.columns import Columns
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from engine.paper_trader import PaperTrader
from engine.portfolio import Portfolio, Position


console = Console()


def _color_pnl(value: float, pct: bool = False) -> Text:
    fmt = f"{value:+.1f}%" if pct else f"${value:+.2f}"
    color = "green" if value > 0 else ("red" if value < 0 else "white")
    return Text(fmt, style=color)


def _truncate(text: str, max_len: int = 40) -> str:
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


def _make_leaderboard(traders: list[PaperTrader]) -> Panel:
    ranked = sorted(traders, key=lambda t: t.portfolio.total_pnl(), reverse=True)

    table = Table(
        box=box.SIMPLE_HEAVY,
        show_header=True,
        header_style="bold cyan",
        expand=True,
        pad_edge=False,
    )
    table.add_column("#", style="dim", width=3, justify="center")
    table.add_column("Bot", min_width=18)
    table.add_column("Estrategia", min_width=26)
    table.add_column("Balance", justify="right", min_width=10)
    table.add_column("P&L $", justify="right", min_width=10)
    table.add_column("P&L %", justify="right", min_width=8)
    table.add_column("Trades", justify="center", width=7)
    table.add_column("Win %", justify="right", width=7)
    table.add_column("Pos.", justify="center", width=5)
    table.add_column("Estado", width=12)

    medal = [" 1 ", " 2 ", " 3 ", " 4 ", " 5 "]

    for i, trader in enumerate(ranked):
        pf = trader.portfolio
        pnl = pf.total_pnl()
        pnl_pct = pf.total_pnl_pct()
        rank_str = medal[i] if i < 3 else medal[i]
        color = "green" if pnl > 0 else ("red" if pnl < 0 else "white")

        table.add_row(
            rank_str,
            Text(trader.name, style="bold " + color),
            Text(trader.strategy.description, style="dim"),
            f"${pf.total_value():,.2f}",
            _color_pnl(pnl),
            _color_pnl(pnl_pct, pct=True),
            str(pf.trades_count),
            f"{pf.win_rate():.0f}%",
            str(len(pf.open_positions())),
            Text(trader.status, style="dim"),
        )

    return Panel(table, title="[bold yellow]LEADERBOARD[/bold yellow]", border_style="yellow")


def _make_bot_panel(trader: PaperTrader) -> Panel:
    pf = trader.portfolio
    positions = pf.open_positions()
    pnl = pf.total_pnl()
    color = "green" if pnl > 0 else "red"

    table = Table(box=box.MINIMAL, show_header=True, header_style="bold", expand=True)
    table.add_column("Mercado", min_width=24)
    table.add_column("Dir", width=4, justify="center")
    table.add_column("Entrada", width=7, justify="right")
    table.add_column("Actual", width=7, justify="right")
    table.add_column("P&L", width=8, justify="right")
    table.add_column("h", width=5, justify="right")

    for pos in sorted(positions, key=lambda p: p.unrealized_pnl, reverse=True)[:6]:
        dir_color = "green" if pos.outcome == "YES" else "red"
        table.add_row(
            _truncate(pos.question, 24),
            Text(pos.outcome[:3], style=dir_color),
            f"{pos.entry_price:.3f}",
            f"{pos.current_price:.3f}",
            _color_pnl(pos.unrealized_pnl),
            f"{pos.age_hours:.1f}",
        )

    if not positions:
        table.add_row("[dim]Sin posiciones abiertas[/dim]", "", "", "", "", "")

    title = (
        f"[bold]{trader.name}[/bold] "
        f"[dim]{trader.strategy.description}[/dim] | "
        f"Cash: ${pf.cash:,.0f} | "
    )
    title += str(_color_pnl(pnl))

    return Panel(table, title=title, border_style=color, padding=(0, 1))


def _make_header(initial_balance: float, num_markets: int) -> Panel:
    now = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
    content = (
        f"[bold cyan]POLYMARKET PAPER TRADING SIMULATOR[/bold cyan]   "
        f"[dim]Saldo inicial: [/dim][bold]${initial_balance:,.2f}[/bold]   "
        f"[dim]Mercados activos: [/dim][bold]{num_markets}[/bold]   "
        f"[dim]{now}[/dim]"
    )
    return Panel(Text.from_markup(content), border_style="blue", padding=(0, 2))


def run_dashboard(
    traders: list[PaperTrader],
    initial_balance: float,
    client,
    refresh_interval: int = 3,
):
    """Main blocking dashboard loop."""
    with Live(console=console, refresh_per_second=1, screen=True) as live:
        while True:
            num_markets = len(client.get_markets())

            layout = Layout()
            layout.split_column(
                Layout(name="header", size=3),
                Layout(name="leaderboard", size=14),
                Layout(name="bots"),
            )

            layout["header"].update(_make_header(initial_balance, num_markets))
            layout["leaderboard"].update(_make_leaderboard(traders))

            bot_panels = [_make_bot_panel(t) for t in traders]
            layout["bots"].update(Columns(bot_panels, equal=True, expand=True))

            live.update(layout)
            time.sleep(refresh_interval)
