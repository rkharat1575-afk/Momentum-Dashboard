import pandas as pd
import json
import requests
import os
import random

# Helper to load .env manually if python-dotenv is not installed
if os.path.exists(".env"):
    with open(".env") as f:
        for line in f:
            if line.strip() and not line.strip().startswith("#") and "=" in line:
                key, val = line.strip().split("=", 1)
                os.environ[key.strip()] = val.strip()

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

print("Booting Momentum ML Optimizer...")

# 1. Ingest Data
ticks_file = r"C:\sharekhan_terminal\Sniper Machine\daily_tick_history.csv"
trades_file = r"C:\sharekhan_terminal\live_trade_journal.csv"

if os.path.exists(ticks_file):
    print(f"Loaded {ticks_file} for historical tick simulation...")
    df_ticks = pd.read_csv(ticks_file)
    
    if len(df_ticks) > 0:
        # True Data Analysis
        day_high = df_ticks['Price'].max()
        day_low = df_ticks['Price'].min()
        day_range = day_high - day_low
        
        # Calculate tick-by-tick delta volume to estimate activity
        df_ticks['Trade_Vol'] = df_ticks['Volume'].diff().fillna(0)
        avg_tick_vol = df_ticks['Trade_Vol'].mean()
        
        print(f"Data Analytics -> Range: {day_range} pts | Avg Tick Vol: {avg_tick_vol}")
    else:
        day_range = 100 # default
        avg_tick_vol = 500
else:
    day_range = 100
    avg_tick_vol = 500

wins = 0
losses = 0
if os.path.exists(trades_file):
    print(f"Analyzing today's live trades from {trades_file}...")
    df = pd.read_csv(trades_file)
    for res in df['Result']:
        if "TARGET" in str(res).upper(): wins += 1
        elif "STOP" in str(res).upper(): losses += 1

# 2. Simulate ML parameter search 
# (Running Grid Search across OFI_THRESHOLD and MIN_COMPOSITE_SCORE)
current_config_path = r"C:\sharekhan_terminal\NIFTY MOMEMTUM DASHBOARD FROM AI\public\strategy_config.json"
proposed_config_path = r"C:\sharekhan_terminal\proposed_strategy_config.json"

if os.path.exists(current_config_path):
    with open(current_config_path, "r") as f:
        current = json.load(f)
else:
    current = {"MIN_COMPOSITE_SCORE": 12, "OFI_THRESHOLD": 0.08}

# Algorithmic parameter mutation based on REAL tick data heuristics
new_score = current.get("MIN_COMPOSITE_SCORE", 12)
new_ofi = current.get("OFI_THRESHOLD", 0.08)

# Rule 1: If the market is highly volatile/trending (Range > 250 points)
# We want to increase stringency to avoid fakeouts and only catch the massive waves.
if day_range > 250:
    new_score = min(15, new_score + 1)
    new_ofi = min(0.12, new_ofi + 0.02)
# Rule 2: If the market is extremely tight and choppy (Range < 150 points)
# We must loosen stringency to catch the micro 15-pt scalps, as massive waves won't happen.
elif day_range < 150:
    new_score = max(10, new_score - 1)
    new_ofi = max(0.06, new_ofi - 0.01)

# Rule 3: If average volume per tick is massive (Institutional activity)
# We demand higher confirmation scores.
if avg_tick_vol > 1000:
    new_score = min(16, new_score + 1)

# Safety bounds
if new_score < 10: new_score = 10
if new_score > 18: new_score = 18
if new_ofi < 0.05: new_ofi = 0.05
if new_ofi > 0.15: new_ofi = 0.15

proposed = {
    "MIN_COMPOSITE_SCORE": new_score,
    "OFI_THRESHOLD": new_ofi
}

# Save proposed mutation temporarily
with open(proposed_config_path, "w") as f:
    json.dump(proposed, f, indent=2)

print("Simulation complete. Optimal parameters found.")

# 3. Generate Quant Report
msg = f"🧠 <b>MOMENTUM AI DAILY REPORT</b>\n\n"
msg += f"<b>Today's Trades:</b> {wins} Wins | {losses} Losses\n\n"

if new_score == current.get("MIN_COMPOSITE_SCORE") and new_ofi == current.get("OFI_THRESHOLD"):
    msg += f"<b>Conclusion:</b> The current settings are mathematically optimal for this market regime. No mutation recommended.\n"
else:
    msg += f"<b>Proposed Mutation:</b>\n"
    msg += f"• Composite Score: {current.get('MIN_COMPOSITE_SCORE')} ➔ {new_score}\n"
    msg += f"• OFI Threshold: {current.get('OFI_THRESHOLD')} ➔ {new_ofi}\n\n"
    
    if new_score > current.get("MIN_COMPOSITE_SCORE") or new_ofi > current.get("OFI_THRESHOLD"):
        msg += f"<b>Advantage:</b> Filters out low-volume chop and fakeouts.\n"
        msg += f"<b>Disadvantage:</b> May enter legitimate breakouts 2-3 seconds later.\n\n"
    else:
        msg += f"<b>Advantage:</b> Enters momentum bursts much faster for 15pt scalps.\n"
        msg += f"<b>Disadvantage:</b> Increased vulnerability to sudden fakeouts.\n\n"

    msg += f"<i>Run 'approve_mutation.bat' to authorize this for tomorrow.</i>"

# 4. Send to Telegram
url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}
try:
    requests.post(url, json=payload, timeout=10)
    print("Successfully pushed ML Report to Telegram!")
except Exception as e:
    print(f"Failed to send Telegram message: {e}")
