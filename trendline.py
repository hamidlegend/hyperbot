"""
Dynamic Trendline Module
Handles trendline detection and breakout identification
"""

import logging
import numpy as np
import pandas as pd
from typing import Optional, List, Tuple
from dataclasses import dataclass
import config
from data_fetcher import find_swing_highs, find_swing_lows, get_recent_swing_low

logger = logging.getLogger(__name__)


@dataclass
class Trendline:
    """Represents a trendline"""
    # Points that form the trendline
    point1_index: int
    point1_price: float
    point2_index: int
    point2_price: float

    # Line equation: y = slope * x + intercept
    slope: float
    intercept: float

    # Additional info
    num_touches: int = 2
    is_valid: bool = True

    def get_price_at_index(self, index: int) -> float:
        """Get the trendline price at a given candle index"""
        return self.slope * index + self.intercept

    def get_price_at_current(self, current_index: int) -> float:
        """Get current trendline price"""
        return self.get_price_at_index(current_index)


class TrendlineDetector:
    """Detects and manages descending trendlines"""

    def __init__(self):
        self.current_trendline: Optional[Trendline] = None

    def find_descending_trendline(
        self,
        df: pd.DataFrame,
        swing_highs: List[dict]
    ) -> Optional[Trendline]:
        """
        Find a valid descending trendline from swing highs

        The trendline connects swing highs and must:
        1. Have negative slope (descending)
        2. Connect at least MIN_SWING_HIGHS points
        3. Not be too steep or too flat

        Args:
            df: OHLCV DataFrame
            swing_highs: List of swing high points

        Returns:
            Trendline object or None
        """
        logger.debug(f"Swing highs found: {len(swing_highs)}, need at least {config.MIN_SWING_HIGHS}")

        if len(swing_highs) < config.MIN_SWING_HIGHS:
            logger.debug(f"Not enough swing highs: {len(swing_highs)} < {config.MIN_SWING_HIGHS}")
            return None

        # Use the most recent swing highs (up to MAX_SWING_HIGHS)
        recent_highs = swing_highs[-config.MAX_SWING_HIGHS:]
        logger.debug(f"Using {len(recent_highs)} recent swing highs for trendline")

        # Try different combinations of swing highs
        best_trendline = None
        best_score = -float('inf')

        # Try using last 2, 3, or 4 swing highs
        for num_points in range(config.MIN_SWING_HIGHS, min(len(recent_highs), config.MAX_SWING_HIGHS) + 1):
            points = recent_highs[-num_points:]

            # Calculate trendline using linear regression
            trendline = self._calculate_trendline(points)

            if trendline is None:
                continue

            # Validate trendline
            if not self._validate_trendline(trendline, df):
                continue

            # Score the trendline
            score = self._score_trendline(trendline, points, df)

            if score > best_score:
                best_score = score
                best_trendline = trendline
                best_trendline.num_touches = num_points

        self.current_trendline = best_trendline
        return best_trendline

    def _calculate_trendline(self, points: List[dict]) -> Optional[Trendline]:
        """
        Calculate trendline from points using linear regression

        Args:
            points: List of swing high points

        Returns:
            Trendline object or None
        """
        if len(points) < 2:
            return None

        # Extract x (index) and y (price) values
        x = np.array([p['index'] for p in points])
        y = np.array([p['price'] for p in points])

        # Linear regression: y = slope * x + intercept
        # Using numpy polyfit
        try:
            slope, intercept = np.polyfit(x, y, 1)
        except Exception:
            return None

        return Trendline(
            point1_index=points[0]['index'],
            point1_price=points[0]['price'],
            point2_index=points[-1]['index'],
            point2_price=points[-1]['price'],
            slope=slope,
            intercept=intercept
        )

    def _validate_trendline(self, trendline: Trendline, df: pd.DataFrame) -> bool:
        """
        Validate that trendline meets criteria

        Args:
            trendline: Trendline to validate
            df: OHLCV DataFrame

        Returns:
            True if valid
        """
        # Must be descending (negative slope)
        if trendline.slope >= 0:
            logger.debug(f"Rejected: slope is not descending ({trendline.slope:.6f})")
            return False

        # Slope must be within acceptable range
        # Normalize slope relative to price
        avg_price = df['close'].mean()
        normalized_slope = trendline.slope / avg_price

        logger.debug(f"Trendline slope: {trendline.slope:.6f}, normalized: {normalized_slope:.6f}")
        logger.debug(f"Valid range: {config.MAX_TRENDLINE_SLOPE} <= slope <= {config.MIN_TRENDLINE_SLOPE}")

        if normalized_slope > config.MIN_TRENDLINE_SLOPE:  # Too flat
            logger.debug(f"Rejected: too flat ({normalized_slope:.6f} > {config.MIN_TRENDLINE_SLOPE})")
            return False

        if normalized_slope < config.MAX_TRENDLINE_SLOPE:  # Too steep
            logger.debug(f"Rejected: too steep ({normalized_slope:.6f} < {config.MAX_TRENDLINE_SLOPE})")
            return False

        logger.debug(f"Trendline VALID: normalized slope {normalized_slope:.6f}")
        return True

    def _score_trendline(
        self,
        trendline: Trendline,
        points: List[dict],
        df: pd.DataFrame
    ) -> float:
        """
        Score a trendline based on quality

        Higher score = better trendline

        Args:
            trendline: Trendline to score
            points: Points used to create trendline
            df: OHLCV DataFrame

        Returns:
            Score value
        """
        score = 0.0

        # More touches = better
        score += len(points) * 10

        # Check how well points fit the line
        for point in points:
            expected_price = trendline.get_price_at_index(point['index'])
            actual_price = point['price']
            error = abs(expected_price - actual_price) / actual_price
            score -= error * 100  # Penalize error

        # Recent trendlines are better
        recency = points[-1]['index'] / len(df)
        score += recency * 20

        # Moderate slope is better than extreme
        avg_price = df['close'].mean()
        normalized_slope = abs(trendline.slope / avg_price)
        if 0.005 < normalized_slope < 0.05:
            score += 10

        return score

    def check_breakout(
        self,
        df: pd.DataFrame,
        trendline: Trendline = None
    ) -> Optional[dict]:
        """
        Check if price has broken above the trendline

        Args:
            df: OHLCV DataFrame
            trendline: Trendline to check (uses current if None)

        Returns:
            Breakout info dict or None
        """
        trendline = trendline or self.current_trendline

        if trendline is None:
            return None

        # Get the last few candles
        last_candle = df.iloc[-1]
        current_index = len(df) - 1

        # Calculate trendline price at current position
        trendline_price = trendline.get_price_at_index(current_index)

        # Check if close is above trendline
        close_price = last_candle['close']
        high_price = last_candle['high']

        # Breakout conditions:
        # 1. Close must be above trendline
        # 2. Must break by at least MIN_BREAKOUT_PERCENT
        breakout_threshold = trendline_price * (1 + config.MIN_BREAKOUT_PERCENT)

        if close_price > breakout_threshold:
            # Confirm breakout
            breakout_strength = (close_price - trendline_price) / trendline_price

            return {
                'is_breakout': True,
                'breakout_price': close_price,
                'trendline_price': trendline_price,
                'breakout_strength': breakout_strength,
                'candle_index': current_index,
                'timestamp': last_candle['timestamp']
            }

        return None

    def get_current_trendline_price(self, df: pd.DataFrame) -> Optional[float]:
        """Get the current trendline price at the latest candle"""
        if self.current_trendline is None:
            return None

        current_index = len(df) - 1
        return self.current_trendline.get_price_at_index(current_index)


def analyze_trendline_setup(df: pd.DataFrame) -> Optional[dict]:
    """
    Analyze DataFrame for trendline breakout setup

    This is the main function that combines all analysis

    Args:
        df: OHLCV DataFrame with at least 'high', 'low', 'close' columns

    Returns:
        Setup dict with trendline, breakout info, and trade parameters
    """
    logger.debug(f"Analyzing {len(df)} candles for trendline setup (lookback={config.SWING_LOOKBACK})")

    # Find swing highs
    swing_highs = find_swing_highs(df, lookback=config.SWING_LOOKBACK)

    logger.debug(f"Found {len(swing_highs)} swing highs")
    if swing_highs:
        for i, sh in enumerate(swing_highs[-5:]):  # Show last 5
            logger.debug(f"  Swing High #{len(swing_highs)-4+i}: index={sh['index']}, price={sh['price']:.4f}")

    if len(swing_highs) < config.MIN_SWING_HIGHS:
        logger.debug(f"Not enough swing highs for trendline: {len(swing_highs)} < {config.MIN_SWING_HIGHS}")
        return None

    # Create trendline detector
    detector = TrendlineDetector()

    # Find descending trendline
    trendline = detector.find_descending_trendline(df, swing_highs)

    if trendline is None:
        logger.debug("No valid descending trendline found")
        return None

    logger.info(f"Valid trendline found: slope={trendline.slope:.6f}, touches={trendline.num_touches}")

    # Check for breakout
    breakout = detector.check_breakout(df, trendline)

    if breakout is None:
        # No breakout yet - return monitoring info
        return {
            'status': 'monitoring',
            'trendline': trendline,
            'current_trendline_price': detector.get_current_trendline_price(df),
            'current_price': df.iloc[-1]['close'],
            'swing_highs_used': trendline.num_touches
        }

    # Breakout detected! Find stop loss level
    # SL is below the most recent swing low (the low of the breakout wave)
    breakout_index = breakout['candle_index']
    recent_swing_low = get_recent_swing_low(df, breakout_index, lookback=20)

    if recent_swing_low is None:
        return None

    # Calculate SL and TP
    entry_price = breakout['breakout_price']
    stop_loss = recent_swing_low['price']

    # Ensure SL is below entry
    if stop_loss >= entry_price:
        # Adjust SL to be slightly below entry
        stop_loss = entry_price * 0.995

    # Calculate risk
    risk = entry_price - stop_loss

    # TP based on R:R ratio
    take_profit = entry_price + (risk * config.RISK_REWARD_RATIO)

    return {
        'status': 'breakout',
        'trendline': trendline,
        'breakout': breakout,
        'entry_price': entry_price,
        'stop_loss': stop_loss,
        'take_profit': take_profit,
        'risk': risk,
        'risk_percent': risk / entry_price,
        'swing_low': recent_swing_low,
        'timestamp': breakout['timestamp']
    }
