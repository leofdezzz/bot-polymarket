import logging
from typing import Optional

logger = logging.getLogger(__name__)

CLOB_HOST = "https://clob.polymarket.com"
CHAIN_ID = 137

try:
    from py_clob_client_v2.client import ClobClient
    from py_clob_client_v2.clob_types import MarketOrderArgsV2, OrderType
    from py_clob_client_v2.order_builder.constants import BUY, SELL
    HAS_SDK = True
except ImportError:
    HAS_SDK = False
    logger.warning("py-clob-client-v2 not installed. Run: pip install py-clob-client-v2")


class CLOBClient:
    def __init__(self, private_key: str):
        if not HAS_SDK:
            raise RuntimeError("py-clob-client-v2 not installed. Run: pip install py-clob-client-v2")

        self._key = private_key
        self._client: Optional[ClobClient] = None
        self._address: Optional[str] = None

    def _get_address(self) -> str:
        if self._address is None:
            try:
                from eth_account import Account
                self._address = Account.from_key(self._key).address
            except Exception:
                self._address = ""
        return self._address

    def _get_client(self) -> ClobClient:
        if self._client is None:
            from py_clob_client_v2 import ApiCreds

            temp_client = ClobClient(
                host=CLOB_HOST,
                chain_id=CHAIN_ID,
                key=self._key,
                signature_type=0,
            )
            try:
                creds = temp_client.create_or_derive_api_key()
                logger.info(f"CLOB API credentials created for address: {self._get_address()[:10]}...")
            except Exception as e:
                logger.warning(f"Could not create API credentials: {e}. Using L1 auth only.")
                creds = None

            self._client = ClobClient(
                host=CLOB_HOST,
                chain_id=CHAIN_ID,
                key=self._key,
                creds=creds,
                signature_type=0,
            )
            logger.info(f"CLOB client initialized for address: {self._get_address()[:10]}...")
        return self._client

    def get_balance(self) -> float:
        try:
            rpc_urls = [
                "https://polygon-rpc.com",
                "https://rpc-mainnet.matic.network",
                "https://rpc.ankr.com/polygon",
                "https://polygon-mainnet.public.blastapi.io",
            ]
            for rpc_url in rpc_urls:
                try:
                    from web3 import Web3
                    w3 = Web3(Web3.HTTPProvider(rpc_url))
                    if w3.is_connected():
                        USDC_CONTRACT = "0xC011a73ee8576Fb46F5E1c575732cBCbc3CDE225"
                        erc20_abi = '[{"inputs":[{"name":"account"},{"outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},{"name":"decimals","outputs":[{"type":"uint8"}],"stateMutability":"view","type":"function"}]}'
                        contract = w3.eth.contract(
                            address=Web3.to_checksum_address(USDC_CONTRACT),
                            abi=erc20_abi
                        )
                        addr = Web3.to_checksum_address(self._get_address())
                        raw_balance = contract.functions.balanceOf(addr).call()
                        decimals = contract.functions.decimals().call()
                        balance = raw_balance / (10 ** decimals)
                        logger.info(f"Web3 connected via {rpc_url[:30]}..., USDC balance: {balance}")
                        return balance
                except Exception as e:
                    logger.debug(f"RPC {rpc_url[:30]} failed: {e}")
                    continue

            logger.warning("All Web3 RPC attempts failed")
            return 0.0

        except Exception as e:
            logger.error(f"Error getting balance: {e}")
            return 0.0

    def place_market_buy(self, token_id: str, amount_usdc: float) -> Optional[str]:
        return self._place_market_order(token_id, amount_usdc, BUY)

    def place_market_sell(self, token_id: str, amount_usdc: float) -> Optional[str]:
        return self._place_market_order(token_id, amount_usdc, SELL)

    def _place_market_order(self, token_id: str, amount_usdc: float, side) -> Optional[str]:
        try:
            client = self._get_client()
            side_str = "BUY" if side == BUY else "SELL"

            response = client.create_and_post_market_order(
                order_args=MarketOrderArgsV2(
                    token_id=token_id,
                    amount=amount_usdc,
                    side=side_str,
                ),
                order_type=OrderType.FOK,
            )

            logger.info(f"Market order response: {response}")

            if isinstance(response, dict):
                for key in ["orderID", "filledOrderID", "id"]:
                    if key in response and response[key]:
                        return str(response[key])
                if "error" in response:
                    logger.error(f"Order error: {response['error']}")
                    return None
            elif isinstance(response, str) and len(response) > 5:
                return response

            logger.warning(f"Could not extract order_id from: {response}")
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
