"""
Test script to debug API connection
"""
import requests
import json
import time

# Mainnet URL
API_URL = "https://api.hyperliquid.xyz"

def test_meta():
    """Test getting exchange metadata"""
    print("Testing /info with meta...")
    response = requests.post(
        f"{API_URL}/info",
        json={"type": "meta"}
    )
    print(f"Status: {response.status_code}")
    data = response.json()

    # Find HYPE in universe
    for i, asset in enumerate(data.get("universe", [])):
        if asset.get("name") == "HYPE":
            print(f"Found HYPE at index {i}: {asset}")
            return
    print("HYPE not found in universe!")
    print(f"Available assets: {[a['name'] for a in data.get('universe', [])[:20]]}")

def test_all_mids():
    """Test getting mid prices"""
    print("\nTesting /info with allMids...")
    response = requests.post(
        f"{API_URL}/info",
        json={"type": "allMids"}
    )
    print(f"Status: {response.status_code}")
    data = response.json()

    if "HYPE" in data:
        print(f"HYPE price: {data['HYPE']}")
    else:
        print("HYPE not found in mids!")
        # Show some available
        print(f"Available: {list(data.keys())[:20]}")

def test_candles():
    """Test getting candle data"""
    print("\nTesting /info with candleSnapshot...")

    end_time = int(time.time() * 1000)
    start_time = end_time - (100 * 5 * 60 * 1000)  # 100 5-minute candles

    payload = {
        "type": "candleSnapshot",
        "req": {
            "coin": "HYPE",
            "interval": "5m",
            "startTime": start_time,
            "endTime": end_time
        }
    }

    print(f"Request: {json.dumps(payload, indent=2)}")

    response = requests.post(
        f"{API_URL}/info",
        json=payload
    )

    print(f"Status: {response.status_code}")

    try:
        data = response.json()
        print(f"Response type: {type(data)}")

        if isinstance(data, list):
            print(f"Got {len(data)} candles")
            if len(data) > 0:
                print(f"First candle: {data[0]}")
                print(f"Last candle: {data[-1]}")
        else:
            print(f"Response: {json.dumps(data, indent=2)[:500]}")
    except Exception as e:
        print(f"Error parsing response: {e}")
        print(f"Raw response: {response.text[:500]}")

if __name__ == "__main__":
    test_meta()
    test_all_mids()
    test_candles()
