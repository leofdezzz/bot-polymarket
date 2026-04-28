import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

CLOB_HOST = "https://clob.polymarket.com"
CHAIN_ID = 137

try:
    from py_clob_client_v2.client import ClobClient
    from py_clob_client_v2.clob_types import MarketOrderArgs, OrderType
    from py_clob_client_v2.order_builder.constants import BUY, SELL
    HAS_CLOB_SDK = True
    ORDER_TYPE_FOK = OrderType.FOK
    ORDER_TYPE_FAK = OrderType.FAK
except ImportError:
    HAS_CLOB_SDK = False
    logger.warning("py-clob-client-v2 not installed, live trading disabled")


class CLOBClient:
    def __init__(self, private_key: str, api_creds: Optional[dict] = None):
        if not HAS_CLOB_SDK:
            raise RuntimeError("py-clob-client-v2 not installed. Run: pip install py-clob-client-v2")

        self._key = private_key
        self._creds = api_creds
        self._client: Optional[ClobClient] = None
        self._signature_type = 0

    def _get_client(self) -> ClobClient:
        if self._client is None:
            creds = self._creds
            if creds is None:
                temp_client = ClobClient(host=CLOB_HOST, chain=CHAIN_ID, key=self._key)
                creds = temp_client.create_or_derive_api_creds()

            self._client = ClobClient(
                host=CLOB_HOST,
                key=self._key,
                chain=CHAIN_ID,
                creds=creds,
                signature_type=self._signature_type,
            )
            logger.info("CLOB client initialized")
        return self._client

    def get_balance(self) -> float:
        try:
            client = self._get_client()
            balance = client.get_balance()
            return float(balance) if balance else 0.0
        except Exception as e:
            logger.error(f"Error getting balance: {e}")
            return 0.0

    def place_market_buy(self, token_id: str, amount_usdc: float, tick_size: str = "0.01", neg_risk: bool = False) -> Optional[str]:
        return self._place_market_order(token_id, amount_usdc, BUY, tick_size, neg_risk)

    def place_market_sell(self, token_id: str, amount_usdc: float, tick_size: str = "0.01", neg_risk: bool = False) -> Optional[str]:
        return self._place_market_order(token_id, amount_usdc, SELL, tick_size, neg_risk)

    def _place_market_order(self, token_id: str, amount_usdc: float, side, tick_size: str, neg_risk: bool) -> Optional[str]:
        try:
            client = self._get_client()
            response = client.create_and_post_market_order(
                order_args=MarketOrderArgs(
                    token_id=token_id,
                    amount=amount_usdc,
                    side=side,
                ),
                options={"tick_size": tick_size, "neg_risk": neg_risk},
                order_type=ORDER_TYPE_FAK,
            )
            logger.info(f"Market order raw response: {response}")

            for key in ["orderID", "filledOrderID", "id", "OrderID", "FilledOrderID"]:
                if isinstance(response, dict) and key in response:
                    oid = response[key]
                    if oid:
                        logger.info(f"Market order key={key}: {oid}")
                        return str(oid)

            if isinstance(response, dict):
                for k, v in response.items():
                    if v and isinstance(v, str) and len(v) > 5:
                        logger.info(f"Using key={k}: {v}")
                        return v

            if isinstance(response, str) and len(response) > 5:
                return response

            logger.warning(f"Could not extract order_id from response: {response}")
            return None
        except Exception as e:
            logger.error(f"Error placing market order: {e}")
            return None

    def cancel_order(self, order_id: str) -> bool:
        try:
            client = self._get_client()
            result = client.cancel_order(order_id)
            logger.info(f"Cancel order {order_id}: {result}")
            return True
        except Exception as e:
            logger.error(f"Error canceling order {order_id}: {e}")
            return False

    def get_open_orders(self) -> list:
        try:
            client = self._get_client()
            return client.get_orders() or []
        except Exception as e:
            logger.error(f"Error getting open orders: {e}")
            return []

    def get_filled_orders(self, token_id: Optional[str] = None) -> list:
        try:
            client = self._get_client()
            trades = client.get_trades(token_id=token_id) or []
            return trades
        except Exception as e:
            logger.error(f"Error getting trades: {e}")
            return []

    def get_token_balance(self, token_id: str) -> float:
        try:
            client = self._get_client()
            pos = client.get_positions(token_id=token_id)
            if pos:
                return float(pos.get("balance", 0))
            return 0.0
        except Exception as e:
            logger.error(f"Error getting token balance for {token_id}: {e}")
            return 0.0
