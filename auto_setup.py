"""
auto_setup.py — FULLY AUTOMATIC
Downloads scrip master + sets tokens automatically.
No manual input needed. Run AFTER daily_login_v2.py.
"""
import os, sys, json, time, pandas as pd
from datetime import date

print("=" * 55)
print("  AUTO SETUP — Loading tokens automatically")
print("=" * 55)

# Step 1: Check access token
if not os.path.exists("access_token.txt"):
    print("❌ No access token. Run daily_login_v2.py first.")
    sys.exit(1)

with open("access_token.txt", encoding="utf-8") as f:
    token = f.read().strip()
print(f"✅ Token loaded: {token[:20]}...")

# Step 2: Load API key
# Helper to load .env manually if python-dotenv is not installed
if os.path.exists(".env"):
    with open(".env") as f:
        for line in f:
            if line.strip() and not line.strip().startswith("#") and "=" in line:
                key, val = line.strip().split("=", 1)
                os.environ[key.strip()] = val.strip()

api_key = os.environ.get("SHAREKHAN_API_KEY", "")

# Step 3: Download fresh scrip master
print("\nDownloading fresh scrip master...")
try:
    from SharekhanApi.sharekhanConnect import SharekhanConnect
    sk = SharekhanConnect(api_key=api_key, access_token=token)
    raw = sk.master("NF")
    df_raw = pd.DataFrame(raw)
    # Try to expand nested data column
    rows = []
    if 'data' in df_raw.columns:
        for val in df_raw['data']:
            try: rows.append(eval(str(val)))
            except: pass
    
    if rows:
        df = pd.DataFrame(rows)
    else:
        # Data might already be flat
        df = df_raw
    
    df.to_csv("nf_scrip_master_expanded.csv", index=False)
    print(f"✅ Scrip master: {len(df)} scrips")
    print(f"   Columns: {list(df.columns[:5])}")
except Exception as e:
    print(f"⚠ Could not download scrip master: {e}")
    if os.path.exists("nf_scrip_master_expanded.csv"):
        df = pd.read_csv("nf_scrip_master_expanded.csv")
        print(f"  Using cached: {len(df)} scrips")
    else:
        print("❌ No scrip master found. Exiting.")
        sys.exit(1)

# Step 4: Get Nifty Futures price from live ticks or default
futures_price = 0
import sk_utils
FUTURES_TOKEN = sk_utils.get_nifty_futures_token()
if os.path.exists("live_ticks.json"):
    try:
        with open("live_ticks.json") as f:
            ticks = json.load(f)
        futures_price = float(ticks.get(FUTURES_TOKEN, {}).get("ltp", 0))
        if futures_price > 0:
            print(f"✅ Nifty Futures from live feed: {futures_price}")
    except: pass

if futures_price == 0:
    futures_price = 23600  # fallback default
    print(f"⚠ Using default futures price: {futures_price}")
    print("  (Start tick_live.py first for accurate price)")

atm = round(futures_price / 100) * 100
print(f"✅ ATM Strike: {atm}")

# Step 5: Filter Nifty options
df['expiry_dt'] = pd.to_datetime(df['expiry'], format='%d/%m/%Y', errors='coerce')
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
print(f"\n✅ Available expiries:")
for e in expiries[:5]:
    print(f"   {e.strftime('%d/%m/%Y')}")

# Step 6: Load ATM ±10 strikes for first 4 expiries
strikes = [atm + i*100 for i in range(-10, 11)]
all_tokens = [FUTURES_TOKEN]  # Always include futures

for exp in expiries[:4]:
    exp_str = exp.strftime('%d/%m/%Y')
    weekly = nifty[nifty['expiry_dt'] == exp]
    selected = weekly[weekly['strike'].isin(strikes)]
    tokens = [f"NF{int(r['scripCode'])}" for _,r in selected.iterrows()]
    all_tokens.extend(tokens)
    print(f"   {exp_str}: {len(tokens)} option tokens")

# Remove duplicates
all_tokens = list(dict.fromkeys(all_tokens))

with open("auto_tokens.txt", "w") as f:
    f.write("\n".join(all_tokens))

print(f"\n✅ Total tokens saved: {len(all_tokens)}")
print(f"   (1 Futures + {len(all_tokens)-1} Options)")
print("\n✅ Setup complete! Starting tick feeder...")
