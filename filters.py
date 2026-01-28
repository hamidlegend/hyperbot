"""
Trade Filters Module
Filters to avoid bad trades based on analysis of losing trades
"""

import pandas as pd
import numpy as np
from typing import Tuple
import config
from data_fetcher import find_swing_lows


class TradeFilters:
    """
    Filters to validate trade setups

    Based on analysis of winning vs losing trades:
    - Losing trades: Strong downtrend, weak breakout, lower lows
    - Winning trades: Pullback in uptrend, strong breakout, higher lows
    """

    def __init__(self, df: pd.DataFrame):
        """
        Initialize filters with market data

        Args:
            df: OHLCV DataFrame with indicators
        """
        self.df = df

    def check_all_filters(self, setup: dict) -> Tuple[bool, str]:
        """
        Run all filters on a trade setup

        Args:
            setup: Trade setup dict from trendline analysis

        Returns:
            Tuple of (passed, reason)
        """
        filters = [
            self.filter_overall_trend,
            self.filter_higher_lows,
            self.filter_breakout_strength,
            self.filter_trendline_slope,
            self.filter_not_in_strong_downtrend,
            self.filter_momentum,
        ]

        for filter_func in filters:
            passed, reason = filter_func(setup)
            if not passed:
                return False, reason

        return True, "All filters passed"

    def filter_overall_trend(self, setup: dict) -> Tuple[bool, str]:
        """
        Filter: Overall trend should not be strongly bearish

        We want to trade breakouts in uptrends or sideways markets,
        not against strong downtrends.
        """
        if 'ema' not in self.df.columns:
            # Calculate EMA if not present
            self.df['ema'] = self.df['close'].ewm(
                span=config.EMA_PERIOD, adjust=False
            ).mean()

        last_close = self.df.iloc[-1]['close']
        last_ema = self.df.iloc[-1]['ema']

        # Price should not be too far below EMA
        ema_distance = (last_close - last_ema) / last_ema

        if ema_distance < -0.05:  # More than 5% below EMA
            return False, f"Price too far below EMA ({ema_distance:.2%})"

        return True, "Trend filter passed"

    def filter_higher_lows(self, setup: dict) -> Tuple[bool, str]:
        """
        Filter: Recent swing lows should be forming higher lows

        This indicates bullish structure, not bearish continuation.
        """
        if not config.REQUIRE_HIGHER_LOWS:
            return True, "Higher lows filter disabled"

        # Find recent swing lows
        swing_lows = find_swing_lows(self.df, lookback=config.SWING_LOOKBACK)

        if len(swing_lows) < 2:
            return True, "Not enough swing lows to check"

        # Check last 2-3 swing lows
        recent_lows = swing_lows[-3:] if len(swing_lows) >= 3 else swing_lows[-2:]

        # Count higher lows
        higher_low_count = 0
        for i in range(1, len(recent_lows)):
            if recent_lows[i]['price'] > recent_lows[i-1]['price']:
                higher_low_count += 1

        # At least one higher low in recent swings
        if higher_low_count == 0:
            return False, "No higher lows detected - bearish structure"

        return True, f"Higher lows detected ({higher_low_count})"

    def filter_breakout_strength(self, setup: dict) -> Tuple[bool, str]:
        """
        Filter: Breakout should be strong enough

        Weak breakouts (small candles, no momentum) often fail.
        """
        if setup['status'] != 'breakout':
            return True, "No breakout to check"

        breakout = setup['breakout']
        breakout_strength = breakout.get('breakout_strength', 0)

        # Minimum breakout strength
        if breakout_strength < config.MIN_BREAKOUT_PERCENT:
            return False, f"Breakout too weak ({breakout_strength:.2%})"

        # Check the breakout candle size
        last_candle = self.df.iloc[-1]
        candle_range = (last_candle['high'] - last_candle['low']) / last_candle['close']

        # Calculate average candle range
        avg_range = ((self.df['high'] - self.df['low']) / self.df['close']).rolling(20).mean().iloc[-1]

        # Breakout candle should not be too small
        if candle_range < avg_range * 0.5:
            return False, "Breakout candle too small"

        # Candle should be bullish (close > open)
        if last_candle['close'] < last_candle['open']:
            return False, "Breakout candle is bearish"

        return True, "Breakout strength OK"

    def filter_trendline_slope(self, setup: dict) -> Tuple[bool, str]:
        """
        Filter: Trendline slope should be within acceptable range

        Too steep = risky, price might continue down
        Too flat = might not be a real trendline
        """
        trendline = setup.get('trendline')
        if trendline is None:
            return True, "No trendline to check"

        # Normalize slope relative to price
        avg_price = self.df['close'].mean()
        normalized_slope = trendline.slope / avg_price

        # Already checked in trendline validation, but double-check
        if normalized_slope > config.MIN_TRENDLINE_SLOPE:
            return False, f"Trendline too flat (slope: {normalized_slope:.6f})"

        if normalized_slope < config.MAX_TRENDLINE_SLOPE:
            return False, f"Trendline too steep (slope: {normalized_slope:.6f})"

        return True, f"Trendline slope OK ({normalized_slope:.6f})"

    def filter_not_in_strong_downtrend(self, setup: dict) -> Tuple[bool, str]:
        """
        Filter: Not in a strong downtrend

        If price has dropped significantly recently, avoid buying.
        """
        # Check price change over last N candles
        lookback = 20
        if len(self.df) < lookback:
            return True, "Not enough data"

        price_change = (
            self.df.iloc[-1]['close'] - self.df.iloc[-lookback]['close']
        ) / self.df.iloc[-lookback]['close']

        # If price dropped more than 10% in last 20 candles, avoid
        if price_change < -0.10:
            return False, f"Strong downtrend detected ({price_change:.2%})"

        return True, "No strong downtrend"

    def filter_momentum(self, setup: dict) -> Tuple[bool, str]:
        """
        Filter: Check momentum before breakout

        The candles before breakout should show building momentum,
        not exhaustion.
        """
        # Check last 5 candles before current
        if len(self.df) < 6:
            return True, "Not enough data"

        recent_candles = self.df.iloc[-6:-1]  # Last 5 before current

        # Count bullish candles
        bullish_count = sum(
            1 for _, c in recent_candles.iterrows()
            if c['close'] > c['open']
        )

        # At least 2 bullish candles in last 5
        if bullish_count < 2:
            return False, f"Weak momentum (only {bullish_count} bullish candles)"

        # Check if recent candles are building (not all red)
        closes = recent_candles['close'].values

        # At least the last close should be higher than 3 candles ago
        if closes[-1] < closes[-3]:
            return False, "Price losing momentum"

        return True, "Momentum OK"

    def filter_volatility(self, setup: dict) -> Tuple[bool, str]:
        """
        Filter: Check volatility is reasonable

        Too low volatility = slow moves, hard to profit
        Too high volatility = risky, stop hunts
        """
        if 'atr' not in self.df.columns:
            # Calculate ATR
            self.df['tr'] = np.maximum(
                self.df['high'] - self.df['low'],
                np.maximum(
                    abs(self.df['high'] - self.df['close'].shift(1)),
                    abs(self.df['low'] - self.df['close'].shift(1))
                )
            )
            self.df['atr'] = self.df['tr'].rolling(window=14).mean()

        current_atr = self.df.iloc[-1]['atr']
        current_price = self.df.iloc[-1]['close']

        # ATR as percentage of price
        atr_percent = current_atr / current_price

        # Reasonable volatility range: 0.5% to 5%
        if atr_percent < 0.005:
            return False, f"Volatility too low ({atr_percent:.2%})"

        if atr_percent > 0.05:
            return False, f"Volatility too high ({atr_percent:.2%})"

        return True, f"Volatility OK ({atr_percent:.2%})"


def apply_filters(df: pd.DataFrame, setup: dict) -> Tuple[bool, str]:
    """
    Apply all filters to a trade setup

    Args:
        df: OHLCV DataFrame
        setup: Trade setup dict

    Returns:
        Tuple of (passed, reason)
    """
    filters = TradeFilters(df)
    return filters.check_all_filters(setup)
