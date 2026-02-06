"""
Trade Filters Module
Filters to ensure we only trade on trend reversals
"""

import pandas as pd
import numpy as np
from typing import Tuple
import config
from data_fetcher import find_swing_lows


class TradeFilters:
    """
    Filters to validate trade setups

    Key filter: Only trade when trend is REVERSING (Higher Lows forming)
    """

    def __init__(self, df: pd.DataFrame):
        self.df = df

    def check_all_filters(self, setup: dict) -> Tuple[bool, str]:
        """Run all filters on a trade setup"""
        filters = [
            self.filter_trend_reversal,  # Most important - Higher Lows
            self.filter_trendline_slope,
            self.filter_breakout_candle,
        ]

        for filter_func in filters:
            passed, reason = filter_func(setup)
            if not passed:
                return False, reason

        return True, "All filters passed"

    def filter_trend_reversal(self, setup: dict) -> Tuple[bool, str]:
        """
        Filter: Only trade when trend is reversing (Higher Lows forming)

        In a downtrend: Lower Lows → Don't trade
        Trend reversing: Higher Lows → Trade allowed!
        """
        # Find recent swing lows
        swing_lows = find_swing_lows(self.df, lookback=config.SWING_LOOKBACK)

        if len(swing_lows) < 2:
            return False, "Not enough swing lows to detect trend"

        # Get last 3 swing lows (or 2 if only 2 available)
        recent_lows = swing_lows[-3:] if len(swing_lows) >= 3 else swing_lows[-2:]

        # Check if forming Higher Lows
        higher_low_count = 0
        for i in range(1, len(recent_lows)):
            if recent_lows[i]['price'] > recent_lows[i-1]['price']:
                higher_low_count += 1

        # Need at least 1 Higher Low to confirm trend reversal
        if higher_low_count == 0:
            prices = [f"${sl['price']:.4f}" for sl in recent_lows]
            return False, f"Still in downtrend - no Higher Lows ({' → '.join(prices)})"

        prices = [f"${sl['price']:.4f}" for sl in recent_lows]
        return True, f"Trend reversing - Higher Lows detected ({' → '.join(prices)})"

    def filter_trendline_slope(self, setup: dict) -> Tuple[bool, str]:
        """
        Filter: Trendline slope should be within acceptable range
        Too steep = risky, Too flat = not a real trendline
        """
        trendline = setup.get('trendline')
        if trendline is None:
            return True, "No trendline to check"

        avg_price = self.df['close'].mean()
        normalized_slope = trendline.slope / avg_price

        if normalized_slope > config.MIN_TRENDLINE_SLOPE:
            return False, f"Trendline too flat (slope: {normalized_slope:.6f})"

        if normalized_slope < config.MAX_TRENDLINE_SLOPE:
            return False, f"Trendline too steep (slope: {normalized_slope:.6f})"

        return True, f"Trendline slope OK ({normalized_slope:.6f})"

    def filter_breakout_candle(self, setup: dict) -> Tuple[bool, str]:
        """
        Filter: Breakout candle should be bullish (close > open)
        """
        if setup['status'] != 'breakout':
            return True, "No breakout to check"

        last_candle = self.df.iloc[-1]

        if last_candle['close'] < last_candle['open']:
            return False, "Breakout candle is bearish"

        return True, "Breakout candle OK"


def apply_filters(df: pd.DataFrame, setup: dict) -> Tuple[bool, str]:
    """Apply all filters to a trade setup"""
    filters = TradeFilters(df)
    return filters.check_all_filters(setup)
