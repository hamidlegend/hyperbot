"""
Configuration for HYPE Trendline Breakout Trading Bot
"""

# =============================================================================
# TRADING PARAMETERS
# =============================================================================

# Symbol to trade
SYMBOL = "HYPE"

# Timeframe in minutes
TIMEFRAME = 5

# Direction: "long" only for now
DIRECTION = "long"

# =============================================================================
# TRENDLINE PARAMETERS
# =============================================================================

# Minimum number of swing highs to form trendline
MIN_SWING_HIGHS = 2

# Maximum number of swing highs to form trendline
MAX_SWING_HIGHS = 4

# Number of candles to look back for swing high detection
SWING_LOOKBACK = 3  # A swing high has lower highs on both sides

# Number of candles to analyze for trendline
CANDLES_TO_ANALYZE = 100

# =============================================================================
# RISK MANAGEMENT
# =============================================================================

# Risk per trade (as decimal, 0.02 = 2%)
RISK_PER_TRADE = 0.02

# Leverage
LEVERAGE = 5

# Risk to Reward ratio (1:1)
RISK_REWARD_RATIO = 1.0

# =============================================================================
# FILTERS (to avoid bad trades)
# =============================================================================

# Minimum slope for trendline (too flat = invalid)
MIN_TRENDLINE_SLOPE = -0.001  # Must be negative (descending)

# Maximum slope for trendline (too steep = risky)
MAX_TRENDLINE_SLOPE = -0.1

# Minimum breakout strength (price above trendline)
MIN_BREAKOUT_PERCENT = 0.001  # 0.1%

# Check for Higher Lows (True = more conservative)
REQUIRE_HIGHER_LOWS = True

# EMA period for trend filter
EMA_PERIOD = 50

# =============================================================================
# API CONFIGURATION
# =============================================================================

# Hyperliquid API URL
API_URL = "https://api.hyperliquid.xyz"

# Testnet URL (for testing)
TESTNET_API_URL = "https://api.hyperliquid-testnet.xyz"

# Use testnet for testing (False = Mainnet)
USE_TESTNET = False

# =============================================================================
# BOT SETTINGS
# =============================================================================

# Check interval in seconds
CHECK_INTERVAL = 10

# Maximum open positions
MAX_OPEN_POSITIONS = 1

# Logging level (DEBUG for detailed output, INFO for normal operation)
LOG_LEVEL = "DEBUG"
