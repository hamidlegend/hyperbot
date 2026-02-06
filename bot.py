"""
HYPE Trendline Breakout Trading Bot
Main bot implementation
"""

import time
import logging
import sys
from datetime import datetime
from typing import Optional
import os
from dotenv import load_dotenv

import config
from hyperliquid_client import HyperliquidClient
from data_fetcher import DataFetcher
from trendline import analyze_trendline_setup
from filters import apply_filters
from risk_manager import RiskManager, PositionManager
from colors import (
    Colors, success, error, warning, info, highlight, bold,
    price, percent, banner, box, breakout_alert, trade_executed,
    stop_loss_hit, take_profit_hit, monitoring, status_ok, status_fail
)

# Load environment variables
load_dotenv()

# Import colors and setup colored logging
from colors import Colors
C = Colors

# Custom colored formatter
class ColoredFormatter(logging.Formatter):
    """Custom formatter with colors for different log levels"""

    COLORS = {
        'DEBUG': Colors.DIM,
        'INFO': Colors.BRIGHT_CYAN,
        'WARNING': Colors.BRIGHT_YELLOW,
        'ERROR': Colors.BRIGHT_RED,
        'CRITICAL': Colors.BG_RED + Colors.BRIGHT_WHITE,
    }

    def format(self, record):
        # Color the level name
        color = self.COLORS.get(record.levelname, Colors.RESET)
        record.levelname = f"{color}{record.levelname:8}{Colors.RESET}"

        # Color the logger name
        record.name = f"{Colors.MAGENTA}{record.name}{Colors.RESET}"

        # Color the message based on content
        msg = record.getMessage()
        if 'BREAKOUT' in msg:
            record.msg = f"{Colors.BRIGHT_GREEN}{Colors.BOLD}{msg}{Colors.RESET}"
        elif 'Entry:' in msg or 'SL:' in msg or 'TP:' in msg:
            record.msg = f"{Colors.BRIGHT_CYAN}{msg}{Colors.RESET}"
        elif 'ERROR' in msg or 'Failed' in msg:
            record.msg = f"{Colors.BRIGHT_RED}{msg}{Colors.RESET}"
        elif 'Monitoring' in msg:
            record.msg = f"{Colors.YELLOW}{msg}{Colors.RESET}"
        elif '[1m]' in msg:
            record.msg = f"{Colors.BRIGHT_YELLOW}{msg}{Colors.RESET}"
        elif '[5m]' in msg:
            record.msg = f"{Colors.BRIGHT_BLUE}{msg}{Colors.RESET}"
        elif 'Position' in msg or 'Trade' in msg:
            record.msg = f"{Colors.BRIGHT_MAGENTA}{msg}{Colors.RESET}"

        return super().format(record)


# Setup logging with colors
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(ColoredFormatter(
    f'{Colors.DIM}%(asctime)s{Colors.RESET} - %(name)s - %(levelname)s - %(message)s'
))

file_handler = logging.FileHandler('bot.log')
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
))

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    handlers=[console_handler, file_handler]
)
logger = logging.getLogger('TrendlineBot')


class TrendlineBreakoutBot:
    """
    Main trading bot class

    Strategy:
    1. Find descending trendline on swing highs
    2. Wait for price to break above trendline
    3. Apply filters to validate setup
    4. Enter long with SL below recent swing low
    5. TP at 1:1 risk/reward
    """

    def __init__(self, private_key: str = None, account_address: str = None):
        """
        Initialize the bot

        Args:
            private_key: Wallet private key for trading
            account_address: Wallet address
        """
        logger.info("=" * 60)
        logger.info("Initializing Trendline Breakout Bot")
        logger.info("=" * 60)

        # Initialize client
        self.client = HyperliquidClient(
            private_key=private_key,
            account_address=account_address
        )

        # Initialize components
        self.data_fetcher = DataFetcher(self.client)
        self.risk_manager = RiskManager(self.client)
        self.position_manager = PositionManager(self.client)

        # State
        self.is_running = False
        self.last_signal_time = None
        self.last_trade_close_time = None  # Cooldown after closing position
        self.trade_cooldown_minutes = getattr(config, 'TRADE_COOLDOWN_MINUTES', 5)
        self.had_open_position = False  # Track if we had a position

        # Cache balance to avoid extra API calls during trade execution
        self._cached_balance = None
        self._balance_cache_time = 0

        # Get timeframes to monitor
        self.timeframes = getattr(config, 'TIMEFRAMES', [config.TIMEFRAME])

        logger.info(f"Symbol: {config.SYMBOL}")
        logger.info(f"Timeframes: {self.timeframes} minutes")
        logger.info(f"Risk per trade: {config.RISK_PER_TRADE * 100}%")
        logger.info(f"Leverage: {config.LEVERAGE}x")
        logger.info(f"Using {'Testnet' if config.USE_TESTNET else 'Mainnet'}")

    def run(self):
        """Main bot loop"""
        logger.info("Starting bot...")
        self.is_running = True

        while self.is_running:
            try:
                self._tick()
                time.sleep(config.CHECK_INTERVAL)

            except KeyboardInterrupt:
                logger.info("Received shutdown signal")
                self.stop()

            except Exception as e:
                logger.error(f"Error in main loop: {e}", exc_info=True)
                time.sleep(30)  # Wait before retrying

    def stop(self):
        """Stop the bot"""
        logger.info("Stopping bot...")
        self.is_running = False

    def _tick(self):
        """Single iteration of the bot loop"""
        logger.debug("=" * 40)
        logger.debug(f"Tick at {datetime.now()}")

        # Check for existing position
        has_position = self.position_manager.has_open_position()

        # Detect if position was closed externally (by exchange TP/SL orders)
        if self.had_open_position and not has_position:
            # Position was just closed - start cooldown
            self.last_trade_close_time = datetime.now()
            print(f"\n  {C.BRIGHT_CYAN}Position closed by exchange (TP/SL){C.RESET}")
            print(f"  {C.DIM}Cooldown started: {self.trade_cooldown_minutes} min{C.RESET}")
            logger.info(f"Position closed externally - cooldown started for {self.trade_cooldown_minutes} min")

        # Update position tracking state
        self.had_open_position = has_position

        if has_position:
            self._manage_position()
        else:
            self._look_for_entry()

    def _look_for_entry(self):
        """Look for new trade entry across all timeframes"""
        logger.debug("Looking for entry signal...")

        # Refresh balance cache every 60 seconds
        import time as _time
        now = _time.time()
        if self._cached_balance is None or (now - self._balance_cache_time) > 60:
            try:
                balance = self.client.get_balance()
                self._cached_balance = balance['account_value']
                self._balance_cache_time = now
            except Exception as e:
                logger.warning(f"Failed to refresh balance cache: {e}")

        # Check cooldown after last trade close
        if self.last_trade_close_time:
            elapsed = (datetime.now() - self.last_trade_close_time).total_seconds() / 60
            if elapsed < self.trade_cooldown_minutes:
                remaining = self.trade_cooldown_minutes - elapsed
                print(f"  {C.DIM}Cooldown: {remaining:.1f} min remaining after last trade{C.RESET}")
                return

        # Check each timeframe for setups
        for timeframe in self.timeframes:
            result = self._check_timeframe(timeframe)

            if result and result['setup'] and result['setup']['status'] == 'breakout':
                # Found a breakout! Process it
                self._process_breakout(result['setup'], result['df'], timeframe)
                return  # Only take one trade at a time

    def _check_timeframe(self, timeframe: int):
        """Check a specific timeframe for trendline setup"""
        interval = self._minutes_to_interval(timeframe)
        logger.debug(f"Checking {timeframe}m timeframe...")

        # Fetch candle data for this timeframe
        df = self.data_fetcher.get_candles(
            symbol=config.SYMBOL,
            interval=interval,
            limit=config.CANDLES_TO_ANALYZE
        )

        if df.empty or len(df) < config.CANDLES_TO_ANALYZE // 2:
            logger.warning(f"Not enough candle data for {timeframe}m")
            return None

        # Add indicators
        df = self.data_fetcher.add_indicators(df)

        # Analyze for trendline setup
        setup = analyze_trendline_setup(df)

        if setup is None:
            logger.debug(f"[{timeframe}m] No valid trendline found")
            return None

        if setup['status'] == 'monitoring':
            tl_price = setup['current_trendline_price']
            current_price = setup['current_price']
            distance = (current_price - tl_price) / tl_price * 100

            # Color based on timeframe
            tf_color = C.BRIGHT_YELLOW if timeframe == 1 else C.BRIGHT_BLUE
            # Color based on distance
            dist_color = C.BRIGHT_GREEN if distance > 0 else C.BRIGHT_RED
            dist_sign = "+" if distance > 0 else ""

            print(
                f"  {tf_color}[{timeframe}m]{C.RESET} "
                f"{C.DIM}Monitoring{C.RESET} │ "
                f"TL: {C.CYAN}${tl_price:.4f}{C.RESET} │ "
                f"Price: {C.WHITE}${current_price:.4f}{C.RESET} │ "
                f"Distance: {dist_color}{dist_sign}{distance:.2f}%{C.RESET}"
            )

        return {'setup': setup, 'df': df}

    def _minutes_to_interval(self, minutes: int) -> str:
        """Convert minutes to interval string"""
        intervals = {1: "1m", 5: "5m", 15: "15m", 60: "1h", 240: "4h", 1440: "1d"}
        return intervals.get(minutes, "5m")

    def _process_breakout(self, setup: dict, df, timeframe: int):
        """Process a breakout signal - optimized for speed"""
        if setup['status'] == 'breakout':
            # Apply filters FIRST (before printing) - speed matters
            passed, reason = apply_filters(df, setup)
            if not passed:
                logger.warning(f"Trade rejected by filters: {reason}")
                return

            # Create trade parameters using cached balance
            params = self.risk_manager.create_trade_params(
                setup, account_balance=self._cached_balance
            )
            if params is None:
                logger.warning("Could not create trade parameters")
                return

            # Validate trade (no API calls)
            is_valid, reason = self.risk_manager.validate_trade(params)
            if not is_valid:
                logger.warning(f"Trade validation failed: {reason}")
                return

            # Print breakout info
            print(f"\n{C.BRIGHT_GREEN}{'=' * 60}")
            print(f"  BREAKOUT [{timeframe}m]")
            print(f"{'=' * 60}{C.RESET}")
            print(f"  {C.WHITE}Entry:{C.RESET}      {C.BRIGHT_CYAN}${setup['entry_price']:.4f}{C.RESET}")
            print(f"  {C.WHITE}Stop Loss:{C.RESET}  {C.BRIGHT_RED}${setup['stop_loss']:.4f}{C.RESET}")
            print(f"  {C.WHITE}Take Profit:{C.RESET}{C.BRIGHT_GREEN}${setup['take_profit']:.4f}{C.RESET}")
            print(f"  {C.WHITE}Size:{C.RESET}       {C.BRIGHT_CYAN}{params.position_size} {params.symbol}{C.RESET}")
            print(f"{C.BRIGHT_GREEN}{'=' * 60}{C.RESET}")

            # Execute trade IMMEDIATELY
            self._execute_trade(params)

            # Show swing points AFTER trade is opened (not before, to save time)
            self._print_swing_info(setup)

    def _print_swing_info(self, setup: dict):
        """Print swing highs and lows info after trade is opened"""
        trendline = setup.get('trendline')
        swing_highs = setup.get('swing_highs', [])
        swing_lows = setup.get('swing_lows', [])
        wave_low = setup.get('wave_low')

        print(f"\n  {C.BRIGHT_YELLOW}--- Swing Points ---{C.RESET}")

        # Show trendline points
        if trendline:
            pattern_width = trendline.point2_index - trendline.point1_index
            print(f"  {C.WHITE}Trendline:{C.RESET} {C.CYAN}slope={trendline.slope:.6f}, touches={trendline.num_touches}{C.RESET}")
            print(f"  {C.WHITE}Pattern width:{C.RESET} {C.BRIGHT_GREEN}{pattern_width} candles{C.RESET}")
            print(f"    {C.DIM}Point 1: index={trendline.point1_index}, price=${trendline.point1_price:.4f}{C.RESET}")
            print(f"    {C.DIM}Point 2: index={trendline.point2_index}, price=${trendline.point2_price:.4f}{C.RESET}")

        # Show swing highs (used for trendline)
        if swing_highs:
            print(f"\n  {C.BRIGHT_MAGENTA}Swing Highs ({len(swing_highs)} found):{C.RESET}")
            for i, sh in enumerate(swing_highs[-6:]):  # Last 6
                ts = sh.get('timestamp', '')
                ts_str = f" @ {ts}" if ts else ""
                # Mark which ones were used for trendline
                used = ""
                if trendline and sh['index'] in [trendline.point1_index, trendline.point2_index]:
                    used = f" {C.BRIGHT_GREEN}<-- trendline{C.RESET}"
                print(f"    {C.MAGENTA}SH#{i+1}: ${sh['price']:.4f} (idx={sh['index']}){ts_str}{used}{C.RESET}")

        # Show swing lows
        if swing_lows:
            print(f"\n  {C.BRIGHT_CYAN}Swing Lows ({len(swing_lows)} found):{C.RESET}")
            for i, sl in enumerate(swing_lows[-6:]):  # Last 6
                ts = sl.get('timestamp', '')
                ts_str = f" @ {ts}" if ts else ""
                print(f"    {C.CYAN}SL#{i+1}: ${sl['price']:.4f} (idx={sl['index']}){ts_str}{C.RESET}")

        # Show wave low (used for stop loss)
        if wave_low:
            print(f"\n  {C.BRIGHT_RED}Wave Low (SL basis): ${wave_low:.4f}{C.RESET}")
            print(f"  {C.RED}Stop Loss placed at: ${setup['stop_loss']:.4f}{C.RESET}")

        print(f"  {C.BRIGHT_YELLOW}--------------------{C.RESET}\n")

    def _execute_trade(self, params):
        """Execute a trade - speed optimized"""
        # Open position FIRST, print after
        response = self.position_manager.open_position(params)

        # Check if order was actually filled (not just API success)
        if response.get('filled'):
            self.last_signal_time = datetime.now()
            filled_size = response.get('filled_size', params.position_size)
            avg_price = response.get('avg_price', params.entry_price)
            print(f"\n  {C.BRIGHT_GREEN}✓ Trade FILLED!{C.RESET}")
            print(f"    {C.WHITE}Size:{C.RESET} {C.BRIGHT_CYAN}{filled_size}{C.RESET}")
            print(f"    {C.WHITE}Avg Price:{C.RESET} {C.BRIGHT_CYAN}${avg_price:.4f}{C.RESET}\n")
        elif response.get('error_message'):
            # Order was rejected
            error_msg = response.get('error_message')
            print(f"\n  {C.BRIGHT_RED}✗ Order REJECTED: {error_msg}{C.RESET}")
            logger.error(f"Order rejected: {error_msg}")
        elif response.get('resting_oid'):
            # Order is resting (not filled for market order = problem)
            oid = response.get('resting_oid')
            print(f"\n  {C.BRIGHT_YELLOW}⚠ Order RESTING (not filled): oid={oid}{C.RESET}")
            print(f"    {C.YELLOW}This shouldn't happen for market orders - check liquidity{C.RESET}")
            logger.warning(f"Market order resting instead of filling: oid={oid}")
        else:
            # Unknown failure
            print(f"\n  {C.BRIGHT_RED}✗ Trade execution failed!{C.RESET}")
            logger.error(f"Trade execution failed: {response}")

    def _manage_position(self):
        """Manage existing position"""
        status = self.position_manager.monitor_position()

        if status['status'] == 'no_position':
            logger.debug("No position to manage")
            return

        position = status.get('position', {})

        if status['status'] == 'sl_hit':
            print(f"\n{C.BRIGHT_RED}{'═' * 60}")
            print(f"  [X] STOP LOSS HIT")
            print(f"{'═' * 60}{C.RESET}\n")
            self.position_manager.close_position(reason="Stop loss hit")
            self.last_trade_close_time = datetime.now()  # Start cooldown
            print(f"  {C.DIM}Cooldown started: {self.trade_cooldown_minutes} min{C.RESET}")
            return

        if status['status'] == 'tp_hit':
            print(f"\n{C.BRIGHT_GREEN}{'═' * 60}")
            print(f"  [OK] TAKE PROFIT HIT!")
            print(f"{'═' * 60}{C.RESET}\n")
            self.position_manager.close_position(reason="Take profit hit")
            self.last_trade_close_time = datetime.now()  # Start cooldown
            print(f"  {C.DIM}Cooldown started: {self.trade_cooldown_minutes} min{C.RESET}")
            return

        # Position still open
        pnl = status.get('unrealized_pnl', 0)
        pnl_color = C.BRIGHT_GREEN if pnl >= 0 else C.BRIGHT_RED
        pnl_sign = "+" if pnl >= 0 else ""
        print(f"  {C.DIM}Position open{C.RESET} │ PnL: {pnl_color}{pnl_sign}${pnl:.2f}{C.RESET}")

    def get_status(self) -> dict:
        """Get current bot status"""
        position = self.position_manager.get_position_info()
        balance = self.client.get_balance()

        return {
            'is_running': self.is_running,
            'symbol': config.SYMBOL,
            'has_position': position is not None,
            'position': position,
            'account_balance': balance['account_value'],
            'last_signal_time': self.last_signal_time
        }


def verify_account(client, private_key: str) -> bool:
    """
    Verify account connection and trading capability at startup
    """
    C = Colors

    print(f"\n{C.BRIGHT_CYAN}{'═' * 60}{C.RESET}")
    print(f"{C.BRIGHT_WHITE}{C.BOLD}  🔐 ACCOUNT VERIFICATION{C.RESET}")
    print(f"{C.BRIGHT_CYAN}{'═' * 60}{C.RESET}")

    # Check 1: Private key
    if not private_key:
        print(f"\n  {C.BRIGHT_RED}[✗] PRIVATE_KEY not found!{C.RESET}")
        print(f"      Create .env file with: PRIVATE_KEY=your_key_here")
        return False
    else:
        masked = f"{private_key[:6]}...{private_key[-4:]}"
        print(f"\n  {C.BRIGHT_GREEN}[✓]{C.RESET} Private Key: {C.CYAN}{masked}{C.RESET}")

    # Check 2: API Connection
    try:
        mids = client.get_all_mids()
        if "HYPE" in mids:
            hype_price = float(mids['HYPE'])
            print(f"  {C.BRIGHT_GREEN}[✓]{C.RESET} API Connected - HYPE: {C.BRIGHT_CYAN}${hype_price:.4f}{C.RESET}")
        else:
            print(f"  {C.BRIGHT_RED}[✗] HYPE not found on exchange!{C.RESET}")
            return False
    except Exception as e:
        print(f"  {C.BRIGHT_RED}[✗] API Connection Failed: {e}{C.RESET}")
        return False

    # Check 3: Account Access & Balance
    try:
        user_state = client.get_user_state()
        if not user_state:
            print(f"  {C.BRIGHT_RED}[✗] Could not access account!{C.RESET}")
            return False

        margin = user_state.get("marginSummary", {})
        balance = float(margin.get("accountValue", 0))
        margin_used = float(margin.get("totalMarginUsed", 0))
        available = balance - margin_used

        print(f"\n  {C.BRIGHT_GREEN}[✓]{C.RESET} Account Connected")
        print(f"      {C.CYAN}┌{'─' * 35}{C.RESET}")
        print(f"      {C.CYAN}│{C.RESET} Total Balance:  {C.BRIGHT_GREEN}${balance:.2f}{C.RESET}")
        print(f"      {C.CYAN}│{C.RESET} Margin Used:    {C.YELLOW}${margin_used:.2f}{C.RESET}")
        print(f"      {C.CYAN}│{C.RESET} Available:      {C.BRIGHT_CYAN}${available:.2f}{C.RESET}")
        print(f"      {C.CYAN}└{'─' * 35}{C.RESET}")

        min_balance = 10.0
        if balance < min_balance:
            print(f"\n  {C.BRIGHT_RED}[✗] Balance too low for trading!{C.RESET}")
            print(f"      Minimum recommended: ${min_balance:.2f}")
            return False

        hype_price = float(client.get_all_mids().get("HYPE", 0))
        if hype_price > 0:
            risk_amount = balance * config.RISK_PER_TRADE
            max_position_value = risk_amount / 0.02 * config.LEVERAGE
            max_hype_size = max_position_value / hype_price

            print(f"\n      {C.BRIGHT_WHITE}Trading Parameters:{C.RESET}")
            print(f"      {C.MAGENTA}┌{'─' * 35}{C.RESET}")
            print(f"      {C.MAGENTA}│{C.RESET} Risk per Trade: {C.YELLOW}{config.RISK_PER_TRADE*100:.1f}%{C.RESET} ({C.CYAN}${risk_amount:.2f}{C.RESET})")
            print(f"      {C.MAGENTA}│{C.RESET} Max Position:   {C.BRIGHT_CYAN}~{max_hype_size:.2f} HYPE{C.RESET}")
            print(f"      {C.MAGENTA}│{C.RESET} Max Value:      {C.BRIGHT_CYAN}~${max_position_value:.2f}{C.RESET}")
            print(f"      {C.MAGENTA}└{'─' * 35}{C.RESET}")

    except Exception as e:
        print(f"  {C.BRIGHT_RED}[✗] Account Access Failed: {e}{C.RESET}")
        return False

    # Check 4: Set leverage
    try:
        client.set_leverage(config.SYMBOL, config.LEVERAGE)
        print(f"\n  {C.BRIGHT_GREEN}[✓]{C.RESET} Leverage Set: {C.BRIGHT_YELLOW}{config.LEVERAGE}x{C.RESET}")
    except Exception as e:
        print(f"  {C.YELLOW}[!] Could not set leverage: {e}{C.RESET}")

    print(f"\n{C.BRIGHT_GREEN}{'═' * 60}{C.RESET}")
    print(f"{C.BRIGHT_GREEN}{C.BOLD}  ✓ ACCOUNT READY FOR TRADING!{C.RESET}")
    print(f"  {C.DIM}Wallet: {client.account_address}{C.RESET}")
    print(f"{C.BRIGHT_GREEN}{'═' * 60}{C.RESET}\n")

    return True


def test_trade(client) -> bool:
    """
    Execute a test trade to verify the full trading flow works.
    Opens a small REAL position, then closes it immediately.
    """
    C = Colors

    print(f"\n{C.BRIGHT_YELLOW}{'═' * 60}{C.RESET}")
    print(f"{C.BRIGHT_YELLOW}  🧪 TEST TRADE - Opening Real Position{C.RESET}")
    print(f"{C.BRIGHT_YELLOW}{'═' * 60}{C.RESET}")

    try:
        # Get current price
        mids = client.get_all_mids()
        current_price = float(mids.get("HYPE", 0))

        if current_price == 0:
            print(f"  {C.BRIGHT_RED}[✗] Could not get HYPE price{C.RESET}")
            return False

        print(f"  {C.WHITE}Current HYPE Price:{C.RESET} {C.BRIGHT_CYAN}${current_price:.4f}{C.RESET}")

        # Calculate minimum size to meet $10 minimum order value
        min_value = 10.0
        test_size = round((min_value / current_price) * 1.1, 2)  # Add 10% buffer
        test_size = max(test_size, 0.4)  # At least 0.4 HYPE (~$12 at $30)

        print(f"  {C.WHITE}Test Size:{C.RESET} {C.BRIGHT_CYAN}{test_size} HYPE{C.RESET} (${test_size * current_price:.2f})")

        print(f"\n  {C.WHITE}Step 1: Opening test position{C.RESET}")
        print(f"  {C.DIM}Buying {test_size} HYPE (market order)...{C.RESET}")

        # Place market order to OPEN position
        response = client.place_market_order(
            symbol="HYPE",
            is_buy=True,
            size=test_size
        )

        print(f"  {C.DIM}Response: {response}{C.RESET}")

        # Check API status first
        if response.get('status') != 'ok':
            print(f"  {C.BRIGHT_RED}[✗] API request failed: {response}{C.RESET}")
            print(f"\n{C.BRIGHT_RED}{'═' * 60}")
            print(f"  ✗ TEST FAILED - API Error!")
            print(f"{'═' * 60}{C.RESET}\n")
            return False

        # Check actual order status
        order_response = response.get('response', {})
        order_data = order_response.get('data', {})
        statuses = order_data.get('statuses', [])

        if not statuses:
            print(f"  {C.BRIGHT_RED}[✗] No order status in response{C.RESET}")
            print(f"\n{C.BRIGHT_RED}{'═' * 60}")
            print(f"  ✗ TEST FAILED - No status!")
            print(f"{'═' * 60}{C.RESET}\n")
            return False

        order_status = statuses[0]
        print(f"  {C.CYAN}Order status: {order_status}{C.RESET}")

        # Check if order was FILLED
        if 'filled' in order_status:
            fill_info = order_status['filled']
            filled_size = fill_info.get('totalSz', '0')
            avg_price = fill_info.get('avgPx', '0')

            print(f"  {C.BRIGHT_GREEN}[✓] Position OPENED!{C.RESET}")
            print(f"      Size: {C.BRIGHT_CYAN}{filled_size} HYPE{C.RESET}")
            print(f"      Price: {C.BRIGHT_CYAN}${avg_price}{C.RESET}")

            # Now close the position
            print(f"\n  {C.WHITE}Step 2: Closing test position{C.RESET}")
            print(f"  {C.DIM}Selling {filled_size} HYPE to close...{C.RESET}")

            import time
            time.sleep(1)  # Small delay

            close_response = client.close_position("HYPE")
            print(f"  {C.DIM}Close response: {close_response}{C.RESET}")

            # Check close status
            if close_response.get('status') == 'ok':
                close_statuses = close_response.get('response', {}).get('data', {}).get('statuses', [])
                if close_statuses and 'filled' in close_statuses[0]:
                    close_fill = close_statuses[0]['filled']
                    print(f"  {C.BRIGHT_GREEN}[✓] Position CLOSED!{C.RESET}")
                    print(f"      Size: {C.BRIGHT_CYAN}{close_fill.get('totalSz')} HYPE{C.RESET}")
                    print(f"      Price: {C.BRIGHT_CYAN}${close_fill.get('avgPx')}{C.RESET}")

                    print(f"\n{C.BRIGHT_GREEN}{'═' * 60}")
                    print(f"  ✓ TEST PASSED! Full trading flow works!")
                    print(f"{'═' * 60}{C.RESET}\n")
                    return True
                elif close_statuses and 'error' in close_statuses[0]:
                    print(f"  {C.BRIGHT_RED}[✗] Close REJECTED: {close_statuses[0].get('error')}{C.RESET}")
                else:
                    print(f"  {C.BRIGHT_YELLOW}[?] Unexpected close status: {close_statuses}{C.RESET}")
            else:
                print(f"  {C.BRIGHT_RED}[✗] Close failed: {close_response}{C.RESET}")

            # Position opened but close had issues
            print(f"\n{C.BRIGHT_YELLOW}{'═' * 60}")
            print(f"  ⚠ Position opened but close had issues - CHECK MANUALLY!")
            print(f"{'═' * 60}{C.RESET}\n")
            return False

        elif 'resting' in order_status:
            oid = order_status['resting'].get('oid')
            print(f"  {C.BRIGHT_YELLOW}[⚠] Order RESTING (not filled): oid={oid}{C.RESET}")
            print(f"  {C.YELLOW}Market order didn't fill - possible liquidity issue{C.RESET}")

            # Cancel the resting order
            print(f"  {C.DIM}Cancelling resting order...{C.RESET}")
            client.cancel_all_orders("HYPE")

            print(f"\n{C.BRIGHT_RED}{'═' * 60}")
            print(f"  ✗ TEST FAILED - Order didn't fill!")
            print(f"{'═' * 60}{C.RESET}\n")
            return False

        elif 'error' in order_status:
            error_msg = order_status.get('error', 'Unknown error')
            print(f"  {C.BRIGHT_RED}[✗] Order REJECTED: {error_msg}{C.RESET}")

            # Check for common errors
            if 'does not exist' in error_msg.lower():
                print(f"\n  {C.BRIGHT_RED}Signing Error!{C.RESET}")
                print(f"  {C.YELLOW}The wallet address derived from signature doesn't match.{C.RESET}")
            elif 'margin' in error_msg.lower():
                print(f"\n  {C.BRIGHT_YELLOW}Margin Issue!{C.RESET}")
                print(f"  {C.YELLOW}Not enough margin for test trade.{C.RESET}")
            elif 'size' in error_msg.lower():
                print(f"\n  {C.BRIGHT_YELLOW}Size Issue!{C.RESET}")
                print(f"  {C.YELLOW}Order size too small or invalid.{C.RESET}")

            print(f"\n{C.BRIGHT_RED}{'═' * 60}")
            print(f"  ✗ TEST FAILED - Order rejected!")
            print(f"{'═' * 60}{C.RESET}\n")
            return False

        else:
            print(f"  {C.BRIGHT_YELLOW}[?] Unknown order status: {order_status}{C.RESET}")
            print(f"\n{C.BRIGHT_YELLOW}{'═' * 60}")
            print(f"  ? TEST INCONCLUSIVE")
            print(f"{'═' * 60}{C.RESET}\n")
            return False

    except Exception as e:
        print(f"  {C.BRIGHT_RED}[✗] Error: {e}{C.RESET}")
        import traceback
        traceback.print_exc()
        print(f"\n{C.BRIGHT_RED}{'═' * 60}")
        print(f"  ✗ TEST FAILED - Exception!")
        print(f"{'═' * 60}{C.RESET}\n")
        return False


def main():
    """Main entry point"""
    # Load credentials from environment
    private_key = os.getenv('PRIVATE_KEY') or os.getenv('HYPERLIQUID_PRIVATE_KEY')
    account_address = os.getenv('WALLET_ADDRESS') or os.getenv('HYPERLIQUID_ACCOUNT_ADDRESS')

    # Create client first to verify account
    logger.info("Checking account connection...")

    try:
        client = HyperliquidClient(
            private_key=private_key,
            account_address=account_address
        )
    except Exception as e:
        logger.error(f"Failed to initialize client: {e}")
        sys.exit(1)

    # Verify account before starting
    if not verify_account(client, private_key):
        logger.error("Account verification failed! Cannot start trading.")
        sys.exit(1)

    # Test trade disabled - uncomment to test full trading flow
    # if not test_trade(client):
    #     logger.error("Test trade failed! Signing may be broken.")
    #     sys.exit(1)

    # Create and run bot
    bot = TrendlineBreakoutBot(
        private_key=private_key,
        account_address=account_address
    )

    try:
        bot.run()
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
    finally:
        bot.stop()


if __name__ == "__main__":
    main()
