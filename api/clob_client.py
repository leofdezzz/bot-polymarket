import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

CLOB_HOST = "https://clob.polymarket.com"
RELAYER_HOST = "https://relayer-v2.polymarket.com"
CHAIN_ID = 137

try:
    from py_clob_client_v2.client import ClobClient
    from py_clob_client_v2.clob_types import MarketOrderArgs, OrderType
    from py_clob_client_v2.order_builder.constants import BUY, SELL
    from py_builder_relayer_client.client import RelayClient
    HAS_RELAYER_SDK = True
except ImportError:
    HAS_RELAYER_SDK = False
    try:
        from py_clob_client_v2.client import ClobClient
        from py_clob_client_v2.clob_types import MarketOrderArgs, OrderType
        from py_clob_client_v2.order_builder.constants import BUY, SELL
        HAS_CLOB_SDK = True
    except ImportError:
        HAS_CLOB_SDK = False
        logger.warning("No Polymarket SDK installed. Run: pip install py-clob-client-v2 py-builder-relayer-client")


class CLOBClient:
    def __init__(self, private_key: str, api_creds: Optional[dict] = None,
                 relayer_api_key: str = "", relayer_secret: str = "", relayer_passphrase: str = ""):
        self._key = private_key
        self._creds = api_creds
        self._client = None
        self._relayer = None
        self._signature_type = 0
        self._relayer_api_key = relayer_api_key
        self._relayer_secret = relayer_secret
        self._relayer_passphrase = relayer_passphrase
        self._using_relayer = bool(relayer_api_key and relayer_secret and relayer_passphrase)

        if not self._using_relayer and not HAS_RELAYER_SDK:
            if not HAS_CLOB_SDK:
                raise RuntimeError("No SDK available. Install: pip install py-clob-client-v2")

    def _get_relayer_client(self):
        if self._relayer is None:
            if not self._using_relayer:
                raise RuntimeError("Relayer credentials not configured")
            self._relayer = RelayClient(
                host=RELAYER_HOST,
                chain=CHAIN_ID,
                signer=self._key,
                relayer_api_key=self._relayer_api_key,
                relayer_api_key_address=self._get_address(),
            )
            logger.info("Relayer client initialized")
        return self._relayer

    def _get_clob_client(self):
        if self._client is None:
            creds = self._creds
            if creds is None:
                from py_clob_client_v2.client import ClobClient
                temp_client = ClobClient(host=CLOB_HOST, chain_id=CHAIN_ID, key=self._key)
                try:
                    creds = temp_client.derive_api_key()
                except Exception:
                    try:
                        creds = temp_client.create_api_key()
                    except Exception:
                        creds = None
            self._client = ClobClient(
                host=CLOB_HOST,
                chain_id=CHAIN_ID,
                key=self._key,
                creds=creds,
                signature_type=self._signature_type,
            )
            logger.info("CLOB client initialized")
        return self._client

    def _get_address(self) -> str:
        try:
            from eth_account import Account
            account = Account.from_key(self._key)
            return account.address
        except Exception:
            return ""

    def get_balance(self) -> float:
        try:
            if self._using_relayer:
                client = self._get_relayer_client()
                try:
                    result = client.get_balance()
                    if isinstance(result, dict):
                        return float(result.get("balance", 0))
                    return float(result) if result else 0.0
                except Exception:
                    pass
                try:
                    result = client._get(f"{RELAYER_HOST}/balance")
                    if isinstance(result, dict):
                        return float(result.get("balance", 0))
                except Exception:
                    pass
                return 0.0
            else:
                client = self._get_clob_client()
                try:
                    from py_clob_client_v2.clob_types import BalanceAllowanceParams, AssetType
                    params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=0)
                    result = client.get_balance_allowance(params=params)
                    if isinstance(result, dict):
                        return float(result.get("balance", 0))
                except Exception:
                    pass
                return 0.0
        except Exception as e:
            logger.error(f"Error getting balance: {e}")
            return 0.0

    def place_market_buy(self, token_id: str, amount_usdc: float, tick_size: str = "0.01", neg_risk: bool = False) -> Optional[str]:
        return self._place_market_order(token_id, amount_usdc, BUY, tick_size, neg_risk)

    def place_market_sell(self, token_id: str, amount_usdc: float, tick_size: str = "0.01", neg_risk: bool = False) -> Optional[str]:
        return self._place_market_order(token_id, amount_usdc, SELL, tick_size, neg_risk)

    def _place_market_order(self, token_id: str, amount_usdc: float, side, tick_size: str, neg_risk: bool) -> Optional[str]:
        try:
            if self._using_relayer:
                client = self._get_relayer_client()
                response = client.create_market_order(
                    token_id=token_id,
                    amount=amount_usdc,
                    side=side,
                )
            else:
                client = self._get_clob_client()
                from py_clob_client_v2.clob_types import MarketOrderArgsV2
                from py_clob_client_v2.order_builder.constants import Side as CLobSide
                clob_side = CLobSide.BUY if side == BUY else CLobSide.SELL
                response = client.create_and_post_market_order(
                    order_args=MarketOrderArgsV2(
                        token_id=token_id,
                        amount=amount_usdc,
                        side=clob_side,
                    ),
                    options={"tick_size": tick_size, "neg_risk": neg_risk},
                    order_type=OrderType.FOK,
                )
            logger.info(f"Market order response: {response}")
            if isinstance(response, dict):
                for key in ["orderID", "filledOrderID", "id", "OrderID"]:
                    if key in response and response[key]:
                        return str(response[key])
                if "error" in response:
                    logger.error(f"Order error: {response['error']}")
            elif isinstance(response, str) and len(response) > 5:
                return response
            logger.warning(f"Could not extract order_id from: {response}")
            return None
        except Exception as e:
            logger.error(f"Error placing market order: {e}")
            return None

    def cancel_order(self, order_id: str) -> bool:
        try:
            if self._using_relayer:
                client = self._get_relayer_client()
                result = client.cancel_order(order_id)
            else:
                client = self._get_clob_client()
                result = client.cancel_order(order_id)
            logger.info(f"Cancel order {order_id}: {result}")
            return True
        except Exception as e:
            logger.error(f"Error canceling order {order_id}: {e}")
            return False

    def get_open_orders(self) -> list:
        try:
            if self._using_relayer:
                return []
            client = self._get_clob_client()
            return client.get_orders() or []
        except Exception as e:
            logger.error(f"Error getting open orders: {e}")
            return []

    def get_filled_orders(self, token_id: Optional[str] = None) -> list:
        try:
            if self._using_relayer:
                return []
            client = self._get_clob_client()
            return client.get_trades(token_id=token_id) or []
        except Exception as e:
            logger.error(f"Error getting trades: {e}")
            return []
