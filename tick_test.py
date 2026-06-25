"""
tick_test.py v2 — Fixed parser for list format
CONFIRMED: Sharekhan sends data as a LIST [{...}]
Run: python tick_test.py
"""
import json
from SharekhanApi.sharekhanWebsocket import SharekhanWebSocket

with open("access_token.txt", encoding="utf-8") as f:
    access_token = f.read().strip()

# Helper to load .env manually if python-dotenv is not installed
import os
if os.path.exists(".env"):
    with open(".env") as f:
        for line in f:
            if line.strip() and not line.strip().startswith("#") and "=" in line:
                key, val = line.strip().split("=", 1)
                os.environ[key.strip()] = val.strip()

api_key = os.environ.get("SHAREKHAN_API_KEY", "")

print("=" * 60)
print("  SHAREKHAN RAW TICK TEST v2")
print("=" * 60)

sws = SharekhanWebSocket(access_token)
sws.root = f"wss://stream.sharekhan.com/skstream/api/stream?ACCESS_TOKEN={access_token}&API_KEY={api_key}"

tokens = "NF57054,NF57055,NF57058,NF57059,NF57060,NF57063,NF57064,NF57065"
subscribe_msg = {"action": "subscribe", "key": ["feed", "ack"], "value": [""]}
full_feed_msg = {"action": "feed", "key": ["full"], "value": [tokens]}
tick_count = 0

def on_open(wsapp):
    print("CONNECTED!")
    sws.subscribe(subscribe_msg)
    sws.fetchData(full_feed_msg)
    print("Subscribed. Waiting for ticks...\n")

def on_data(wsapp, message):
    global tick_count
    if message == "heartbeat" or message == "pong":
        return
    try:
        data = json.loads(message) if isinstance(message, str) else message
        msg_type = data.get("message", "")

        if msg_type == "connect":
            print(f"SESSION OK: {data.get('data','')}")
            return
        if msg_type == "subscribe":
            print(f"SUBSCRIBED: {data.get('data','')}\n")
            return

        if msg_type == "feed":
            inner = data.get("data", [])

            # CONFIRMED FORMAT: data is a LIST of tick dicts
            tick_list = inner if isinstance(inner, list) else [inner]

            for tick in tick_list:
                if not isinstance(tick, dict):
                    continue
                tick_count += 1
                scrip  = tick.get("scripCode", "?")
                exch   = tick.get("exchangeCode", "?")
                ltp    = tick.get("ltp", 0)
                oi     = tick.get("currentOI", 0)
                vol    = tick.get("qty", 0)
                bid    = tick.get("bidPrice", 0)
                ask    = tick.get("offPrice", 0)
                high   = tick.get("high", 0)
                low    = tick.get("low", 0)
                print(f"TICK {tick_count:04d} | {exch}{scrip} | LTP:{ltp} | High:{high} | Low:{low} | OI:{oi} | Vol:{vol} | Bid:{bid} | Ask:{ask}")
        else:
            print(f"MSG[{msg_type}]: {str(data)[:100]}")

    except Exception as e:
        print(f"ERR: {e} | {str(message)[:80]}")

def on_error(wsapp, error):
    print(f"ERROR: {error}")

def on_close(wsapp):
    print(f"Closed. Total ticks: {tick_count}")

sws.on_open  = on_open
sws.on_data  = on_data
sws.on_error = on_error
sws.on_close = on_close

sws.connect()
