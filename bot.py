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
        if self.position_manager.has_open_position():
            self._manage_position()
        else:
            self._look_for_entry()

    def _look_for_entry(self):
        """Look for new trade entry across all timeframes"""
        logger.debug("Looking for entry signal...")

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
        """Process a breakout signal"""
        if setup['status'] == 'breakout':
            # Print colorful breakout banner
            print(f"\n{C.BRIGHT_GREEN}{'═' * 60}")
            print(f"  🚀 BREAKOUT DETECTED! [{timeframe}m] 🚀")
            print(f"{'═' * 60}{C.RESET}")
            print(f"  {C.WHITE}Timeframe:{C.RESET}  {C.BRIGHT_YELLOW}{timeframe} minutes{C.RESET}")
            print(f"  {C.WHITE}Entry:{C.RESET}      {C.BRIGHT_CYAN}${setup['entry_price']:.4f}{C.RESET}")
            print(f"  {C.WHITE}Stop Loss:{C.RESET}  {C.BRIGHT_RED}${setup['stop_loss']:.4f}{C.RESET}")
            print(f"  {C.WHITE}Take Profit:{C.RESET}{C.BRIGHT_GREEN}${setup['take_profit']:.4f}{C.RESET}")
            print(f"  {C.WHITE}Risk:{C.RESET}       {C.YELLOW}{setup['risk_percent']:.2%}{C.RESET}")
            print(f"{C.BRIGHT_GREEN}{'═' * 60}{C.RESET}\n")

            # Apply filters
            passed, reason = apply_filters(df, setup)

            if not passed:
                logger.warning(f"Trade rejected by filters: {reason}")
                return

            logger.info(f"Filters passed: {reason}")

            # Create trade parameters
            params = self.risk_manager.create_trade_params(setup)

            if params is None:
                logger.warning("Could not create trade parameters")
                return

            # Validate trade
            is_valid, reason = self.risk_manager.validate_trade(params)

            if not is_valid:
                logger.warning(f"Trade validation failed: {reason}")
                return

            # Execute trade
            self._execute_trade(params)

    def _execute_trade(self, params):
        """Execute a trade"""
        print(f"\n{C.BRIGHT_CYAN}{'═' * 60}")
        print(f"  📊 EXECUTING TRADE")
        print(f"{'═' * 60}{C.RESET}")
        print(f"  {C.WHITE}Symbol:{C.RESET}      {C.BRIGHT_WHITE}{params.symbol}{C.RESET}")
        print(f"  {C.WHITE}Direction:{C.RESET}   {C.BRIGHT_GREEN}▲ {params.direction.upper()}{C.RESET}")
        print(f"  {C.WHITE}Size:{C.RESET}        {C.BRIGHT_CYAN}{params.position_size} {params.symbol}{C.RESET}")
        print(f"  {C.WHITE}Entry:{C.RESET}       {C.BRIGHT_WHITE}${params.entry_price:.4f}{C.RESET}")
        print(f"  {C.WHITE}Stop Loss:{C.RESET}   {C.BRIGHT_RED}${params.stop_loss:.4f}{C.RESET}")
        print(f"  {C.WHITE}Take Profit:{C.RESET} {C.BRIGHT_GREEN}${params.take_profit:.4f}{C.RESET}")
        print(f"  {C.WHITE}Risk Amount:{C.RESET} {C.YELLOW}${params.risk_amount:.2f}{C.RESET}")
        print(f"{C.BRIGHT_CYAN}{'═' * 60}{C.RESET}")

        # Open position
        response = self.position_manager.open_position(params)

        if response.get('status') == 'ok':
            self.last_signal_time = datetime.now()
            print(f"\n  {C.BRIGHT_GREEN}✓ Trade executed successfully!{C.RESET}\n")
        else:
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
            print(f"  ✗ STOP LOSS HIT")
            print(f"{'═' * 60}{C.RESET}\n")
            self.position_manager.close_position(reason="Stop loss hit")
            return

        if status['status'] == 'tp_hit':
            print(f"\n{C.BRIGHT_GREEN}{'═' * 60}")
            print(f"  ★ TAKE PROFIT HIT! 🎉")
            print(f"{'═' * 60}{C.RESET}\n")
            self.position_manager.close_position(reason="Take profit hit")
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
