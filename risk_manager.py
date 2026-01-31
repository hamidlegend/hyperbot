"""
Risk Manager Module
Handles position sizing, risk calculation, and trade management
"""

import logging
from typing import Optional, Dict
from dataclasses import dataclass
import config

logger = logging.getLogger(__name__)


@dataclass
class TradeParams:
    """Parameters for a trade"""
    symbol: str
    direction: str  # "long" or "short"
    entry_price: float
    stop_loss: float
    take_profit: float
    position_size: float
    risk_amount: float
    leverage: int


class RiskManager:
    """Manages risk and position sizing"""

    def __init__(self, client):
        """
        Initialize RiskManager

        Args:
            client: HyperliquidClient instance
        """
        self.client = client

    def calculate_position_size(
        self,
        entry_price: float,
        stop_loss: float,
        account_balance: float = None
    ) -> float:
        """
        Calculate position size based on risk parameters

        Args:
            entry_price: Entry price
            stop_loss: Stop loss price
            account_balance: Account balance (fetched if None)

        Returns:
            Position size
        """
        if account_balance is None:
            balance = self.client.get_balance()
            account_balance = balance['account_value']

        # Risk amount = account_balance * risk_per_trade
        risk_amount = account_balance * config.RISK_PER_TRADE

        # Risk per unit = |entry - stop_loss|
        risk_per_unit = abs(entry_price - stop_loss)

        if risk_per_unit == 0:
            logger.warning("Risk per unit is zero, cannot calculate position size")
            return 0

        # Position size (without leverage)
        base_position_size = risk_amount / risk_per_unit

        # Apply leverage
        position_value = base_position_size * entry_price
        max_position_value = account_balance * config.LEVERAGE

        # Ensure we don't exceed max leverage
        if position_value > max_position_value:
            position_size = max_position_value / entry_price
        else:
            position_size = base_position_size

        return round(position_size, 4)

    def create_trade_params(
        self,
        setup: dict,
        account_balance: float = None
    ) -> Optional[TradeParams]:
        """
        Create trade parameters from a setup

        Args:
            setup: Trade setup dict
            account_balance: Account balance (fetched if None)

        Returns:
            TradeParams or None
        """
        if setup['status'] != 'breakout':
            return None

        entry_price = setup['entry_price']
        stop_loss = setup['stop_loss']
        take_profit = setup['take_profit']

        # Calculate position size
        position_size = self.calculate_position_size(
            entry_price=entry_price,
            stop_loss=stop_loss,
            account_balance=account_balance
        )

        if position_size <= 0:
            return None

        # Calculate risk amount
        risk_per_unit = abs(entry_price - stop_loss)
        risk_amount = position_size * risk_per_unit

        return TradeParams(
            symbol=config.SYMBOL,
            direction=config.DIRECTION,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_size=position_size,
            risk_amount=risk_amount,
            leverage=config.LEVERAGE
        )

    def validate_trade(self, params: TradeParams) -> tuple[bool, str]:
        """
        Validate trade parameters before execution

        Args:
            params: TradeParams to validate

        Returns:
            Tuple of (is_valid, reason)
        """
        # Check position size
        if params.position_size <= 0:
            return False, "Invalid position size"

        # Check SL is below entry for long
        if params.direction == "long" and params.stop_loss >= params.entry_price:
            return False, "Stop loss must be below entry for long"

        # Check TP is above entry for long
        if params.direction == "long" and params.take_profit <= params.entry_price:
            return False, "Take profit must be above entry for long"

        # Check risk amount is reasonable
        balance = self.client.get_balance()
        if params.risk_amount > balance['account_value'] * 0.1:
            return False, "Risk amount too high (>10% of account)"

        return True, "Trade validated"


class PositionManager:
    """Manages open positions"""

    def __init__(self, client):
        """
        Initialize PositionManager

        Args:
            client: HyperliquidClient instance
        """
        self.client = client
        self.active_trades: Dict[str, dict] = {}

    def has_open_position(self, symbol: str = None) -> bool:
        """Check if there's an open position for symbol"""
        symbol = symbol or config.SYMBOL
        position = self.client.get_position(symbol)
        return position is not None and abs(position['size']) > 0

    def get_position_info(self, symbol: str = None) -> Optional[dict]:
        """Get current position information"""
        symbol = symbol or config.SYMBOL
        return self.client.get_position(symbol)

    def open_position(self, params: TradeParams) -> dict:
        """
        Open a new position

        Args:
            params: TradeParams for the trade

        Returns:
            Order response with 'filled' key indicating if order was actually filled
        """
        # Set leverage first
        logger.info(f"Setting leverage to {params.leverage}x")
        self.client.set_leverage(params.symbol, params.leverage)

        # Place market order
        logger.info(
            f"Opening {params.direction} position: "
            f"{params.position_size} {params.symbol} @ ~{params.entry_price}"
        )

        is_buy = params.direction == "long"

        response = self.client.place_market_order(
            symbol=params.symbol,
            is_buy=is_buy,
            size=params.position_size,
            current_price=params.entry_price  # Pass price to avoid extra API call
        )

        # Log full response for debugging
        logger.debug(f"Full API response: {response}")

        # Check if API request was successful
        if response.get('status') != 'ok':
            logger.error(f"API request failed: {response}")
            response['filled'] = False
            return response

        # Check the actual order status in response.response.data.statuses
        order_response = response.get('response', {})
        order_data = order_response.get('data', {})
        statuses = order_data.get('statuses', [])

        if not statuses:
            logger.error(f"No order status in response: {response}")
            response['filled'] = False
            return response

        # Check first order status (we only place one order)
        order_status = statuses[0]
        logger.info(f"Order status: {order_status}")

        # Check if order was filled
        if 'filled' in order_status:
            fill_info = order_status['filled']
            filled_size = float(fill_info.get('totalSz', 0))
            avg_price = float(fill_info.get('avgPx', 0))

            logger.info(f"[OK] Order FILLED: {filled_size} @ ${avg_price}")

            # Store trade info
            self.active_trades[params.symbol] = {
                'params': params,
                'entry_time': response.get('timestamp'),
                'status': 'open',
                'filled_size': filled_size,
                'avg_price': avg_price
            }
            response['filled'] = True
            response['filled_size'] = filled_size
            response['avg_price'] = avg_price

            # Place TP/SL orders on exchange
            is_long = params.direction == "long"
            logger.info(f"Placing TP/SL orders: SL=${params.stop_loss}, TP=${params.take_profit}")

            try:
                tp_sl_response = self.client.place_tp_sl_orders(
                    symbol=params.symbol,
                    is_long=is_long,
                    size=filled_size,
                    stop_loss=params.stop_loss,
                    take_profit=params.take_profit
                )

                # Check SL order
                sl_resp = tp_sl_response.get('sl', {})
                if sl_resp.get('status') == 'ok':
                    sl_statuses = sl_resp.get('response', {}).get('data', {}).get('statuses', [])
                    if sl_statuses and 'resting' in sl_statuses[0]:
                        sl_oid = sl_statuses[0]['resting'].get('oid')
                        logger.info(f"[OK] Stop Loss set @ ${params.stop_loss} (oid: {sl_oid})")
                        response['sl_oid'] = sl_oid
                    elif sl_statuses and 'error' in sl_statuses[0]:
                        logger.error(f"[X] SL order rejected: {sl_statuses[0].get('error')}")
                else:
                    logger.error(f"[X] SL order failed: {sl_resp}")

                # Check TP order
                tp_resp = tp_sl_response.get('tp', {})
                if tp_resp.get('status') == 'ok':
                    tp_statuses = tp_resp.get('response', {}).get('data', {}).get('statuses', [])
                    if tp_statuses and 'resting' in tp_statuses[0]:
                        tp_oid = tp_statuses[0]['resting'].get('oid')
                        logger.info(f"[OK] Take Profit set @ ${params.take_profit} (oid: {tp_oid})")
                        response['tp_oid'] = tp_oid
                    elif tp_statuses and 'error' in tp_statuses[0]:
                        logger.error(f"[X] TP order rejected: {tp_statuses[0].get('error')}")
                else:
                    logger.error(f"[X] TP order failed: {tp_resp}")

            except Exception as e:
                logger.error(f"Failed to place TP/SL orders: {e}")

        elif 'resting' in order_status:
            # Order is sitting in orderbook, not filled
            oid = order_status['resting'].get('oid')
            logger.warning(f"[!] Order RESTING (not filled), oid: {oid}")
            logger.warning("Market order should not rest - possible liquidity issue")
            response['filled'] = False
            response['resting_oid'] = oid

        elif 'error' in order_status:
            # Order was rejected
            error_msg = order_status.get('error', 'Unknown error')
            logger.error(f"[X] Order REJECTED: {error_msg}")
            response['filled'] = False
            response['error_message'] = error_msg

        else:
            # Unknown status
            logger.warning(f"Unknown order status: {order_status}")
            response['filled'] = False

        return response

    def close_position(self, symbol: str = None, reason: str = "") -> dict:
        """
        Close position for symbol

        Args:
            symbol: Trading pair
            reason: Reason for closing

        Returns:
            Order response
        """
        symbol = symbol or config.SYMBOL
        logger.info(f"Closing position for {symbol}. Reason: {reason}")

        response = self.client.close_position(symbol)

        # Log full response
        logger.debug(f"Close position response: {response}")

        # Check if it's a "no position" message
        if response.get('message') == 'No position to close':
            logger.info("No position to close")
            if symbol in self.active_trades:
                del self.active_trades[symbol]
            return response

        # Check actual order status
        if response.get('status') == 'ok':
            order_response = response.get('response', {})
            order_data = order_response.get('data', {})
            statuses = order_data.get('statuses', [])

            if statuses:
                order_status = statuses[0]
                if 'filled' in order_status:
                    fill_info = order_status['filled']
                    logger.info(f"[OK] Position closed: {fill_info.get('totalSz')} @ ${fill_info.get('avgPx')}")
                    if symbol in self.active_trades:
                        del self.active_trades[symbol]
                elif 'error' in order_status:
                    logger.error(f"[X] Close order rejected: {order_status.get('error')}")
                else:
                    logger.warning(f"Close order status: {order_status}")
            else:
                logger.warning(f"No status in close response: {response}")
        else:
            logger.error(f"Failed to close position: {response}")

        return response

    def check_sl_tp(self, symbol: str = None) -> Optional[str]:
        """
        Check if price has hit SL or TP

        Args:
            symbol: Trading pair

        Returns:
            "sl", "tp", or None
        """
        symbol = symbol or config.SYMBOL

        if symbol not in self.active_trades:
            return None

        trade = self.active_trades[symbol]
        params = trade['params']

        # Get current price
        position = self.get_position_info(symbol)
        if position is None:
            return None

        current_pnl = position['unrealized_pnl']
        entry_price = position['entry_price']

        # For long positions
        if params.direction == "long":
            # Check if we need to get current price instead
            mids = self.client.get_all_mids()
            current_price = float(mids.get(symbol, 0))

            if current_price <= params.stop_loss:
                return "sl"
            elif current_price >= params.take_profit:
                return "tp"

        return None

    def monitor_position(self, symbol: str = None) -> dict:
        """
        Monitor an open position

        Args:
            symbol: Trading pair

        Returns:
            Position status dict
        """
        symbol = symbol or config.SYMBOL

        position = self.get_position_info(symbol)

        if position is None:
            return {'status': 'no_position'}

        sl_tp_status = self.check_sl_tp(symbol)

        if sl_tp_status == "sl":
            return {
                'status': 'sl_hit',
                'position': position,
                'action': 'close'
            }
        elif sl_tp_status == "tp":
            return {
                'status': 'tp_hit',
                'position': position,
                'action': 'close'
            }

        return {
            'status': 'open',
            'position': position,
            'unrealized_pnl': position['unrealized_pnl']
        }
