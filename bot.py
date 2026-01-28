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

        logger.info(f"Symbol: {config.SYMBOL}")
        logger.info(f"Timeframe: {config.TIMEFRAME}m")
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
        """Look for new trade entry"""
        logger.debug("Looking for entry signal...")

        # Fetch candle data
        df = self.data_fetcher.get_candles()

        if df.empty or len(df) < config.CANDLES_TO_ANALYZE // 2:
            logger.warning("Not enough candle data")
            return

        # Add indicators
        df = self.data_fetcher.add_indicators(df)

        # Analyze for trendline setup
        setup = analyze_trendline_setup(df)

        if setup is None:
            logger.debug("No valid trendline found")
            return

        if setup['status'] == 'monitoring':
            tl_price = setup['current_trendline_price']
            current_price = setup['current_price']
            distance = (current_price - tl_price) / tl_price * 100

            logger.info(
                f"Monitoring trendline | "
                f"TL Price: {tl_price:.4f} | "
                f"Current: {current_price:.4f} | "
                f"Distance: {distance:.2f}%"
            )
            return

        if setup['status'] == 'breakout':
            logger.info("=" * 40)
            logger.info("BREAKOUT DETECTED!")
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


def main():
    """Main entry point"""
    # Load credentials from environment
    private_key = os.getenv('HYPERLIQUID_PRIVATE_KEY')
    account_address = os.getenv('HYPERLIQUID_ACCOUNT_ADDRESS')

    if not private_key:
        logger.warning("No private key found. Running in read-only mode.")
        logger.warning("Set HYPERLIQUID_PRIVATE_KEY in .env file for trading")

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
