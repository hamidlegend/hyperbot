# CLAUDE.md

## Project Overview

**HYPE Trendline Breakout Trading Bot** — An automated cryptocurrency trading bot for the [Hyperliquid](https://hyperliquid.xyz) decentralized exchange. It identifies descending trendlines on swing highs, detects price breakouts above those trendlines, and executes leveraged long trades with automated risk management (stop loss / take profit).

**Language:** Python 3
**Entry point:** `python bot.py`

## Repository Structure

```
hyperbot/
├── bot.py                 # Main bot loop and orchestration (TrendlineBreakoutBot)
├── hyperliquid_client.py  # Hyperliquid DEX API client (orders, positions, market data)
├── data_fetcher.py        # Candlestick data fetching and technical indicators (EMA, ATR, swings)
├── trendline.py           # Trendline detection via linear regression, breakout scoring
├── filters.py             # Trade validation filters (slope, range, Higher Lows, breakout distance)
├── risk_manager.py        # Position sizing (RiskManager) and trade execution (PositionManager)
├── config.py              # All configurable parameters (trading, risk, filters, API, bot settings)
├── colors.py              # ANSI color utilities for console output
├── requirements.txt       # Python dependencies
├── .env.example           # Environment variable template (PRIVATE_KEY, WALLET_ADDRESS)
├── .gitignore             # Ignores .env, logs, __pycache__, IDE files
├── README.md              # Documentation (Persian/Farsi + English)
├── test_account.py        # Manual test: account connection / API access
├── test_api.py            # Manual test: API endpoint debugging
├── check_wallet.py        # Utility: verify wallet address from private key
└── debug_candles.py       # Utility: debug candlestick data fetching
```

## Architecture

### Core Trading Flow

```
bot.py:main()
  → TrendlineBreakoutBot.run()          # Main loop (CHECK_INTERVAL = 5s)
    → _tick()                           # Single iteration per timeframe
      → DataFetcher.get_candles()       # Fetch OHLCV data from Hyperliquid
      → analyze_trendline_setup()       # Detect trendlines, check for breakout
      → apply_filters()                 # Validate the setup (slope, range, Higher Lows, etc.)
      → RiskManager.create_trade_params()  # Calculate entry, SL, TP, position size
      → PositionManager.open_position() # Execute market order + place SL/TP
```

### Key Classes

| Class | File | Purpose |
|-------|------|---------|
| `TrendlineBreakoutBot` | `bot.py` | Main orchestrator — runs the trading loop, manages cooldowns, balance caching |
| `HyperliquidClient` | `hyperliquid_client.py` | Full API wrapper — market data (candles, prices, meta), trading (orders, SL/TP), EIP-712 signing |
| `DataFetcher` | `data_fetcher.py` | Fetches candles, computes EMA/ATR, detects swing highs/lows |
| `TrendlineDetector` | `trendline.py` | Linear regression trendlines, quality scoring, breakout detection |
| `TradeFilters` | `filters.py` | Validates setups: slope range, trendline range, Higher Lows, breakout distance |
| `RiskManager` | `risk_manager.py` | Position sizing based on account balance, risk %, SL distance, leverage |
| `PositionManager` | `risk_manager.py` | Opens positions, places TP/SL orders, tracks position state |

### Key Data Structures

- `Trendline` (`trendline.py`, `@dataclass`) — slope, intercept, swing points, score, breakout info
- `TradeParams` (`risk_manager.py`, `@dataclass`) — entry price, SL, TP, position size, leverage

## Configuration

All parameters are in `config.py`. Key sections:

| Section | Parameters | Example |
|---------|-----------|---------|
| Trading | `SYMBOL`, `TIMEFRAMES`, `DIRECTION` | `"HYPE"`, `[1]`, `"long"` |
| Trendline | `MIN_SWING_HIGHS`, `SWING_LOOKBACK`, `CANDLES_TO_ANALYZE` | `2`, `3`, `150` |
| Pattern Quality | `MIN_PATTERN_CANDLES`, `MIN_SWING_DISTANCE`, `MAX_BREAKOUT_DISTANCE` | `30`, `10`, `0.005` |
| Risk | `RISK_PER_TRADE`, `LEVERAGE`, `RISK_REWARD_RATIO` | `0.02`, `5`, `1.0` |
| Filters | `MIN_TRENDLINE_SLOPE`, `MAX_TRENDLINE_SLOPE`, `REQUIRE_HIGHER_LOWS` | `-0.0003`, `-0.03`, `True` |
| Bot | `CHECK_INTERVAL`, `MAX_OPEN_POSITIONS`, `TRADE_COOLDOWN_MINUTES` | `5`, `1`, `2` |
| API | `API_URL`, `TESTNET_API_URL`, `USE_TESTNET` | mainnet URL, testnet URL, `False` |

## Environment Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure credentials
cp .env.example .env
# Edit .env with your private key and wallet address

# 3. Run the bot
python bot.py
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `PRIVATE_KEY` (or `HYPERLIQUID_PRIVATE_KEY`) | Yes | Wallet private key for signing trades |
| `WALLET_ADDRESS` (or `HYPERLIQUID_ACCOUNT_ADDRESS`) | No | Wallet address (auto-derived from key if omitted) |

## Key Dependencies

- `hyperliquid-python-sdk` — Official exchange SDK
- `pandas`, `numpy` — Data manipulation and numerical computing
- `eth-account`, `eth-abi`, `eth-utils` — Ethereum signing (EIP-712)
- `requests`, `aiohttp`, `websockets` — HTTP and WebSocket clients
- `python-dotenv` — Environment variable loading
- `ta` — Technical analysis indicators (optional)

## Code Conventions

- **Docstrings:** Google-style docstrings on classes and public functions
- **Type hints:** Used throughout (`List[dict]`, `Optional[Trendline]`, etc.)
- **Dataclasses:** Used for data structures (`Trendline`, `TradeParams`)
- **Logging:** Module-level `logger = logging.getLogger(__name__)` in every file
- **Console output:** ANSI colors via `colors.py` helper functions (`success()`, `error()`, `warning()`, etc.)
- **File logging:** Plain text to `bot.log` (no colors)
- **Config:** All tunable parameters centralized in `config.py` — never hardcode trading parameters

## Security Rules

- **NEVER** commit `.env` files or private keys — `.gitignore` blocks `.env` and `.env.local`
- Private keys are masked in logs (only first 6 + last 4 characters shown)
- All trading operations use EIP-712 typed data signing
- Wallet address is verified against the private key via `eth_account.Account.from_key()`

## Testing

There is no automated test suite (no pytest, no CI). Testing is done via manual utility scripts:

- `test_account.py` — Tests account connection and API access
- `test_api.py` — Debugs API endpoints (meta, allMids, candles)
- `check_wallet.py` — Verifies wallet address derivation from private key
- `debug_candles.py` — Debugs candlestick data fetching

## Common Development Tasks

### Modifying Trading Strategy
1. Trendline detection logic is in `trendline.py` (`TrendlineDetector` class and `analyze_trendline_setup()`)
2. Trade filters are in `filters.py` (`TradeFilters` class and `apply_filters()`)
3. Tune parameters in `config.py` — do not hardcode values in the strategy modules

### Modifying Risk Management
- Position sizing logic is in `risk_manager.py` (`RiskManager.create_trade_params()`)
- Trade execution is in `risk_manager.py` (`PositionManager.open_position()`)

### Adding API Functionality
- All Hyperliquid API calls go through `hyperliquid_client.py` (`HyperliquidClient`)
- Info (read-only) API: `get_meta()`, `get_all_mids()`, `get_candles()`, `get_user_state()`
- Exchange (trading) API: `place_order()`, `place_market_order()`, `place_stop_loss()`, `place_take_profit()`

### Switching to Testnet
Set `USE_TESTNET = True` in `config.py` — the client will automatically use the testnet API URL.

## Important Warnings

- This bot trades with **real money on mainnet** by default (`USE_TESTNET = False`)
- Always test changes on testnet first before deploying to mainnet
- The bot currently only supports **long** positions (`DIRECTION = "long"`)
- Maximum 1 open position at a time (`MAX_OPEN_POSITIONS = 1`)
- There is a 2-minute cooldown between trades (`TRADE_COOLDOWN_MINUTES = 2`)
