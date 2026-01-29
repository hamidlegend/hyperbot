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

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('bot.log')
    ]
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

            logger.info(
                f"[{timeframe}m] Monitoring trendline | "
                f"TL Price: {tl_price:.4f} | "
                f"Current: {current_price:.4f} | "
                f"Distance: {distance:.2f}%"
            )

        return {'setup': setup, 'df': df}

    def _minutes_to_interval(self, minutes: int) -> str:
        """Convert minutes to interval string"""
        intervals = {1: "1m", 5: "5m", 15: "15m", 60: "1h", 240: "4h", 1440: "1d"}
        return intervals.get(minutes, "5m")

    def _process_breakout(self, setup: dict, df, timeframe: int):
        """Process a breakout signal"""
        if setup['status'] == 'breakout':
            logger.info("=" * 40)
            logger.info(f"BREAKOUT DETECTED! [{timeframe}m]")
            logger.info(f"Timeframe: {timeframe} minutes")
            logger.info(f"Entry: {setup['entry_price']:.4f}")
            logger.info(f"SL: {setup['stop_loss']:.4f}")
            logger.info(f"TP: {setup['take_profit']:.4f}")
            logger.info(f"Risk: {setup['risk_percent']:.2%}")

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
        logger.info("=" * 40)
        logger.info("EXECUTING TRADE")
        logger.info(f"Symbol: {params.symbol}")
        logger.info(f"Direction: {params.direction}")
        logger.info(f"Size: {params.position_size}")
        logger.info(f"Entry: {params.entry_price:.4f}")
        logger.info(f"SL: {params.stop_loss:.4f}")
        logger.info(f"TP: {params.take_profit:.4f}")
        logger.info(f"Risk Amount: ${params.risk_amount:.2f}")

        # Open position
        response = self.position_manager.open_position(params)

        if response.get('status') == 'ok':
            self.last_signal_time = datetime.now()
            logger.info("Trade executed successfully!")
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
            logger.info("=" * 40)
            logger.info("STOP LOSS HIT")
            self.position_manager.close_position(reason="Stop loss hit")
            return

        if status['status'] == 'tp_hit':
            logger.info("=" * 40)
            logger.info("TAKE PROFIT HIT")
            self.position_manager.close_position(reason="Take profit hit")
            return

        # Position still open
        pnl = status.get('unrealized_pnl', 0)
        logger.debug(f"Position open | PnL: ${pnl:.2f}")

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

    Args:
        client: HyperliquidClient instance
        private_key: Private key string

    Returns:
        True if account is ready for trading
    """
    print("\n" + "=" * 60)
    print("  ACCOUNT VERIFICATION")
    print("=" * 60)

    # Check 1: Private key
    if not private_key:
        print("\n  [X] PRIVATE_KEY not found!")
        print("      Create .env file with: PRIVATE_KEY=your_key_here")
        return False
    else:
        masked = f"{private_key[:6]}...{private_key[-4:]}"
        print(f"\n  [OK] Private Key: {masked}")

    # Check 2: API Connection
    try:
        mids = client.get_all_mids()
        if "HYPE" in mids:
            print(f"  [OK] API Connected - HYPE Price: ${float(mids['HYPE']):.4f}")
        else:
            print("  [X] HYPE not found on exchange!")
            return False
    except Exception as e:
        print(f"  [X] API Connection Failed: {e}")
        return False

    # Check 3: Account Access & Balance
    try:
        user_state = client.get_user_state()
        if not user_state:
            print("  [X] Could not access account!")
            return False

        margin = user_state.get("marginSummary", {})
        balance = float(margin.get("accountValue", 0))
        margin_used = float(margin.get("totalMarginUsed", 0))
        available = balance - margin_used

        print(f"\n  [OK] Account Connected")
        print(f"      ┌─────────────────────────────────")
        print(f"      │ Total Balance:    ${balance:.2f}")
        print(f"      │ Margin Used:      ${margin_used:.2f}")
        print(f"      │ Available:        ${available:.2f}")
        print(f"      └─────────────────────────────────")

        # Check minimum balance for trading
        # With 2% risk and 5x leverage, minimum useful balance is ~$10
        min_balance = 10.0
        if balance < min_balance:
            print(f"\n  [X] Balance too low for trading!")
            print(f"      Minimum recommended: ${min_balance:.2f}")
            return False

        # Calculate max position size for reference
        hype_price = float(client.get_all_mids().get("HYPE", 0))
        if hype_price > 0:
            risk_amount = balance * config.RISK_PER_TRADE
            # Rough estimate assuming 2% stop loss distance
            max_position_value = risk_amount / 0.02 * config.LEVERAGE
            max_hype_size = max_position_value / hype_price

            print(f"\n      Trading Parameters:")
            print(f"      ┌─────────────────────────────────")
            print(f"      │ Risk per Trade:   {config.RISK_PER_TRADE*100:.1f}% (${risk_amount:.2f})")
            print(f"      │ Max Position:     ~{max_hype_size:.2f} HYPE")
            print(f"      │ Max Value:        ~${max_position_value:.2f}")
            print(f"      └─────────────────────────────────")

    except Exception as e:
        print(f"  [X] Account Access Failed: {e}")
        print("      Check your private key is correct")
        return False

    # Check 4: Set leverage
    try:
        client.set_leverage(config.SYMBOL, config.LEVERAGE)
        print(f"  [OK] Leverage Set: {config.LEVERAGE}x")
    except Exception as e:
        print(f"  [!] Could not set leverage: {e}")
        print("      (OK if you have open positions)")

    print("\n" + "=" * 60)
    print(f"  ACCOUNT READY FOR TRADING!")
    print(f"  Wallet: {client.account_address}")
    print("=" * 60 + "\n")

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
