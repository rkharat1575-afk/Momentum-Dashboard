"""
set_tokens.py — Fully automatic, no manual input needed
Reads Nifty Futures price from live_ticks.json
Selects nearest expiry + ATM±10 strikes automatically
"""
import pandas as pd, json, os
from datetime import date

df = pd.read_csv("nf_scrip_master_expanded.csv")
df['expiry_dt'] = pd.to_datetime(df['expiry'], dayfirst=True, errors='coerce')
today = pd.Timestamp(date.today())

nifty = df[
    (df['tradingSymbol'].str.upper().str.startswith('NIFTY')) &
    (~df['tradingSymbol'].str.upper().str.startswith('BANKNIFTY')) &
    (~df['tradingSymbol'].str.upper().str.startswith('NIFTYBEE')) &
    (df['instType'] == 'OI') &
    (df['optionType'].isin(['CE','PE'])) &
    (df['expiry_dt'] >= today)
].copy()

expiries = sorted(nifty['expiry_dt'].unique())

# Auto-get Nifty Futures price
spot = 0
if os.path.exists("live_ticks.json"):
    try:
        import sk_utils
        fut_tok = sk_utils.get_nifty_futures_token()
        ticks = json.load(open("live_ticks.json"))
        spot = float(ticks.get(fut_tok,{}).get("ltp",0))
        if spot == 0:
            spot = float(ticks.get("NC20000",{}).get("ltp",0))
    except: pass

if spot == 0:
    spot = float(input("Enter Nifty Futures price: ").strip())

atm = round(spot / 100) * 100
print(f"Futures: {spot} | ATM: {atm}")

# Load ATM±10 for nearest 4 expiries
strikes = [atm + i*100 for i in range(-10, 11)]
import sk_utils
tokens = [sk_utils.get_nifty_futures_token(), "NC26023", "NC20000"]  # Futures + VIX + Spot always included

for exp in expiries[:4]:
    exp_str = exp.strftime('%d/%m/%Y')
    sel = nifty[(nifty['expiry_dt']==exp) & (nifty['strike'].isin(strikes))]
    toks = [f"NF{int(r['scripCode'])}" for _,r in sel.iterrows()]
    tokens.extend(toks)
    print(f"  {exp_str}: {len(toks)} tokens")

tokens = list(dict.fromkeys(tokens))
open("auto_tokens.txt","w").write("\n".join(tokens))
print(f"✅ {len(tokens)} tokens saved. Restart tick_live.py")
