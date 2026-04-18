import argparse

DEFAULT_BALANCE = 1000.0
TRADE_SIZE_PCT = 0.05          # 5% of portfolio per trade
MAX_POSITION_SIZE_PCT = 0.15   # Max 15% in one market
MAX_POSITIONS = 10             # Max open positions per bot
UPDATE_INTERVAL = 30           # Seconds between strategy runs
DASHBOARD_REFRESH = 3          # Seconds between dashboard updates
MIN_VOLUME = 500               # Minimum market volume (USDC)
MIN_LIQUIDITY = 200            # Minimum liquidity
STOP_LOSS_PCT = 0.40           # Exit if position drops 40%
TAKE_PROFIT_PCT = 0.80         # Exit if position gains 80%

GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"


def parse_args():
    parser = argparse.ArgumentParser(description="Polymarket Paper Trading Simulator")
    parser.add_argument(
        "--balance",
        type=float,
        default=DEFAULT_BALANCE,
        help=f"Initial balance in USDC for each bot (default: {DEFAULT_BALANCE})",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=UPDATE_INTERVAL,
        help=f"Seconds between strategy updates (default: {UPDATE_INTERVAL})",
    )
    return parser.parse_args()
