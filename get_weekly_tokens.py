"""
get_weekly_tokens.py — Gets THIS WEEK's Nifty expiry tokens
Run: python get_weekly_tokens.py
"""
import pandas as pd
from datetime import date

df = pd.read_csv("nf_scrip_master_expanded.csv")

# Filter Nifty options only
nifty = df[
    (df['tradingSymbol'].str.upper().str.startswith('NIFTY')) &
    (~df['tradingSymbol'].str.upper().str.startswith('BANKNIFTY')) &
    (~df['tradingSymbol'].str.upper().str.startswith('NIFTYBEE')) &
    (df['instType'] == 'OI') &
    (df['optionType'].isin(['CE', 'PE']))
].copy()

nifty['expiry_dt'] = pd.to_datetime(nifty['expiry'], format='%d/%m/%Y', errors='coerce')
today = pd.Timestamp(date.today())

# Show ALL future expiries so user can pick
future = nifty[nifty['expiry_dt'] >= today]
expiries = sorted(future['expiry_dt'].unique())

print("Available expiries:")
for i, e in enumerate(expiries[:6]):
    print(f"  {i}: {e.strftime('%d/%m/%Y')}")

print()
choice = input("Enter number for expiry to use (0 = nearest): ").strip()
try:
    idx = int(choice)
except:
    idx = 0

chosen = expiries[idx]
print(f"\nUsing expiry: {chosen.strftime('%d/%m/%Y')}")

weekly = nifty[nifty['expiry_dt'] == chosen].copy()

# Get current Nifty spot estimate
try:
    import json
    with open("live_ticks.json") as f:
        ticks = json.load(f)
    # Average of all LTPs as rough spot estimate
    ltps = [v.get("ltp",0) for v in ticks.values() if v.get("ltp",0) > 100]
    spot = sum(ltps)/len(ltps) if ltps else 24200
    print(f"Estimated Nifty spot from live ticks: {spot:.0f}")
except:
    spot = float(input("Enter current Nifty spot price: ").strip())

# Find ATM
atm = round(spot / 50) * 50
print(f"ATM Strike: {atm}")

# Select ATM ± 5 strikes
strikes = [atm + i*50 for i in range(-5, 6)]
selected = weekly[weekly['strike'].isin(strikes)].sort_values(['strike','optionType'])

print(f"\nSelected {len(selected)} tokens:")
print(f"{'Strike':<10} {'Type':<5} {'WS Token':<12}")
print("-"*30)

tokens = []
for _, row in selected.iterrows():
    ws = f"NF{int(row['scripCode'])}"
    tokens.append(ws)
    atm_mark = " ⭐" if int(row['strike']) == int(atm) else ""
    print(f"{int(row['strike']):<10} {row['optionType']:<5} {ws}{atm_mark}")

# Save
with open("auto_tokens.txt", "w") as f:
    f.write("\n".join(tokens))

import json
meta = {"expiry": chosen.strftime('%d/%m/%Y'), "atm": atm, "spot": spot, "tokens": tokens}
with open("auto_tokens_meta.json", "w") as f:
    json.dump(meta, f, indent=2)

print(f"\n✅ Saved {len(tokens)} tokens to auto_tokens.txt")
print("Now restart tick_live.py to use new tokens.")
