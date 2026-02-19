"""
Telegram Signal Trading Bot
Main entry point for signal-based trading on Hyperliquid.

Connects to Telegram channels, parses trading signals, and executes trades
on the Hyperliquid exchange.

Usage:
    python telegram_bot.py                 # Run the signal bot
    python telegram_bot.py --list-channels # List your Telegram channels/groups
    python telegram_bot.py --dry-run       # Parse signals but don't trade
"""

import os
import sys
import time
import logging
import asyncio
import argparse
from datetime import datetime
from typing import Optional, Dict
from dotenv import load_dotenv

import config
from hyperliquid_client import HyperliquidClient
from risk_manager import TradeParams, PositionManager
from signal_parser import SignalParser, ParsedSignal
from telegram_listener import TelegramListener
from colors import Colors

# Load environment variables
load_dotenv()

C = Colors

# Setup logging
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(logging.Formatter(
    f'{C.DIM}%(asctime)s{C.RESET} - '
    f'{C.MAGENTA}%(name)s{C.RESET} - '
    f'%(levelname)s - %(message)s'
))

file_handler = logging.FileHandler('telegram_bot.log')
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
))

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    handlers=[console_handler, file_handler]
)
logger = logging.getLogger('TelegramBot')


class SignalTrader:
    """
    Processes parsed signals and executes trades on Hyperliquid.

    Handles:
    - New trade signals (open positions with SL/TP)
    - Management signals (risk free, close, move SL)
    - Position tracking per symbol
    """

    def __init__(self, client: HyperliquidClient, dry_run: bool = False):
        """
        Initialize signal trader.

        Args:
            client: HyperliquidClient instance
            dry_run: If True, only parse and display signals without trading
        """
        self.client = client
        self.position_manager = PositionManager(client)
        self.dry_run = dry_run
        self.active_signals: Dict[str, ParsedSignal] = {}
        self.last_trade_time: Optional[datetime] = None
        self._cached_balance: Optional[float] = None
        self._balance_cache_time = 0

    def _get_balance(self) -> float:
        """Get account balance with caching"""
        now = time.time()
        if self._cached_balance is None or (now - self._balance_cache_time) > 60:
            balance = self.client.get_balance()
            self._cached_balance = balance['account_value']
            self._balance_cache_time = now
        return self._cached_balance

    def _check_cooldown(self) -> bool:
        """Check if we're still in cooldown period"""
        if self.last_trade_time is None:
            return False
        elapsed = (datetime.now() - self.last_trade_time).total_seconds()
        return elapsed < config.TELEGRAM_TRADE_COOLDOWN

    async def process_signal(self, signal: ParsedSignal):
        """
        Process a parsed signal — either execute trade or manage position.

        Args:
            signal: Parsed signal from SignalParser
        """
        if signal.signal_type == "new_trade":
            await self._handle_new_trade(signal)
        elif signal.signal_type == "management":
            await self._handle_management(signal)

    async def _handle_new_trade(self, signal: ParsedSignal):
        """Handle a new trade signal"""
        self._print_signal(signal)

        if self.dry_run:
            print(f"  {C.BRIGHT_YELLOW}[DRY RUN] Trade not executed{C.RESET}\n")
            return

        if not config.TELEGRAM_AUTO_TRADE:
            print(f"  {C.BRIGHT_YELLOW}[AUTO-TRADE OFF] Set TELEGRAM_AUTO_TRADE=True to execute{C.RESET}\n")
            return

        if self._check_cooldown():
            remaining = config.TELEGRAM_TRADE_COOLDOWN - (
                datetime.now() - self.last_trade_time
            ).total_seconds()
            print(f"  {C.DIM}Cooldown: {remaining:.0f}s remaining{C.RESET}\n")
            return

        # Check if already have position for this symbol
        if self.position_manager.has_open_position(signal.symbol):
            print(f"  {C.BRIGHT_YELLOW}[SKIP] Already have open position for {signal.symbol}{C.RESET}\n")
            return

        # Determine leverage
        leverage = signal.leverage or config.TELEGRAM_DEFAULT_LEVERAGE
        leverage = min(leverage, config.TELEGRAM_MAX_LEVERAGE)

        # Set leverage on exchange
        try:
            self.client.set_leverage(signal.symbol, leverage)
            logger.info(f"Leverage set to {leverage}x for {signal.symbol}")
        except Exception as e:
            logger.error(f"Failed to set leverage: {e}")
            print(f"  {C.BRIGHT_RED}[ERROR] Failed to set leverage: {e}{C.RESET}\n")
            return

        # Use first entry price
        entry_price = signal.entries[0]
        stop_loss = signal.stop_loss

        # Determine take profit
        if signal.take_profits:
            if config.TELEGRAM_USE_FIRST_TP_ONLY:
                take_profit = signal.take_profits[0]
            else:
                take_profit = signal.take_profits[0]  # First TP for the SL/TP order
        else:
            # No TP specified — calculate based on risk/reward
            if stop_loss:
                risk = abs(entry_price - stop_loss)
                if signal.direction == "long":
                    take_profit = entry_price + risk * config.RISK_REWARD_RATIO
                else:
                    take_profit = entry_price - risk * config.RISK_REWARD_RATIO
            else:
                print(f"  {C.BRIGHT_RED}[SKIP] No SL and no TP — cannot determine risk{C.RESET}\n")
                return

        if not stop_loss:
            print(f"  {C.BRIGHT_RED}[SKIP] No stop loss specified — too risky{C.RESET}\n")
            return

        # Calculate position size
        balance = self._get_balance()
        risk_amount = balance * config.RISK_PER_TRADE
        risk_per_unit = abs(entry_price - stop_loss)

        if risk_per_unit == 0:
            print(f"  {C.BRIGHT_RED}[SKIP] Entry equals SL — invalid signal{C.RESET}\n")
            return

        position_size = risk_amount / risk_per_unit

        # Apply leverage cap
        position_value = position_size * entry_price
        max_position_value = balance * leverage
        if position_value > max_position_value:
            position_size = max_position_value / entry_price

        position_size = round(position_size, 4)

        # Create trade params
        params = TradeParams(
            symbol=signal.symbol,
            direction=signal.direction,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_size=position_size,
            risk_amount=risk_amount,
            leverage=leverage,
        )

        # Validate
        if signal.direction == "long" and stop_loss >= entry_price:
            print(f"  {C.BRIGHT_RED}[SKIP] SL ({stop_loss}) >= Entry ({entry_price}) for LONG{C.RESET}\n")
            return
        if signal.direction == "short" and stop_loss <= entry_price:
            print(f"  {C.BRIGHT_RED}[SKIP] SL ({stop_loss}) <= Entry ({entry_price}) for SHORT{C.RESET}\n")
            return

        # Execute trade
        print(f"  {C.BRIGHT_CYAN}Executing trade...{C.RESET}")

        if signal.order_type == "market":
            response = self.position_manager.open_position(params)
        else:
            # Limit order
            is_buy = signal.direction == "long"
            response = self.client.place_limit_order(
                symbol=signal.symbol,
                is_buy=is_buy,
                size=position_size,
                price=entry_price,
            )
            # For limit orders, also need to handle TP/SL after fill
            response['filled'] = False  # Limit orders don't fill immediately
            print(f"  {C.BRIGHT_YELLOW}Limit order placed @ ${entry_price}{C.RESET}")

        if response.get('filled'):
            self.last_trade_time = datetime.now()
            self.active_signals[signal.symbol] = signal
            filled_size = response.get('filled_size', position_size)
            avg_price = response.get('avg_price', entry_price)
            print(f"  {C.BRIGHT_GREEN}[OK] FILLED: {filled_size} {signal.symbol} @ ${avg_price}{C.RESET}")
        elif response.get('error_message'):
            print(f"  {C.BRIGHT_RED}[ERROR] {response['error_message']}{C.RESET}")
        else:
            if signal.order_type != "limit":
                print(f"  {C.BRIGHT_RED}[FAILED] Order not filled{C.RESET}")

        print()

    async def _handle_management(self, signal: ParsedSignal):
        """Handle a management signal"""
        self._print_management(signal)

        if self.dry_run:
            print(f"  {C.BRIGHT_YELLOW}[DRY RUN] Action not executed{C.RESET}\n")
            return

        if not config.TELEGRAM_AUTO_TRADE:
            print(f"  {C.BRIGHT_YELLOW}[AUTO-TRADE OFF] Action not executed{C.RESET}\n")
            return

        symbol = signal.symbol
        if symbol == "UNKNOWN":
            print(f"  {C.BRIGHT_YELLOW}[SKIP] Unknown symbol{C.RESET}\n")
            return

        if signal.action == "close":
            # Close position
            if self.position_manager.has_open_position(symbol):
                self.position_manager.close_position(symbol, reason="Telegram signal: close")
                print(f"  {C.BRIGHT_GREEN}[OK] Position closed for {symbol}{C.RESET}")
                if symbol in self.active_signals:
                    del self.active_signals[symbol]
            else:
                print(f"  {C.DIM}No open position for {symbol}{C.RESET}")

        elif signal.action == "risk_free":
            # Move SL to entry price
            if symbol in self.active_signals:
                original = self.active_signals[symbol]
                entry = original.entries[0] if original.entries else None
                if entry:
                    # Cancel existing SL and place new one at entry
                    self.client.cancel_all_orders(symbol)
                    position = self.client.get_position(symbol)
                    if position and abs(position['size']) > 0:
                        is_long = position['size'] > 0
                        self.client.place_stop_loss(
                            symbol=symbol,
                            is_long=is_long,
                            size=abs(position['size']),
                            trigger_price=entry,
                        )
                        print(f"  {C.BRIGHT_GREEN}[OK] SL moved to entry ${entry} (Risk Free){C.RESET}")
                    else:
                        print(f"  {C.DIM}No position to make risk free{C.RESET}")
                else:
                    print(f"  {C.DIM}No entry price recorded for {symbol}{C.RESET}")
            else:
                print(f"  {C.DIM}No active signal for {symbol}{C.RESET}")

        elif signal.action == "move_sl" and signal.new_sl:
            # Move SL to new price
            self.client.cancel_all_orders(symbol)
            position = self.client.get_position(symbol)
            if position and abs(position['size']) > 0:
                is_long = position['size'] > 0
                self.client.place_stop_loss(
                    symbol=symbol,
                    is_long=is_long,
                    size=abs(position['size']),
                    trigger_price=signal.new_sl,
                )
                print(f"  {C.BRIGHT_GREEN}[OK] SL moved to ${signal.new_sl}{C.RESET}")
            else:
                print(f"  {C.DIM}No position for {symbol}{C.RESET}")

        elif signal.action == "tp_hit":
            print(f"  {C.DIM}TP hit notification — no action needed{C.RESET}")

        print()

    def _print_signal(self, signal: ParsedSignal):
        """Print a formatted new trade signal"""
        direction_color = C.BRIGHT_GREEN if signal.direction == "long" else C.BRIGHT_RED
        direction_icon = "LONG" if signal.direction == "long" else "SHORT"

        print(f"\n{C.BRIGHT_CYAN}{'=' * 60}{C.RESET}")
        print(f"  {C.BRIGHT_WHITE}{C.BOLD}NEW SIGNAL{C.RESET}")
        print(f"{C.BRIGHT_CYAN}{'=' * 60}{C.RESET}")
        print(f"  {C.WHITE}Symbol:{C.RESET}      {C.BRIGHT_WHITE}{signal.symbol}USDT{C.RESET}")
        print(f"  {C.WHITE}Direction:{C.RESET}   {direction_color}{direction_icon}{C.RESET}")
        print(f"  {C.WHITE}Type:{C.RESET}        {C.CYAN}{signal.order_type.upper()}{C.RESET}")

        # Entries
        entries_str = ", ".join(f"${e}" for e in signal.entries)
        print(f"  {C.WHITE}Entry:{C.RESET}       {C.BRIGHT_CYAN}{entries_str}{C.RESET}")

        # Stop Loss
        if signal.stop_loss:
            print(f"  {C.WHITE}Stop Loss:{C.RESET}   {C.BRIGHT_RED}${signal.stop_loss}{C.RESET}")
        else:
            print(f"  {C.WHITE}Stop Loss:{C.RESET}   {C.BRIGHT_YELLOW}Not specified{C.RESET}")

        # Take Profits
        if signal.take_profits:
            for i, tp in enumerate(signal.take_profits):
                print(f"  {C.WHITE}TP{i+1}:{C.RESET}         {C.BRIGHT_GREEN}${tp}{C.RESET}")

        # Leverage
        lev = signal.leverage or config.TELEGRAM_DEFAULT_LEVERAGE
        print(f"  {C.WHITE}Leverage:{C.RESET}    {C.BRIGHT_YELLOW}{lev}x{C.RESET}")

        print(f"{C.BRIGHT_CYAN}{'=' * 60}{C.RESET}")

    def _print_management(self, signal: ParsedSignal):
        """Print a formatted management signal"""
        action_map = {
            "close": ("CLOSE POSITION", C.BRIGHT_RED),
            "risk_free": ("RISK FREE", C.BRIGHT_GREEN),
            "move_sl": ("MOVE STOP LOSS", C.BRIGHT_YELLOW),
            "tp_hit": ("TP HIT", C.BRIGHT_CYAN),
        }
        action_text, color = action_map.get(
            signal.action, ("UNKNOWN", C.WHITE)
        )

        print(f"\n{color}{'=' * 60}{C.RESET}")
        print(f"  {C.BOLD}{action_text}{C.RESET} — {signal.symbol}USDT")
        if signal.new_sl:
            print(f"  New SL: {C.BRIGHT_YELLOW}${signal.new_sl}{C.RESET}")
        print(f"  {C.DIM}{signal.raw_text[:80]}{C.RESET}")
        print(f"{color}{'=' * 60}{C.RESET}")


async def run_bot(dry_run: bool = False):
    """Main async entry point for the Telegram signal bot"""

    # Load credentials
    private_key = os.getenv('PRIVATE_KEY') or os.getenv('HYPERLIQUID_PRIVATE_KEY')
    account_address = os.getenv('WALLET_ADDRESS') or os.getenv('HYPERLIQUID_ACCOUNT_ADDRESS')

    # Telegram credentials (from env or config)
    api_id = os.getenv('TELEGRAM_API_ID') or config.TELEGRAM_API_ID
    api_hash = os.getenv('TELEGRAM_API_HASH') or config.TELEGRAM_API_HASH
    phone = os.getenv('TELEGRAM_PHONE') or config.TELEGRAM_PHONE

    if not api_id or not api_hash or not phone:
        print(f"\n{C.BRIGHT_RED}{'=' * 60}{C.RESET}")
        print(f"  {C.BRIGHT_RED}Telegram credentials not configured!{C.RESET}")
        print(f"{C.BRIGHT_RED}{'=' * 60}{C.RESET}")
        print(f"\n  Set these in .env or config.py:")
        print(f"    TELEGRAM_API_ID=your_api_id")
        print(f"    TELEGRAM_API_HASH=your_api_hash")
        print(f"    TELEGRAM_PHONE=+98912xxxxxxx")
        print(f"\n  Get API credentials from: https://my.telegram.org/apps")
        sys.exit(1)

    api_id = int(api_id)

    # Initialize Hyperliquid client
    print(f"\n{C.BRIGHT_CYAN}{'=' * 60}{C.RESET}")
    print(f"  {C.BRIGHT_WHITE}{C.BOLD}TELEGRAM SIGNAL BOT{C.RESET}")
    print(f"{C.BRIGHT_CYAN}{'=' * 60}{C.RESET}")

    if not private_key:
        print(f"  {C.BRIGHT_YELLOW}[!] No private key — running in display-only mode{C.RESET}")
        dry_run = True

    client = None
    if not dry_run:
        try:
            client = HyperliquidClient(
                private_key=private_key,
                account_address=account_address,
            )
            balance = client.get_balance()
            print(f"  {C.BRIGHT_GREEN}[OK]{C.RESET} Hyperliquid connected")
            print(f"  {C.WHITE}Balance:{C.RESET} {C.BRIGHT_GREEN}${balance['account_value']:.2f}{C.RESET}")
        except Exception as e:
            print(f"  {C.BRIGHT_RED}[ERROR] Hyperliquid connection failed: {e}{C.RESET}")
            print(f"  {C.BRIGHT_YELLOW}Falling back to display-only mode{C.RESET}")
            dry_run = True

    mode = "DRY RUN" if dry_run else ("DISPLAY ONLY" if not config.TELEGRAM_AUTO_TRADE else "AUTO TRADE")
    mode_color = C.BRIGHT_YELLOW if mode != "AUTO TRADE" else C.BRIGHT_GREEN
    print(f"  {C.WHITE}Mode:{C.RESET} {mode_color}{mode}{C.RESET}")
    print(f"{C.BRIGHT_CYAN}{'=' * 60}{C.RESET}\n")

    # Initialize components
    parser = SignalParser()
    trader = SignalTrader(client, dry_run=dry_run)

    # Setup Telegram listener
    listener = TelegramListener(
        api_id=api_id,
        api_hash=api_hash,
        phone=phone,
        session_name=config.TELEGRAM_SESSION_NAME,
        channel_ids=config.TELEGRAM_CHANNEL_IDS,
        channel_usernames=config.TELEGRAM_CHANNEL_USERNAMES,
    )

    # Register signal handler
    async def on_message(sender: str, text: str):
        signal = parser.parse(text)
        if signal:
            await trader.process_signal(signal)
        else:
            # Log unrecognized messages at debug level
            logger.debug(f"Unrecognized message from {sender}: {text[:60]}...")

    listener.on_signal(on_message)

    # Start listening
    await listener.start()
    await listener.run_forever()


async def list_channels():
    """List all Telegram channels/groups the user is part of"""
    api_id = os.getenv('TELEGRAM_API_ID') or config.TELEGRAM_API_ID
    api_hash = os.getenv('TELEGRAM_API_HASH') or config.TELEGRAM_API_HASH
    phone = os.getenv('TELEGRAM_PHONE') or config.TELEGRAM_PHONE

    if not api_id or not api_hash or not phone:
        print(f"\n{C.BRIGHT_RED}Telegram credentials not configured!{C.RESET}")
        print(f"Set TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE in .env")
        sys.exit(1)

    listener = TelegramListener(
        api_id=int(api_id),
        api_hash=api_hash,
        phone=phone,
    )
    await listener.list_dialogs()
    await listener.stop()


def main():
    """Entry point"""
    parser = argparse.ArgumentParser(description="Telegram Signal Trading Bot")
    parser.add_argument(
        '--list-channels', action='store_true',
        help='List your Telegram channels/groups and their IDs'
    )
    parser.add_argument(
        '--dry-run', action='store_true',
        help='Parse and display signals without executing trades'
    )
    args = parser.parse_args()

    if args.list_channels:
        asyncio.run(list_channels())
    else:
        try:
            asyncio.run(run_bot(dry_run=args.dry_run))
        except KeyboardInterrupt:
            print(f"\n{C.BRIGHT_YELLOW}Shutting down...{C.RESET}")


if __name__ == "__main__":
    main()
