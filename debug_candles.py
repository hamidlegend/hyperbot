"""
Debug script - Run this on your system to see what the API returns
"""
import requests
import json
import time

API_URL = "https://api.hyperliquid.xyz"

def debug_candles():
    """Debug candle fetching"""
    print("=" * 60)
    print("DEBUG: Fetching candle data from Hyperliquid")
    print("=" * 60)

    end_time = int(time.time() * 1000)
    start_time = end_time - (150 * 5 * 60 * 1000)  # 150 5-minute candles

    # Method 1: candleSnapshot
    print("\n[Method 1] Using candleSnapshot...")
    payload1 = {
        "type": "candleSnapshot",
        "req": {
            "coin": "HYPE",
            "interval": "5m",
            "startTime": start_time,
            "endTime": end_time
        }
    }
    print(f"Request: {json.dumps(payload1, indent=2)}")

    try:
        response = requests.post(f"{API_URL}/info", json=payload1, timeout=10)
        print(f"Status: {response.status_code}")
        data = response.json()
        print(f"Response type: {type(data)}")

        if isinstance(data, list):
            print(f"Got {len(data)} candles")
            if len(data) > 0:
                print(f"First item type: {type(data[0])}")
                print(f"First item: {json.dumps(data[0], indent=2)}")
                if isinstance(data[0], dict):
                    print(f"Keys in candle: {list(data[0].keys())}")
                if len(data) > 1:
                    print(f"Last item: {json.dumps(data[-1], indent=2)}")
        elif isinstance(data, dict):
            print(f"Keys: {list(data.keys())}")
            print(f"Data: {json.dumps(data, indent=2)[:1000]}")
        else:
            print(f"Data: {data}")

        print("\n✅ Candle data looks valid!" if isinstance(data, list) and len(data) > 50 else "\n⚠️ Not enough candles returned")
    except Exception as e:
        print(f"Error: {e}")

    # Method 2: Try different request format
    print("\n[Method 2] Alternative request format...")
    payload2 = {
        "type": "candleSnapshot",
        "coin": "HYPE",
        "interval": "5m",
        "startTime": start_time,
        "endTime": end_time
    }
    print(f"Request: {json.dumps(payload2, indent=2)}")

    try:
        response = requests.post(f"{API_URL}/info", json=payload2, timeout=10)
        print(f"Status: {response.status_code}")
        data = response.json()
        print(f"Response type: {type(data)}")

        if isinstance(data, list) and len(data) > 0:
            print(f"Got {len(data)} items")
            print(f"First item: {data[0]}")
        else:
            print(f"Data: {json.dumps(data, indent=2)[:500]}")
    except Exception as e:
        print(f"Error: {e}")

    # Check if HYPE exists
    print("\n[Check] Verifying HYPE exists in exchange...")
    try:
        response = requests.post(f"{API_URL}/info", json={"type": "allMids"}, timeout=10)
        mids = response.json()

        if "HYPE" in mids:
            print(f"HYPE exists! Current price: {mids['HYPE']}")
        else:
            print("HYPE NOT FOUND in allMids!")
            print(f"Available coins (first 30): {list(mids.keys())[:30]}")

            # Maybe it's listed differently?
            hype_like = [k for k in mids.keys() if 'HYPE' in k.upper()]
            if hype_like:
                print(f"Similar names found: {hype_like}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    debug_candles()
