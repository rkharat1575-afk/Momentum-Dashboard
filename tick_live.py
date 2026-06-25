"""
tick_live.py v5 — AUTO-RECONNECT + NIFTY FUTURES
Keep this running in a separate CMD window all day.
"""
import json, time, os, threading
from SharekhanApi.sharekhanWebsocket import SharekhanWebSocket

with open("access_token.txt", encoding="utf-8") as f:
    access_token = f.read().strip()

# Helper to load .env manually if python-dotenv is not installed
if os.path.exists(".env"):
    with open(".env") as f:
        for line in f:
            if line.strip() and not line.strip().startswith("#") and "=" in line:
                key, val = line.strip().split("=", 1)
                os.environ[key.strip()] = val.strip()

api_key = os.environ.get("SHAREKHAN_API_KEY", "")

if os.path.exists("auto_tokens.txt"):
    with open("auto_tokens.txt") as f:
        token_list = [t.strip() for t in f.read().splitlines() if t.strip()]
else:
    token_list = []

import pandas as pd
from datetime import datetime

def get_nifty_futures_token():
    try:
        df = pd.read_csv("nf_scrip_master_expanded.csv")
        futures = df[
            (df['tradingSymbol'].str.upper().str.startswith('NIFTY')) &
            (~df['tradingSymbol'].str.upper().str.startswith('BANKNIFTY')) &
            (df['instType'] == 'FI')
        ].copy()
        futures['expiry_dt'] = pd.to_datetime(futures['expiry'], dayfirst=True, errors='coerce')
        # Only keep tokens that haven't expired yet
        futures = futures[futures['expiry_dt'].dt.date >= datetime.now().date()]
        futures = futures.sort_values('expiry_dt')
        if not futures.empty:
            return f"NF{int(futures.iloc[0]['scripCode'])}"
    except Exception as e:
        print("Error finding futures token:", e)
    return "NF62329"

FUTURES_TOKEN = get_nifty_futures_token()
VIX_TOKEN     = "NC26023"   # India VIX

# Always include Futures + VIX tokens
SPOT_TOKEN = "NC20000"
for special in [FUTURES_TOKEN, VIX_TOKEN, SPOT_TOKEN]:
    if special not in token_list:
        token_list.insert(0, special)

tokens     = ",".join(token_list)
tick_store = {}
tick_count = 0

def save_ticks():
    try:
        with open("live_ticks.json", "w") as f:
            json.dump(tick_store, f)
        with open("WS_CONNECTED.txt", "w") as f:
            f.write("1")
    except Exception as e:
        print(f"Save error: {e}")

def connect_and_run():
    global tick_count
    sws = SharekhanWebSocket(access_token)
    sws.root = (f"wss://stream.sharekhan.com/skstream/api/stream"
                f"?ACCESS_TOKEN={access_token}&API_KEY={api_key}")

    subscribe_msg = {"action": "subscribe", "key": ["feed", "ack"], "value": [""]}
    full_feed_msg = {"action": "feed", "key": ["full"], "value": [tokens]}

    def periodic_refresh():
        while True:
            time.sleep(30)
            try:
                sws.fetchData(full_feed_msg)
                print(f"  [refresh] {time.strftime('%H:%M:%S')}")
            except: break

    def on_open(wsapp):
        print(f"CONNECTED at {time.strftime('%H:%M:%S')}")
        save_ticks()
        sws.subscribe(subscribe_msg)
        sws.fetchData(full_feed_msg)
        threading.Thread(target=periodic_refresh, daemon=True).start()

    def on_data(wsapp, message):
        global tick_count
        if not message or message in ("heartbeat","pong","ping"):
            return
        if isinstance(message, bytes):
            return
        try:
            data = json.loads(message) if isinstance(message, str) else message
            if not isinstance(data, dict): return
            if data.get("message") == "feed":
                inner = data.get("data", [])
                if isinstance(inner, list):
                    for tick in inner:
                        if isinstance(tick, dict) and "scripCode" in tick:
                            key = f"{tick.get('exchangeCode','NF')}{int(tick['scripCode'])}"
                            tick["_ts"] = time.strftime("%H:%M:%S")
                            tick_store[key] = tick
                            tick_count += 1
                            label = " FUT" if key==FUTURES_TOKEN else " VIX" if key==VIX_TOKEN else " SPOT" if key==SPOT_TOKEN else ""
                            print(f"TICK {tick_count:05d} | {key}{label} | LTP:{tick.get('ltp',0)}")
                    save_ticks()
        except Exception as e:
            print(f"Parse error: {e}")

    def on_error(wsapp, error):
        print(f"Error: {error}")

    def on_close(wsapp):
        print("Connection closed")
        with open("WS_CONNECTED.txt","w") as f:
            f.write("0")

    sws.on_open  = on_open
    sws.on_data  = on_data
    sws.on_error = on_error
    sws.on_close = on_close
    sws.connect()

print("=" * 55)
print("  TICK FEEDER v5 — WITH NIFTY FUTURES")
print(f"  Futures : {FUTURES_TOKEN}")
print(f"  Options : {len(token_list)-1} tokens")
print(f"  Refresh : every 30 seconds")
print("=" * 55)

attempt = 0
while True:
    attempt += 1
    print(f"\nConnection attempt #{attempt}...")
    try:
        connect_and_run()
    except Exception as e:
        print(f"Error: {e}")
    print("Reconnecting in 5 seconds...")
    time.sleep(5)
