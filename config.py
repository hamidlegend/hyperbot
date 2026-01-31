"""
Configuration for HYPE Trendline Breakout Trading Bot
"""

# =============================================================================
# TRADING PARAMETERS
# =============================================================================

# Symbol to trade
SYMBOL = "HYPE"

# Timeframes to monitor (in minutes)
# Bot will check all timeframes for setups
TIMEFRAMES = [1, 5]  # 1-minute and 5-minute

# Legacy single timeframe (for backward compatibility)
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
# Lower = more sensitive (finds more swings), Higher = stricter
SWING_LOOKBACK = 2  # A swing high has lower highs on both sides

# Number of candles to analyze for trendline
CANDLES_TO_ANALYZE = 150

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

# Minimum slope for trendline (normalized by price)
# Too flat slopes are rejected - this is the shallowest allowed
# With HYPE ~33, -0.0003 means ~0.01 price drop per candle
MIN_TRENDLINE_SLOPE = -0.0003  # Shallowest allowed (almost flat)

# Maximum slope for trendline (normalized by price)
# Too steep slopes are rejected - this is the steepest allowed
# With HYPE ~33, -0.03 means ~1.0 price drop per candle
MAX_TRENDLINE_SLOPE = -0.03  # Steepest allowed

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
CHECK_INTERVAL = 5

# Maximum open positions
MAX_OPEN_POSITIONS = 1

# Cooldown after closing a position (in minutes)
# Prevents immediately re-entering after TP/SL hit
TRADE_COOLDOWN_MINUTES = 5

# Logging level (DEBUG for detailed output, INFO for normal operation)
LOG_LEVEL = "DEBUG"
