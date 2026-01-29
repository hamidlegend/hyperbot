"""
Data Fetcher Module
Fetches and processes candlestick data from Hyperliquid
"""

import time
import logging
import pandas as pd
import numpy as np
from typing import Optional
import config

logger = logging.getLogger(__name__)


class DataFetcher:
    """Fetches and processes market data"""

    def __init__(self, client):
        """
        Initialize DataFetcher

        Args:
            client: HyperliquidClient instance
        """
        self.client = client

    def get_candles(
        self,
        symbol: str = None,
        interval: str = None,
        limit: int = None
    ) -> pd.DataFrame:
        """
        Get candlestick data as DataFrame

        Args:
            symbol: Trading pair (default: from config)
            interval: Candle interval (default: from config)
            limit: Number of candles to fetch (default: from config)

        Returns:
            DataFrame with columns: timestamp, open, high, low, close, volume
        """
        symbol = symbol or config.SYMBOL
        limit = limit or config.CANDLES_TO_ANALYZE

        # Convert timeframe minutes to interval string
        interval = interval or self._minutes_to_interval(config.TIMEFRAME)

        # Calculate time range
        end_time = int(time.time() * 1000)
        # Add extra candles to account for any gaps
        start_time = end_time - (limit + 50) * config.TIMEFRAME * 60 * 1000

        logger.debug(f"Fetching candles for {symbol}, interval={interval}, limit={limit}")

        # Fetch candles
        try:
            raw_candles = self.client.get_candles(
                symbol=symbol,
                interval=interval,
                start_time=start_time,
                end_time=end_time
            )
        except Exception as e:
            logger.error(f"Error fetching candles: {e}")
            return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

        # Log what we got
        if raw_candles is None:
            logger.warning("API returned None for candles")
            return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

        logger.debug(f"Raw candles type: {type(raw_candles)}, length: {len(raw_candles) if raw_candles else 0}")

        if isinstance(raw_candles, dict):
            # API might return error as dict
            logger.warning(f"API returned dict instead of list: {raw_candles}")
            return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

        if raw_candles and len(raw_candles) > 0:
            logger.debug(f"First candle sample: {raw_candles[0]}")

        # Convert to DataFrame
        df = self._process_candles(raw_candles)

        logger.info(f"Processed {len(df)} candles for {symbol}")

        # Return last 'limit' candles
        return df.tail(limit).reset_index(drop=True)

    def _process_candles(self, raw_candles: list) -> pd.DataFrame:
        """
        Process raw candle data into DataFrame

        Args:
            raw_candles: Raw candle data from API

        Returns:
            Processed DataFrame
        """
        if not raw_candles:
            return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

        # Detect response format and process accordingly
        first_item = raw_candles[0]

        if isinstance(first_item, dict):
            # Hyperliquid returns objects with 't', 'o', 'h', 'l', 'c', 'v' fields
            # or 'T', 'o', 'h', 'l', 'c', 'v' (check both cases)
            processed = []
            for candle in raw_candles:
                # Handle different key formats
                timestamp = candle.get('t') or candle.get('T') or candle.get('timestamp')
                open_price = candle.get('o') or candle.get('open')
                high_price = candle.get('h') or candle.get('high')
                low_price = candle.get('l') or candle.get('low')
                close_price = candle.get('c') or candle.get('close')
                volume = candle.get('v') or candle.get('volume') or candle.get('vlm') or 0

                if timestamp is not None:
                    processed.append({
                        'timestamp': timestamp,
                        'open': float(open_price) if open_price else 0,
                        'high': float(high_price) if high_price else 0,
                        'low': float(low_price) if low_price else 0,
                        'close': float(close_price) if close_price else 0,
                        'volume': float(volume) if volume else 0
                    })

            df = pd.DataFrame(processed)
            logger.debug(f"Processed {len(df)} candles from dict format")

        elif isinstance(first_item, list):
            # Array format: [timestamp, open, high, low, close, volume]
            df = pd.DataFrame(raw_candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['open'] = df['open'].astype(float)
            df['high'] = df['high'].astype(float)
            df['low'] = df['low'].astype(float)
            df['close'] = df['close'].astype(float)
            df['volume'] = df['volume'].astype(float)
            logger.debug(f"Processed {len(df)} candles from list format")
        else:
            logger.error(f"Unknown candle format: {type(first_item)}")
            return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

        # Convert timestamp to datetime
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')

        # Sort by timestamp
        df = df.sort_values('timestamp').reset_index(drop=True)

        # Remove duplicates
        df = df.drop_duplicates(subset=['timestamp'], keep='last')

        return df

    def _minutes_to_interval(self, minutes: int) -> str:
        """Convert minutes to Hyperliquid interval string"""
        intervals = {
            1: "1m",
            5: "5m",
            15: "15m",
            60: "1h",
            240: "4h",
            1440: "1d"
        }
        return intervals.get(minutes, "5m")

    def get_current_price(self, symbol: str = None) -> float:
        """Get current mid price for symbol"""
        symbol = symbol or config.SYMBOL
        mids = self.client.get_all_mids()
        return float(mids.get(symbol, 0))

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add technical indicators to DataFrame

        Args:
            df: OHLCV DataFrame

        Returns:
            DataFrame with added indicators
        """
        df = df.copy()

        # EMA for trend filter
        df['ema'] = df['close'].ewm(span=config.EMA_PERIOD, adjust=False).mean()

        # ATR for volatility
        df['tr'] = np.maximum(
            df['high'] - df['low'],
            np.maximum(
                abs(df['high'] - df['close'].shift(1)),
                abs(df['low'] - df['close'].shift(1))
            )
        )
        df['atr'] = df['tr'].rolling(window=14).mean()

        # Higher highs and higher lows detection
        df['prev_high'] = df['high'].shift(1)
        df['prev_low'] = df['low'].shift(1)
        df['higher_high'] = df['high'] > df['prev_high']
        df['higher_low'] = df['low'] > df['prev_low']

        return df


def find_swing_highs(df: pd.DataFrame, lookback: int = None) -> list:
    """
    Find swing highs in price data

    A swing high is a candle where:
    - The high is higher than 'lookback' candles before
    - The high is higher than 'lookback' candles after

    Args:
        df: OHLCV DataFrame
        lookback: Number of candles to check on each side

    Returns:
        List of tuples: (index, price, timestamp)
    """
    lookback = lookback or config.SWING_LOOKBACK
    swing_highs = []

    for i in range(lookback, len(df) - lookback):
        is_swing_high = True
        current_high = df.iloc[i]['high']

        # Check left side
        for j in range(1, lookback + 1):
            if df.iloc[i - j]['high'] >= current_high:
                is_swing_high = False
                break

        # Check right side
        if is_swing_high:
            for j in range(1, lookback + 1):
                if df.iloc[i + j]['high'] >= current_high:
                    is_swing_high = False
                    break

        if is_swing_high:
            swing_highs.append({
                'index': i,
                'price': current_high,
                'timestamp': df.iloc[i]['timestamp']
            })

    return swing_highs


def find_swing_lows(df: pd.DataFrame, lookback: int = None) -> list:
    """
    Find swing lows in price data

    Args:
        df: OHLCV DataFrame
        lookback: Number of candles to check on each side

    Returns:
        List of tuples: (index, price, timestamp)
    """
    lookback = lookback or config.SWING_LOOKBACK
    swing_lows = []

    for i in range(lookback, len(df) - lookback):
        is_swing_low = True
        current_low = df.iloc[i]['low']

        # Check left side
        for j in range(1, lookback + 1):
            if df.iloc[i - j]['low'] <= current_low:
                is_swing_low = False
                break

        # Check right side
        if is_swing_low:
            for j in range(1, lookback + 1):
                if df.iloc[i + j]['low'] <= current_low:
                    is_swing_low = False
                    break

        if is_swing_low:
            swing_lows.append({
                'index': i,
                'price': current_low,
                'timestamp': df.iloc[i]['timestamp']
            })

    return swing_lows


def get_recent_swing_low(df: pd.DataFrame, from_index: int, lookback: int = 20) -> Optional[dict]:
    """
    Get the most recent swing low before a given index

    Args:
        df: OHLCV DataFrame
        from_index: Index to search back from
        lookback: How far back to search

    Returns:
        Swing low dict or None
    """
    search_start = max(0, from_index - lookback)
    search_df = df.iloc[search_start:from_index + 1].copy()
    search_df = search_df.reset_index(drop=True)

    swing_lows = find_swing_lows(search_df, lookback=2)

    if swing_lows:
        # Return the most recent (last) swing low
        last_swing = swing_lows[-1]
        # Adjust index back to original DataFrame
        last_swing['original_index'] = search_start + last_swing['index']
        return last_swing

    # If no swing low found, return the lowest low in the range
    min_idx = search_df['low'].idxmin()
    return {
        'index': min_idx,
        'original_index': search_start + min_idx,
        'price': search_df.iloc[min_idx]['low'],
        'timestamp': search_df.iloc[min_idx]['timestamp']
    }
