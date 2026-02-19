"""
Telegram Signal Parser
Parses trading signals from Telegram channels into structured trade data.

Supports multiple signal formats:
- New trade signals (BUY/SELL MARKET/LIMIT with entries, SL, TP, leverage)
- Management signals (risk free, close position, move SL, TP hit notifications)
"""

import re
import logging
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ParsedSignal:
    """Parsed trading signal from Telegram"""
    signal_type: str  # "new_trade", "management"
    symbol: str  # e.g. "BNB" (without USDT suffix)
    direction: Optional[str] = None  # "long" or "short"
    order_type: Optional[str] = None  # "market" or "limit"
    entries: List[float] = field(default_factory=list)
    stop_loss: Optional[float] = None
    take_profits: List[float] = field(default_factory=list)
    leverage: Optional[int] = None
    # Management signal fields
    action: Optional[str] = None  # "close", "risk_free", "move_sl", "tp_hit"
    new_sl: Optional[float] = None  # New SL price for move_sl action
    raw_text: str = ""


class SignalParser:
    """
    Parses Telegram trading signals into structured ParsedSignal objects.

    Handles various signal formats including Persian/Finglish management messages.
    """

    # Regex patterns for signal components
    SYMBOL_PATTERN = re.compile(
        r'#?([A-Za-z]{2,10})(?:USDT|usdt)', re.IGNORECASE
    )
    DIRECTION_PATTERN = re.compile(
        r'\b(BUY|SELL|buy|sell|Buy|Sell)\b'
    )
    ORDER_TYPE_PATTERN = re.compile(
        r'\b(MARKET|LIMIT|market|limit|Market|Limit)\b'
    )
    LEVERAGE_PATTERN = re.compile(
        r'(?:leverage\s*)?(\d{1,3})\s*[xX]', re.IGNORECASE
    )
    SL_PATTERN = re.compile(
        r'(?:SL|sl|Sl|stop\s*loss)\s*[:\s]*(\d+\.?\d*)', re.IGNORECASE
    )
    TP_HEADER_PATTERN = re.compile(
        r'\b(?:TP|tp|Tp|targets?|Targets?|TARGETS?)\b', re.IGNORECASE
    )

    # Management signal keywords (Persian + Finglish + English)
    RISK_FREE_KEYWORDS = [
        'ریسک فری', 'risk free', 'ریسک‌فری',
        'استاپ بزارید نقطه ورود', 'RISK FREE',
    ]
    CLOSE_KEYWORDS = [
        'ببندش', 'ببندید', 'ببندیش', 'close',
    ]
    MOVE_SL_KEYWORDS = [
        'استاپ بزارید', 'استاپ بزار', 'move sl', 'move stop',
    ]
    TP_HIT_KEYWORDS = [
        'TP1', 'TP2', 'TP3', 'TP4',
        'target 1', 'target 2', 'target 3', 'target 4',
        'تارگت', 'khorde',
    ]

    def parse(self, text: str) -> Optional[ParsedSignal]:
        """
        Parse a Telegram message into a ParsedSignal.

        Args:
            text: Raw message text from Telegram

        Returns:
            ParsedSignal if successfully parsed, None otherwise
        """
        if not text or not text.strip():
            return None

        text = text.strip()

        # Try to extract symbol first
        symbol = self._extract_symbol(text)

        # Check if this is a management signal
        management = self._parse_management(text, symbol)
        if management:
            return management

        # Try to parse as new trade signal
        trade = self._parse_new_trade(text, symbol)
        if trade:
            return trade

        logger.debug(f"Could not parse message: {text[:80]}...")
        return None

    def _extract_symbol(self, text: str) -> Optional[str]:
        """Extract trading symbol from text"""
        match = self.SYMBOL_PATTERN.search(text)
        if match:
            return match.group(1).upper()

        # Fallback: look for symbol at start of message
        first_word = text.split()[0] if text.split() else ""
        first_word = first_word.lstrip('#')
        if first_word.upper().endswith('USDT'):
            return first_word[:-4].upper()

        return None

    def _parse_new_trade(self, text: str, symbol: Optional[str]) -> Optional[ParsedSignal]:
        """Parse a new trade signal"""
        # Must have a direction keyword
        dir_match = self.DIRECTION_PATTERN.search(text)
        if not dir_match:
            return None

        direction_raw = dir_match.group(1).upper()
        direction = "long" if direction_raw == "BUY" else "short"

        # Must have a symbol
        if not symbol:
            return None

        # Order type
        order_type = "market"
        type_match = self.ORDER_TYPE_PATTERN.search(text)
        if type_match:
            order_type = type_match.group(1).lower()

        # Extract stop loss
        sl_match = self.SL_PATTERN.search(text)
        stop_loss = float(sl_match.group(1)) if sl_match else None

        # Extract leverage
        leverage = None
        lev_match = self.LEVERAGE_PATTERN.search(text)
        if lev_match:
            leverage = int(lev_match.group(1))

        # Extract all numbers from the text
        entries, take_profits = self._extract_prices(text, direction, stop_loss)

        if not entries:
            return None

        signal = ParsedSignal(
            signal_type="new_trade",
            symbol=symbol,
            direction=direction,
            order_type=order_type,
            entries=entries,
            stop_loss=stop_loss,
            take_profits=take_profits,
            leverage=leverage,
            raw_text=text,
        )

        logger.info(
            f"Parsed signal: {direction.upper()} {symbol} @ {entries} "
            f"SL={stop_loss} TP={take_profits} Lev={leverage}x"
        )
        return signal

    def _extract_prices(self, text: str, direction: str, stop_loss: Optional[float]):
        """
        Extract entry prices and take profit prices from signal text.

        Strategy:
        1. Find all numbers in the text
        2. Identify which section they belong to (entry vs TP)
        3. Use SL and TP keywords as section delimiters
        """
        entries = []
        take_profits = []

        # Normalize text for parsing
        lines = text.replace('\n', ' ').replace('\r', ' ')

        # Find positions of key markers
        dir_match = self.DIRECTION_PATTERN.search(lines)
        type_match = self.ORDER_TYPE_PATTERN.search(lines)
        sl_match = self.SL_PATTERN.search(lines)
        tp_match = self.TP_HEADER_PATTERN.search(lines)
        lev_match = self.LEVERAGE_PATTERN.search(lines)

        # Determine where entry prices start (after direction/type keyword)
        entry_start = 0
        if type_match:
            entry_start = type_match.end()
        elif dir_match:
            entry_start = dir_match.end()

        # Determine where entry prices end (at SL, TP, or leverage keyword)
        entry_end = len(lines)
        sl_pos = sl_match.start() if sl_match else len(lines)
        tp_pos = tp_match.start() if tp_match else len(lines)

        # For some formats, leverage appears before TP (like "#IRUSDT BUY MARKET 0.09146 0.08527 4X TP ...")
        lev_pos = lev_match.start() if lev_match else len(lines)

        entry_end = min(sl_pos, tp_pos, lev_pos)

        # Extract entry prices from the entry section
        entry_section = lines[entry_start:entry_end]
        # Split by & for multi-entry signals
        entry_section = entry_section.replace('&', ' ')
        entry_numbers = re.findall(r'(\d+\.?\d*)', entry_section)
        entries = [float(n) for n in entry_numbers if float(n) > 0]

        # Extract TP prices
        if tp_match:
            tp_section = lines[tp_match.end():]
            # Remove leverage part if it comes after TP
            if lev_match and lev_match.start() > tp_match.end():
                tp_section = lines[tp_match.end():lev_match.start()]
            tp_numbers = re.findall(r'(\d+\.?\d*)', tp_section)
            take_profits = [float(n) for n in tp_numbers if float(n) > 0]
            # Filter out leverage number if accidentally included
            if lev_match:
                lev_val = int(lev_match.group(1))
                take_profits = [tp for tp in take_profits if tp != lev_val]
        else:
            # No TP header - look for numbers after SL section
            if sl_match:
                after_sl = lines[sl_match.end():]
                # Skip the SL price itself (already captured)
                # Look for remaining numbers
                remaining = re.findall(r'(\d+\.?\d*)', after_sl)
                remaining_floats = [float(n) for n in remaining if float(n) > 0]

                # Filter out SL value and leverage
                if stop_loss:
                    remaining_floats = [r for r in remaining_floats if r != stop_loss]
                if lev_match:
                    lev_val = int(lev_match.group(1))
                    remaining_floats = [r for r in remaining_floats if r != lev_val]

                take_profits = remaining_floats

        return entries, take_profits

    def _parse_management(self, text: str, symbol: Optional[str]) -> Optional[ParsedSignal]:
        """Parse a management/update signal"""
        text_lower = text.lower()

        # Skip if it has a clear direction keyword (it's a new trade)
        if self.DIRECTION_PATTERN.search(text) and self.ORDER_TYPE_PATTERN.search(text):
            return None

        action = None
        new_sl = None

        # Check for risk free signals
        for keyword in self.RISK_FREE_KEYWORDS:
            if keyword.lower() in text_lower or keyword in text:
                action = "risk_free"
                break

        # Check for close signals
        if not action:
            for keyword in self.CLOSE_KEYWORDS:
                if keyword in text_lower or keyword in text:
                    action = "close"
                    break

        # Check for move SL signals (with new price)
        if not action:
            for keyword in self.MOVE_SL_KEYWORDS:
                if keyword in text_lower or keyword in text:
                    action = "move_sl"
                    # Try to extract new SL price
                    numbers = re.findall(r'(\d+\.?\d+)', text)
                    if numbers:
                        new_sl = float(numbers[-1])  # Last number is typically the new SL
                    break

        # Check for TP hit notifications
        if not action:
            for keyword in self.TP_HIT_KEYWORDS:
                if keyword.lower() in text_lower:
                    action = "tp_hit"
                    # Also check if risk free is mentioned alongside
                    for rf_keyword in self.RISK_FREE_KEYWORDS:
                        if rf_keyword.lower() in text_lower or rf_keyword in text:
                            action = "risk_free"
                            break
                    break

        if not action:
            return None

        signal = ParsedSignal(
            signal_type="management",
            symbol=symbol or "UNKNOWN",
            action=action,
            new_sl=new_sl,
            raw_text=text,
        )

        logger.info(f"Parsed management signal: {action} for {symbol}")
        return signal
