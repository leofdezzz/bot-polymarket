import argparse

DEFAULT_BALANCE = 50.0
DEFAULT_LIVE_BALANCE = 10.0
TRADE_SIZE_PCT = 0.05
MAX_POSITION_SIZE_PCT = 0.15
MAX_POSITIONS = 10
UPDATE_INTERVAL = 10
DASHBOARD_REFRESH = 3
MIN_VOLUME = 500
MIN_LIQUIDITY = 200
STOP_LOSS_PCT = 0.40
TAKE_PROFIT_PCT = 0.80

GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"
CLOB_HOST = "https://clob.polymarket.com"
CHAIN_ID = 137


def parse_args():
    parser = argparse.ArgumentParser(description="Polymarket Trading Bot")
    parser.add_argument(
        "--balance",
        type=float,
        default=DEFAULT_BALANCE,
        help=f"Initial paper balance in USDC (default: {DEFAULT_BALANCE})",
    )
    parser.add_argument(
        "--live-balance",
        type=float,
        default=DEFAULT_LIVE_BALANCE,
        help=f"Initial live balance in USDC for real trading (default: {DEFAULT_LIVE_BALANCE})",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=UPDATE_INTERVAL,
        help=f"Seconds between strategy updates (default: {UPDATE_INTERVAL})",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Enable live trading mode with real money",
    )
    parser.add_argument(
        "--private-key",
        type=str,
        default="",
        help="Polygon private key for live trading (with 0x prefix)",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Clear saved state and start fresh",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5000,
        help="Web dashboard port (default: 5000)",
    )
    args = parser.parse_args()

    if args.live and not args.private_key:
        parser.error("--private-key is required when --live is enabled")

    return args
