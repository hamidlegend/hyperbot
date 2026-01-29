"""
Account Connection Test Script
Tests if the bot can connect to your Hyperliquid account and trade
"""
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def test_account():
    """Test account connection and trading capability"""
    print("=" * 60)
    print("HYPERLIQUID ACCOUNT CONNECTION TEST")
    print("=" * 60)

    # Step 1: Check environment variables
    print("\n[1] Checking environment variables...")

    # Try different variable names
    private_key = os.getenv("PRIVATE_KEY") or os.getenv("HYPERLIQUID_PRIVATE_KEY")
    wallet_address = os.getenv("WALLET_ADDRESS") or os.getenv("HYPERLIQUID_ACCOUNT_ADDRESS")

    if not private_key:
        print("   ERROR: Private key not found in .env file!")
        print("\n   Create a .env file with:")
        print("   PRIVATE_KEY=your_private_key_here")
        print("   (or HYPERLIQUID_PRIVATE_KEY=your_private_key_here)")
        return False
    else:
        # Show first and last 4 characters only for security
        masked_key = f"{private_key[:6]}...{private_key[-4:]}"
        print(f"   PRIVATE_KEY: {masked_key}")

    if wallet_address:
        print(f"   WALLET_ADDRESS: {wallet_address}")
    else:
        print("   WALLET_ADDRESS: Not set (will be derived from private key)")

    # Step 2: Initialize client
    print("\n[2] Initializing Hyperliquid client...")

    try:
        from hyperliquid_client import HyperliquidClient
        import config

        client = HyperliquidClient(private_key=private_key, account_address=wallet_address)
        print(f"   Client initialized successfully")
        print(f"   API URL: {config.API_URL if not config.USE_TESTNET else config.TESTNET_API_URL}")
        print(f"   Mode: {'TESTNET' if config.USE_TESTNET else 'MAINNET'}")
        print(f"   Wallet: {client.account_address}")
    except Exception as e:
        print(f"   ERROR initializing client: {e}")
        return False

    # Step 3: Test API connection (public endpoint)
    print("\n[3] Testing API connection...")

    try:
        mids = client.get_all_mids()
        if "HYPE" in mids:
            print(f"   API connected! HYPE price: ${mids['HYPE']}")
        else:
            print(f"   API connected but HYPE not found!")
            return False
    except Exception as e:
        print(f"   ERROR: API connection failed: {e}")
        return False

    # Step 4: Test account info (requires valid private key)
    print("\n[4] Testing account access...")

    try:
        user_state = client.get_user_state()

        if user_state:
            # Extract balance info
            margin_summary = user_state.get("marginSummary", {})
            account_value = margin_summary.get("accountValue", "0")
            total_margin = margin_summary.get("totalMarginUsed", "0")

            print(f"   Account connected successfully!")
            print(f"   Account Value: ${float(account_value):.2f}")
            print(f"   Margin Used: ${float(total_margin):.2f}")

            # Check positions
            positions = user_state.get("assetPositions", [])
            open_positions = [p for p in positions if float(p.get("position", {}).get("szi", 0)) != 0]

            if open_positions:
                print(f"   Open Positions: {len(open_positions)}")
                for pos in open_positions:
                    coin = pos.get("position", {}).get("coin", "?")
                    size = pos.get("position", {}).get("szi", 0)
                    entry = pos.get("position", {}).get("entryPx", 0)
                    print(f"      - {coin}: {size} @ ${entry}")
            else:
                print(f"   Open Positions: None")
        else:
            print("   ERROR: Could not retrieve user state")
            return False

    except Exception as e:
        print(f"   ERROR accessing account: {e}")
        print("   This usually means:")
        print("   1. Private key is invalid")
        print("   2. Wallet address doesn't match private key")
        print("   3. Network/API issue")
        return False

    # Step 5: Check leverage setting capability
    print("\n[5] Testing leverage setting...")

    try:
        # Try to set leverage (this confirms we can interact with the exchange)
        result = client.set_leverage("HYPE", config.LEVERAGE)
        if result:
            print(f"   Leverage set to {config.LEVERAGE}x for HYPE")
        else:
            print(f"   Note: Leverage might already be set or account has no margin")
    except Exception as e:
        print(f"   Warning: Could not set leverage: {e}")
        print("   (This is OK if you have open positions)")

    # Step 6: Summary
    print("\n" + "=" * 60)
    print("TEST RESULTS")
    print("=" * 60)
    print("   API Connection:     OK")
    print("   Account Access:     OK")
    print(f"   Trading Symbol:     HYPE")
    print(f"   Leverage:           {config.LEVERAGE}x")
    print(f"   Risk per Trade:     {config.RISK_PER_TRADE * 100}%")
    print("=" * 60)
    print("\n   Your account is ready for trading!")
    print("   Run 'python bot.py' to start the bot.")
    print("=" * 60)

    return True


def test_order_dry_run():
    """
    Simulate order creation without actually placing it
    This tests if the order building logic works
    """
    print("\n" + "=" * 60)
    print("ORDER SIMULATION (DRY RUN)")
    print("=" * 60)

    try:
        from hyperliquid_client import HyperliquidClient
        from risk_manager import RiskManager
        import config

        client = HyperliquidClient()
        risk_manager = RiskManager(client)

        # Get current price
        mids = client.get_all_mids()
        current_price = float(mids.get("HYPE", 0))

        if current_price == 0:
            print("   ERROR: Could not get HYPE price")
            return

        print(f"\n   Current HYPE Price: ${current_price:.4f}")

        # Simulate a trade setup
        # Assume stop loss is 2% below entry
        stop_loss = current_price * 0.98

        # Calculate position size
        position_size = risk_manager.calculate_position_size(
            entry_price=current_price,
            stop_loss_price=stop_loss
        )

        # Calculate take profit (1:1 R:R)
        take_profit = current_price + (current_price - stop_loss)

        print(f"\n   Simulated Trade:")
        print(f"   Entry:      ${current_price:.4f}")
        print(f"   Stop Loss:  ${stop_loss:.4f} (-2%)")
        print(f"   Take Profit: ${take_profit:.4f}")
        print(f"   Position Size: {position_size:.4f} HYPE")
        print(f"   Position Value: ${position_size * current_price:.2f}")

        # Check if we have enough balance
        user_state = client.get_user_state()
        account_value = float(user_state.get("marginSummary", {}).get("accountValue", 0))
        required_margin = (position_size * current_price) / config.LEVERAGE

        print(f"\n   Account Value: ${account_value:.2f}")
        print(f"   Required Margin: ${required_margin:.2f}")

        if account_value >= required_margin:
            print(f"\n   RESULT: Account has sufficient funds for this trade")
        else:
            print(f"\n   WARNING: Insufficient funds!")
            print(f"   Need ${required_margin:.2f} but only have ${account_value:.2f}")

    except Exception as e:
        print(f"   ERROR in dry run: {e}")


if __name__ == "__main__":
    success = test_account()

    if success:
        test_order_dry_run()
