"""
Trade Filters Module
Simplified filters - only reject clearly bad setups
"""

import pandas as pd
import numpy as np
from typing import Tuple
import config
from data_fetcher import find_swing_lows


class TradeFilters:
    """
    Simplified filters to validate trade setups

    Only rejects:
    - Trendlines with bad slopes (too flat/steep)
    - Bearish breakout candles
    - Extremely strong downtrends (>10% drop in 20 candles)
    """

    def __init__(self, df: pd.DataFrame):
        self.df = df

    def check_all_filters(self, setup: dict) -> Tuple[bool, str]:
        """Run all filters on a trade setup"""
        filters = [
            self.filter_trendline_slope,
            self.filter_breakout_candle,
            self.filter_not_in_strong_downtrend,
        ]

        for filter_func in filters:
            passed, reason = filter_func(setup)
            if not passed:
                return False, reason

        return True, "All filters passed"

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

    def filter_not_in_strong_downtrend(self, setup: dict) -> Tuple[bool, str]:
        """
        Filter: Not in an extreme downtrend (>10% drop)
        """
        lookback = 20
        if len(self.df) < lookback:
            return True, "Not enough data"

        price_change = (
            self.df.iloc[-1]['close'] - self.df.iloc[-lookback]['close']
        ) / self.df.iloc[-lookback]['close']

        if price_change < -0.10:
            return False, f"Strong downtrend detected ({price_change:.2%})"

        return True, "No strong downtrend"


def apply_filters(df: pd.DataFrame, setup: dict) -> Tuple[bool, str]:
    """Apply all filters to a trade setup"""
    filters = TradeFilters(df)
    return filters.check_all_filters(setup)
