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
TIMEFRAMES = [1]  # 1-minute only (5-minute disabled)

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
# IMPORTANT: Too low (2) = noise, too high (5+) = misses swings
SWING_LOOKBACK = 3  # A swing high has lower highs on both sides (3 = requires 6 total candles)

# Number of candles to analyze for trendline
CANDLES_TO_ANALYZE = 150

# =============================================================================
# PATTERN QUALITY FILTERS (avoid small/noisy patterns)
# =============================================================================

# Minimum pattern width (candles between first and last swing high)
# Small patterns are noise - we want clear, visible trendlines
# For 1-minute: 30 candles = 30 minutes minimum pattern
MIN_PATTERN_CANDLES = 30

# Minimum distance between consecutive swing highs (in candles)
# If swing highs are too close together, it's noise not a real pattern
# For 1-minute: 10 candles = 10 minutes apart minimum
MIN_SWING_DISTANCE = 10

# Maximum breakout distance from trendline (as percent of price)
# If price is already too far above trendline, don't trade - missed the breakout
# 0.005 = 0.5% max distance
MAX_BREAKOUT_DISTANCE = 0.005

# Minimum price range of trendline (as percent)
# Trendline must represent meaningful price movement, not noise
# 0.003 = 0.3% minimum price drop across trendline
MIN_TRENDLINE_RANGE = 0.003

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
TRADE_COOLDOWN_MINUTES = 2

# Logging level (DEBUG for detailed output, INFO for normal operation)
LOG_LEVEL = "DEBUG"

# =============================================================================
# TELEGRAM SIGNAL BOT SETTINGS
# =============================================================================

# Telegram API credentials (get from https://my.telegram.org/apps)
TELEGRAM_API_ID = None  # Your API ID (integer)
TELEGRAM_API_HASH = None  # Your API Hash (string)
TELEGRAM_PHONE = None  # Phone number with country code (e.g. "+98912...")

# Telegram session file name (stores login state so you don't re-login every time)
TELEGRAM_SESSION_NAME = "signal_bot"

# Channel/Group IDs to monitor (numeric IDs)
# Use `python telegram_bot.py --list-channels` to find your channel IDs
TELEGRAM_CHANNEL_IDS = []  # e.g. [-1001234567890, -1009876543210]

# Channel usernames to monitor (without @)
TELEGRAM_CHANNEL_USERNAMES = []  # e.g. ["crypto_signals", "my_channel"]

# Default leverage if signal doesn't specify one
TELEGRAM_DEFAULT_LEVERAGE = 5

# Maximum allowed leverage from signals (safety cap)
TELEGRAM_MAX_LEVERAGE = 20

# Use only first TP as take profit (True) or use all TPs with split sizing (False)
TELEGRAM_USE_FIRST_TP_ONLY = True

# Auto-execute trades from signals (False = just parse and display, don't trade)
TELEGRAM_AUTO_TRADE = False

# Cooldown between trades from signals (in seconds)
TELEGRAM_TRADE_COOLDOWN = 30
