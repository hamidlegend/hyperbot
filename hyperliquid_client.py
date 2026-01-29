"""
Hyperliquid API Client
Handles all communication with Hyperliquid exchange
"""

import json
import time
import requests
import hashlib
from eth_account import Account
from eth_account.messages import encode_defunct
from eth_abi import encode
from eth_utils import keccak
import config


class HyperliquidClient:
    """Client for interacting with Hyperliquid API"""

    def __init__(self, private_key: str = None, account_address: str = None):
        """
        Initialize the client

        Args:
            private_key: Your wallet private key (for trading)
            account_address: Your wallet address
        """
        self.base_url = config.TESTNET_API_URL if config.USE_TESTNET else config.API_URL
        self.private_key = private_key
        self.account_address = account_address
        self.wallet = None

        if private_key:
            # Remove 0x prefix if present
            if private_key.startswith('0x'):
                private_key = private_key[2:]
            self.wallet = Account.from_key(private_key)
            if not account_address:
                self.account_address = self.wallet.address

    # =========================================================================
    # INFO API (Read-only)
    # =========================================================================

    def get_meta(self):
        """Get exchange metadata including all tradeable assets"""
        return self._info_request({"type": "meta"})

    def get_all_mids(self):
        """Get mid prices for all assets"""
        return self._info_request({"type": "allMids"})

    def get_user_state(self, address: str = None):
        """Get user account state"""
        addr = address or self.account_address
        return self._info_request({"type": "clearinghouseState", "user": addr})

    def get_open_orders(self, address: str = None):
        """Get user's open orders"""
        addr = address or self.account_address
        return self._info_request({"type": "openOrders", "user": addr})

    def get_user_fills(self, address: str = None):
        """Get user's recent fills"""
        addr = address or self.account_address
        return self._info_request({"type": "userFills", "user": addr})

    def get_candles(self, symbol: str, interval: str, start_time: int = None, end_time: int = None):
        """
        Get candlestick data

        Args:
            symbol: Trading pair (e.g., "HYPE")
            interval: Candle interval ("1m", "5m", "15m", "1h", "4h", "1d")
            start_time: Start timestamp in milliseconds
            end_time: End timestamp in milliseconds

        Returns:
            List of candles [timestamp, open, high, low, close, volume]
        """
        req = {
            "type": "candleSnapshot",
            "req": {
                "coin": symbol,
                "interval": interval,
                "startTime": start_time or int((time.time() - 86400) * 1000),  # Default: last 24h
                "endTime": end_time or int(time.time() * 1000)
            }
        }
        return self._info_request(req)

    def get_l2_book(self, symbol: str):
        """Get L2 order book for a symbol"""
        return self._info_request({"type": "l2Book", "coin": symbol})

    # =========================================================================
    # EXCHANGE API (Trading)
    # =========================================================================

    def place_order(
        self,
        symbol: str,
        is_buy: bool,
        size: float,
        price: float = None,
        order_type: str = "limit",
        reduce_only: bool = False,
        time_in_force: str = "Gtc",
        slippage: float = 0.01
    ):
        """
        Place an order

        Args:
            symbol: Trading pair
            is_buy: True for buy, False for sell
            size: Order size
            price: Limit price (None for market order)
            order_type: "limit" or "market"
            reduce_only: True to only reduce position
            time_in_force: "Gtc", "Ioc", "Alo"
            slippage: Slippage for market orders

        Returns:
            Order response
        """
        # Get asset index
        meta = self.get_meta()
        asset_index = self._get_asset_index(meta, symbol)

        # For market orders, use aggressive limit price
        if order_type == "market" or price is None:
            mids = self.get_all_mids()
            mid_price = float(mids[symbol])
            price = mid_price * (1 + slippage) if is_buy else mid_price * (1 - slippage)

        # Round price to valid tick size
        price = self._round_price(price, symbol, meta)
        size = self._round_size(size, symbol, meta)

        order = {
            "a": asset_index,
            "b": is_buy,
            "p": str(price),
            "s": str(size),
            "r": reduce_only,
            "t": {"limit": {"tif": time_in_force}}
        }

        action = {
            "type": "order",
            "orders": [order],
            "grouping": "na"
        }

        return self._exchange_request(action)

    def place_market_order(self, symbol: str, is_buy: bool, size: float, reduce_only: bool = False):
        """Place a market order"""
        return self.place_order(
            symbol=symbol,
            is_buy=is_buy,
            size=size,
            order_type="market",
            reduce_only=reduce_only,
            time_in_force="Ioc"
        )

    def place_limit_order(self, symbol: str, is_buy: bool, size: float, price: float, reduce_only: bool = False):
        """Place a limit order"""
        return self.place_order(
            symbol=symbol,
            is_buy=is_buy,
            size=size,
            price=price,
            order_type="limit",
            reduce_only=reduce_only
        )

    def cancel_order(self, symbol: str, order_id: int):
        """Cancel an order"""
        meta = self.get_meta()
        asset_index = self._get_asset_index(meta, symbol)

        action = {
            "type": "cancel",
            "cancels": [{"a": asset_index, "o": order_id}]
        }

        return self._exchange_request(action)

    def cancel_all_orders(self, symbol: str = None):
        """Cancel all open orders"""
        open_orders = self.get_open_orders()

        if not open_orders:
            return {"status": "ok", "message": "No open orders"}

        meta = self.get_meta()
        cancels = []

        for order in open_orders:
            if symbol is None or order["coin"] == symbol:
                asset_index = self._get_asset_index(meta, order["coin"])
                cancels.append({"a": asset_index, "o": order["oid"]})

        if not cancels:
            return {"status": "ok", "message": "No orders to cancel"}

        action = {
            "type": "cancel",
            "cancels": cancels
        }

        return self._exchange_request(action)

    def set_leverage(self, symbol: str, leverage: int, is_cross: bool = True):
        """
        Set leverage for a symbol

        Args:
            symbol: Trading pair
            leverage: Leverage value
            is_cross: True for cross margin, False for isolated
        """
        meta = self.get_meta()
        asset_index = self._get_asset_index(meta, symbol)

        action = {
            "type": "updateLeverage",
            "asset": asset_index,
            "isCross": is_cross,
            "leverage": leverage
        }

        return self._exchange_request(action)

    def close_position(self, symbol: str):
        """Close entire position for a symbol"""
        user_state = self.get_user_state()

        for position in user_state.get("assetPositions", []):
            if position["position"]["coin"] == symbol:
                size = abs(float(position["position"]["szi"]))
                is_long = float(position["position"]["szi"]) > 0

                if size > 0:
                    return self.place_market_order(
                        symbol=symbol,
                        is_buy=not is_long,  # Opposite direction to close
                        size=size,
                        reduce_only=True
                    )

        return {"status": "ok", "message": "No position to close"}

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def _info_request(self, payload: dict):
        """Make a request to the info API"""
        url = f"{self.base_url}/info"
        response = requests.post(url, json=payload)
        response.raise_for_status()
        return response.json()

    def _exchange_request(self, action: dict):
        """Make a signed request to the exchange API"""
        if not self.wallet:
            raise ValueError("Private key required for exchange requests")

        timestamp = int(time.time() * 1000)

        # Create the signature using Hyperliquid's L1 signing method
        signature = self._sign_l1_action(action, timestamp)

        payload = {
            "action": action,
            "nonce": timestamp,
            "signature": signature,
            "vaultAddress": None
        }

        url = f"{self.base_url}/exchange"
        response = requests.post(url, json=payload)
        response.raise_for_status()
        return response.json()

    def _sign_l1_action(self, action: dict, timestamp: int):
        """
        Sign an action using Hyperliquid's L1 signing method
        Uses EIP-712 typed data signing with phantom agent
        """
        # Hyperliquid uses a specific source identifier
        is_mainnet = not config.USE_TESTNET

        # Create the connection ID (hash of action + nonce + vault)
        connection_id = self._construct_phantom_agent(action, timestamp, None, is_mainnet)

        # Sign the phantom agent hash
        signature = self.wallet.sign_message(encode_defunct(primitive=connection_id))

        return {
            "r": hex(signature.r),
            "s": hex(signature.s),
            "v": signature.v
        }

    def _construct_phantom_agent(self, action: dict, nonce: int, vault_address, is_mainnet: bool):
        """
        Construct the phantom agent hash for signing
        This follows Hyperliquid's exact signing specification
        """
        # Hash the action
        action_str = json.dumps(action, separators=(',', ':'), sort_keys=True)
        action_hash = hashlib.sha256(action_str.encode()).digest()

        # Encode the agent data
        # source = "a" for mainnet, "b" for testnet
        source = b'a' if is_mainnet else b'b'

        # Construct the hash: keccak256(source || actionHash || nonce || vaultAddress)
        if vault_address is None:
            vault_bytes = b'\x00' * 20
        else:
            vault_bytes = bytes.fromhex(vault_address[2:] if vault_address.startswith('0x') else vault_address)

        # Encode nonce as uint64
        nonce_bytes = nonce.to_bytes(8, byteorder='big')

        # Combine all parts
        data = source + action_hash + nonce_bytes + vault_bytes

        # Return keccak256 hash
        return keccak(data)

    def _get_asset_index(self, meta: dict, symbol: str) -> int:
        """Get asset index from metadata"""
        for i, asset in enumerate(meta["universe"]):
            if asset["name"] == symbol:
                return i
        raise ValueError(f"Symbol {symbol} not found")

    def _round_price(self, price: float, symbol: str, meta: dict) -> float:
        """Round price to valid tick size"""
        for asset in meta["universe"]:
            if asset["name"] == symbol:
                # Use 5 significant figures by default
                return round(price, 5)
        return round(price, 5)

    def _round_size(self, size: float, symbol: str, meta: dict) -> float:
        """Round size to valid step size"""
        for asset in meta["universe"]:
            if asset["name"] == symbol:
                sz_decimals = asset.get("szDecimals", 3)
                return round(size, sz_decimals)
        return round(size, 3)

    def get_position(self, symbol: str):
        """Get current position for a symbol"""
        user_state = self.get_user_state()

        for position in user_state.get("assetPositions", []):
            if position["position"]["coin"] == symbol:
                return {
                    "symbol": symbol,
                    "size": float(position["position"]["szi"]),
                    "entry_price": float(position["position"]["entryPx"]),
                    "unrealized_pnl": float(position["position"]["unrealizedPnl"]),
                    "liquidation_price": position["position"].get("liquidationPx")
                }

        return None

    def get_balance(self):
        """Get account balance"""
        user_state = self.get_user_state()
        return {
            "account_value": float(user_state.get("marginSummary", {}).get("accountValue", 0)),
            "total_margin_used": float(user_state.get("marginSummary", {}).get("totalMarginUsed", 0)),
            "withdrawable": float(user_state.get("withdrawable", 0))
        }
