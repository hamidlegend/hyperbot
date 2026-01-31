"""
Hyperliquid API Client
Handles all communication with Hyperliquid exchange

Signing implementation based on official SDK:
https://github.com/hyperliquid-dex/hyperliquid-python-sdk
"""

import json
import time
import requests
import msgpack
from decimal import Decimal
from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_utils import keccak, to_hex
import config


def float_to_wire(x: float) -> str:
    """
    Convert float to wire format (matching official SDK).
    Normalizes decimal and removes trailing zeros.
    """
    rounded = f"{x:.8f}"
    if rounded == "-0.00000000":
        return "0"
    # Normalize to remove trailing zeros
    normalized = Decimal(rounded).normalize()
    return f"{normalized:f}"


def address_to_bytes(address: str) -> bytes:
    """Convert hex address to bytes"""
    if address.startswith('0x'):
        address = address[2:]
    return bytes.fromhex(address)


def action_hash(action, vault_address, nonce):
    """
    Create action hash using msgpack (matching official SDK)
    """
    # Pack action with msgpack
    data = msgpack.packb(action)

    # Append nonce as 8 bytes big endian
    data += nonce.to_bytes(8, "big")

    # Append vault address flag and address
    if vault_address is None:
        data += b"\x00"
    else:
        data += b"\x01"
        data += address_to_bytes(vault_address)

    return keccak(data)


def construct_phantom_agent(connection_id: bytes, is_mainnet: bool) -> dict:
    """Construct phantom agent for signing"""
    return {
        "source": "a" if is_mainnet else "b",
        "connectionId": connection_id
    }


def sign_l1_action(wallet, action, vault_address, nonce, is_mainnet):
    """
    Sign an L1 action using EIP-712 typed data signing
    This matches the official Hyperliquid SDK implementation
    """
    # Create action hash
    hash_bytes = action_hash(action, vault_address, nonce)

    # Construct phantom agent
    phantom_agent = construct_phantom_agent(hash_bytes, is_mainnet)

    # Create EIP-712 payload
    data = {
        "domain": {
            "chainId": 1337,
            "name": "Exchange",
            "verifyingContract": "0x0000000000000000000000000000000000000000",
            "version": "1",
        },
        "types": {
            "Agent": [
                {"name": "source", "type": "string"},
                {"name": "connectionId", "type": "bytes32"},
            ],
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
        },
        "primaryType": "Agent",
        "message": phantom_agent,
    }

    # Sign the typed data
    structured_data = encode_typed_data(full_message=data)
    signed = wallet.sign_message(structured_data)

    return {
        "r": to_hex(signed.r),
        "s": to_hex(signed.s),
        "v": signed.v
    }


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

        # Cache for metadata (reduces API calls)
        self._meta_cache = None
        self._meta_cache_time = 0

        if private_key:
            self.wallet = Account.from_key(private_key)
            if not account_address:
                self.account_address = self.wallet.address

    # =========================================================================
    # INFO API (Read-only)
    # =========================================================================

    def get_meta(self, use_cache: bool = True):
        """
        Get exchange metadata including all tradeable assets.
        Cached for 5 minutes to reduce API calls.
        """
        cache_duration = 300  # 5 minutes
        now = time.time()

        if use_cache and self._meta_cache and (now - self._meta_cache_time) < cache_duration:
            return self._meta_cache

        self._meta_cache = self._info_request({"type": "meta"})
        self._meta_cache_time = now
        return self._meta_cache

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
        slippage: float = 0.05  # 5% default, matching official SDK
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
            "p": float_to_wire(price),
            "s": float_to_wire(size),
            "r": reduce_only,
            "t": {"limit": {"tif": time_in_force}}
        }

        action = {
            "type": "order",
            "orders": [order],
            "grouping": "na"
        }

        return self._exchange_request(action)

    def place_market_order(self, symbol: str, is_buy: bool, size: float,
                           reduce_only: bool = False, current_price: float = None):
        """
        Place a market order.

        Args:
            symbol: Trading pair
            is_buy: True for buy, False for sell
            size: Order size
            reduce_only: True to only reduce position
            current_price: Optional - if provided, skips get_all_mids() call for faster execution
        """
        return self.place_order(
            symbol=symbol,
            is_buy=is_buy,
            size=size,
            price=current_price,  # Will use this if provided, else fetches mid
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

    def place_stop_loss(self, symbol: str, is_long: bool, size: float, trigger_price: float):
        """
        Place a stop-loss order for an existing position.

        Args:
            symbol: Trading pair
            is_long: True if closing a long position, False if closing short
            size: Position size to close
            trigger_price: Price at which SL triggers

        Returns:
            Order response
        """
        meta = self.get_meta()
        asset_index = self._get_asset_index(meta, symbol)

        # Round price and size
        trigger_price = self._round_price(trigger_price, symbol, meta)
        size = self._round_size(size, symbol, meta)

        # SL sells if long, buys if short
        is_buy = not is_long

        order = {
            "a": asset_index,
            "b": is_buy,
            "p": float_to_wire(trigger_price),
            "s": float_to_wire(size),
            "r": True,  # reduce_only
            "t": {
                "trigger": {
                    "isMarket": True,
                    "triggerPx": float_to_wire(trigger_price),
                    "tpsl": "sl"
                }
            }
        }

        action = {
            "type": "order",
            "orders": [order],
            "grouping": "na"
        }

        return self._exchange_request(action)

    def place_take_profit(self, symbol: str, is_long: bool, size: float, trigger_price: float):
        """
        Place a take-profit order for an existing position.

        Args:
            symbol: Trading pair
            is_long: True if closing a long position, False if closing short
            size: Position size to close
            trigger_price: Price at which TP triggers

        Returns:
            Order response
        """
        meta = self.get_meta()
        asset_index = self._get_asset_index(meta, symbol)

        # Round price and size
        trigger_price = self._round_price(trigger_price, symbol, meta)
        size = self._round_size(size, symbol, meta)

        # TP sells if long, buys if short
        is_buy = not is_long

        order = {
            "a": asset_index,
            "b": is_buy,
            "p": float_to_wire(trigger_price),
            "s": float_to_wire(size),
            "r": True,  # reduce_only
            "t": {
                "trigger": {
                    "isMarket": True,
                    "triggerPx": float_to_wire(trigger_price),
                    "tpsl": "tp"
                }
            }
        }

        action = {
            "type": "order",
            "orders": [order],
            "grouping": "na"
        }

        return self._exchange_request(action)

    def place_tp_sl_orders(self, symbol: str, is_long: bool, size: float,
                           stop_loss: float, take_profit: float):
        """
        Place both TP and SL orders for a position.

        Args:
            symbol: Trading pair
            is_long: True if long position, False if short
            size: Position size
            stop_loss: Stop loss price
            take_profit: Take profit price

        Returns:
            Dict with 'sl' and 'tp' responses
        """
        sl_response = self.place_stop_loss(symbol, is_long, size, stop_loss)
        tp_response = self.place_take_profit(symbol, is_long, size, take_profit)

        return {
            'sl': sl_response,
            'tp': tp_response
        }

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

        nonce = int(time.time() * 1000)
        is_mainnet = not config.USE_TESTNET

        # Sign using the official SDK method
        signature = sign_l1_action(
            wallet=self.wallet,
            action=action,
            vault_address=None,
            nonce=nonce,
            is_mainnet=is_mainnet
        )

        payload = {
            "action": action,
            "nonce": nonce,
            "signature": signature,
            "vaultAddress": None
        }

        url = f"{self.base_url}/exchange"
        response = requests.post(url, json=payload)
        response.raise_for_status()
        return response.json()

    def _get_asset_index(self, meta: dict, symbol: str) -> int:
        """Get asset index from metadata"""
        for i, asset in enumerate(meta["universe"]):
            if asset["name"] == symbol:
                return i
        raise ValueError(f"Symbol {symbol} not found")

    def _round_price(self, price: float, symbol: str, meta: dict) -> float:
        """
        Round price to valid format for Hyperliquid API.

        Based on official SDK: round(float(f"{px:.5g}"), 6 - sz_decimals)
        - First format to 5 significant figures
        - Then round to (6 - szDecimals) decimal places for perps
        """
        sz_decimals = 3  # default
        for asset in meta["universe"]:
            if asset["name"] == symbol:
                sz_decimals = asset.get("szDecimals", 3)
                break

        # First: 5 significant figures, then round to correct decimal places
        # For perps: 6 - szDecimals decimal places
        decimal_places = max(0, 6 - sz_decimals)
        price_5g = float(f"{price:.5g}")
        return round(price_5g, decimal_places)

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
