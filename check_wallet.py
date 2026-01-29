"""
Check which wallet address is generated from your private key
"""
import os
from dotenv import load_dotenv
from eth_account import Account

load_dotenv()

def check_wallet():
    print("=" * 60)
    print("  WALLET ADDRESS CHECK")
    print("=" * 60)

    private_key = os.getenv("PRIVATE_KEY") or os.getenv("HYPERLIQUID_PRIVATE_KEY")
    wallet_address = os.getenv("WALLET_ADDRESS") or os.getenv("HYPERLIQUID_ACCOUNT_ADDRESS")

    if not private_key:
        print("\n  [X] No PRIVATE_KEY found in .env!")
        return

    # Derive address from private key
    try:
        wallet = Account.from_key(private_key)
        derived_address = wallet.address
    except Exception as e:
        print(f"\n  [X] Invalid private key: {e}")
        return

    print(f"\n  Private Key: {private_key[:6]}...{private_key[-4:]}")
    print(f"\n  Address from Private Key:")
    print(f"  → {derived_address}")

    if wallet_address:
        print(f"\n  WALLET_ADDRESS in .env:")
        print(f"  → {wallet_address}")

        if derived_address.lower() == wallet_address.lower():
            print("\n  ✅ MATCH! Private key matches wallet address.")
        else:
            print("\n  ❌ MISMATCH!")
            print("     Private key generates a DIFFERENT address!")
            print("\n  Solutions:")
            print("  1. Get the correct private key for your wallet")
            print("  2. Or remove WALLET_ADDRESS from .env and use")
            print("     the wallet that matches your private key")
    else:
        print("\n  ℹ️  No WALLET_ADDRESS in .env")
        print("     Bot will use the derived address above")

    print("\n" + "=" * 60)
    print("  Your Hyperliquid account should be at:")
    print(f"  https://app.hyperliquid.xyz/explorer/address/{derived_address}")
    print("=" * 60)

if __name__ == "__main__":
    check_wallet()
