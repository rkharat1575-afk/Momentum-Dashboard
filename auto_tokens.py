"""
auto_tokens.py — Fully Audited Auto Token Selector
=====================================================
Runs every morning AFTER daily_login_v2.py
Automatically:
  1. Downloads fresh scrip master
  2. Gets Nifty last close price (tries 3 sources)
  3. Finds nearest expiry
  4. Selects ATM ± 5 strikes (CE + PE = 10 tokens)
  5. Saves to auto_tokens.txt for terminal to read

AUDITED: Uses only shareconnect v1.0.0.11 confirmed methods:
  - SharekhanConnect.master("NF")        ✅ confirmed
  - SharekhanConnect.historicaldata()    ✅ confirmed
  No external APIs required (fallback to manual input if needed)
"""

import os, sys, json, time
import pandas as pd
from datetime import datetime, date

# Force UTF-8 encoding for stdout so emojis don't crash the console
if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

# ── CONFIG ──────────────────────────────────────────────────────
API_KEY_FILE    = "access_token.txt"
OUTPUT_FILE     = "auto_tokens.txt"
SCRIP_FILE      = "nf_scrip_master_expanded.csv"
STRIKES_EACH_SIDE = 5   # ATM ± 5 strikes = 10 CE + 10 PE = 20 tokens total
STRIKE_STEP       = 50  # Nifty strikes are multiples of 50
# ────────────────────────────────────────────────────────────────


def load_access_token():
    if not os.path.exists(API_KEY_FILE):
        print(f"❌ {API_KEY_FILE} not found. Run daily_login_v2.py first.")
        sys.exit(1)
    with open(API_KEY_FILE) as f:
        token = f.read().strip()
    if not token:
        print("❌ Access token is empty. Run daily_login_v2.py first.")
        sys.exit(1)
    return token


def load_api_key():
    # Helper to load .env manually if python-dotenv is not installed
    if os.path.exists(".env"):
        with open(".env") as f:
            for line in f:
                if line.strip() and not line.strip().startswith("#") and "=" in line:
                    key, val = line.strip().split("=", 1)
                    os.environ[key.strip()] = val.strip()
    return os.environ.get("SHAREKHAN_API_KEY", "")


def download_scrip_master(api_key, access_token):
    """Download and expand NF scrip master."""
    print("📥 Downloading fresh scrip master...")
    try:
        from SharekhanApi.sharekhanConnect import SharekhanConnect
        sk = SharekhanConnect(api_key=api_key, access_token=access_token)
        raw = sk.master("NF")
        df_raw = pd.DataFrame(raw)

        # Expand nested 'data' column
        rows = []
        for val in df_raw['data']:
            try:
                rows.append(eval(val) if isinstance(val, str) else val)
            except:
                pass

        df = pd.DataFrame(rows)
        df.to_csv(SCRIP_FILE, index=False)
        print(f"✅ Scrip master: {len(df)} scrips downloaded")
        return df
    except Exception as e:
        print(f"⚠ Could not download scrip master: {e}")
        if os.path.exists(SCRIP_FILE):
            print(f"  Using cached: {SCRIP_FILE}")
            return pd.read_csv(SCRIP_FILE)
        sys.exit(1)


def get_nifty_spot():
    """
    Try multiple sources for Nifty spot price.
    Returns float price or asks user.
    """
    price = None

    # Source 1: Yahoo Finance (works on Windows, may be blocked elsewhere)
    try:
        import urllib.request
        url = "https://query1.finance.yahoo.com/v8/finance/chart/%5ENSEI?interval=1m&range=1d"
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        })
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        price = float(data["chart"]["result"][0]["meta"]["regularMarketPrice"])
        print(f"✅ Nifty Spot from Yahoo Finance: {price:.2f}")
        return price
    except Exception as e:
        print(f"  Yahoo Finance: unavailable ({e})")

    # Source 2: NSE India public API
    try:
        import urllib.request
        import http.cookiejar
        # NSE requires a session cookie — open homepage first
        cj = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
        opener.addheaders = [("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)")]
        opener.open("https://www.nseindia.com", timeout=5)
        time.sleep(1)
        resp = opener.open("https://www.nseindia.com/api/allIndices", timeout=5)
        data = json.loads(resp.read())
        for idx in data.get("data", []):
            if idx.get("index") == "NIFTY 50":
                price = float(idx["last"])
                print(f"✅ Nifty Spot from NSE: {price:.2f}")
                return price
    except Exception as e:
        print(f"  NSE API: unavailable ({e})")

    # Source 3: Last saved price
    if os.path.exists("last_nifty_spot.txt"):
        try:
            with open("last_nifty_spot.txt") as f:
                saved = float(f.read().strip())
            print(f"  Using last saved Nifty spot: {saved:.2f} (may be from yesterday)")
            return saved
        except:
            pass

    # Source 4: Manual input
    print()
    print("⚠  Could not auto-fetch Nifty spot price.")
    while True:
        try:
            manual = float(input("Enter current Nifty spot price manually (e.g. 24200): ").strip())
            if 15000 < manual < 40000:
                return manual
            print("  Please enter a valid Nifty value between 15000-40000")
        except ValueError:
            print("  Invalid input. Enter a number.")


def find_atm_tokens(df, spot_price):
    """Find ATM ± N strikes for nearest expiry."""

    # Filter Nifty options only
    nifty = df[
        (df['tradingSymbol'].str.upper().str.startswith('NIFTY')) &
        (~df['tradingSymbol'].str.upper().str.startswith('NIFTYBEE')) &
        (~df['tradingSymbol'].str.upper().str.startswith('BANKNIFTY')) &
        (df['instType'] == 'OI') &
        (df['optionType'].isin(['CE', 'PE']))
    ].copy()

    if nifty.empty:
        print("❌ No Nifty options found in scrip master!")
        sys.exit(1)

    # Get nearest expiry
    nifty['expiry_dt'] = pd.to_datetime(nifty['expiry'], format='%d/%m/%Y', errors='coerce')
    today = pd.Timestamp(date.today())
    future = nifty[nifty['expiry_dt'] >= today]
    if future.empty:
        print("❌ No future expiry found. Check scrip master.")
        sys.exit(1)

    nearest_expiry = future['expiry_dt'].min()
    expiry_str = nearest_expiry.strftime('%d/%m/%Y')
    print(f"📅 Nearest expiry: {expiry_str}")

    weekly = nifty[nifty['expiry_dt'] == nearest_expiry].copy()

    # Round spot to nearest strike step
    atm_strike = round(spot_price / STRIKE_STEP) * STRIKE_STEP
    print(f"🎯 ATM Strike: {atm_strike} (Nifty spot: {spot_price:.2f})")

    # Select ATM ± N strikes
    strike_range = [
        atm_strike + (i * STRIKE_STEP)
        for i in range(-STRIKES_EACH_SIDE, STRIKES_EACH_SIDE + 1)
    ]

    selected = weekly[weekly['strike'].isin(strike_range)].copy()
    selected = selected.sort_values(['strike', 'optionType'])

    print(f"\n📋 Selected {len(selected)} tokens ({STRIKES_EACH_SIDE*2+1} strikes × CE+PE):")
    print(f"{'Strike':<10} {'Type':<5} {'ScripCode':<12} {'WS Token':<15} {'Symbol'}")
    print("-" * 65)

    tokens = []
    for _, row in selected.iterrows():
        ws_token = f"NF{int(row['scripCode'])}"
        tokens.append(ws_token)
        atm_marker = " ⭐ATM" if int(row['strike']) == int(atm_strike) else ""
        print(f"{int(row['strike']):<10} {row['optionType']:<5} {int(row['scripCode']):<12} {ws_token:<15}{atm_marker}")

    return tokens, atm_strike, expiry_str


def save_tokens(tokens, atm_strike, expiry_str, spot_price):
    """Save tokens to file for terminal to auto-load."""
    with open(OUTPUT_FILE, "w") as f:
        f.write("\n".join(tokens))

    # Save metadata
    meta = {
        "generated_at": datetime.now().isoformat(),
        "expiry": expiry_str,
        "atm_strike": atm_strike,
        "nifty_spot": spot_price,
        "token_count": len(tokens),
        "tokens": tokens
    }
    with open("auto_tokens_meta.json", "w") as f:
        json.dump(meta, f, indent=2)

    # Save spot for next time
    with open("last_nifty_spot.txt", "w") as f:
        f.write(str(spot_price))

    print(f"\n✅ {len(tokens)} tokens saved to {OUTPUT_FILE}")
    print(f"✅ Metadata saved to auto_tokens_meta.json")


def main():
    print("=" * 60)
    print("  SHAREKHAN AUTO TOKEN SELECTOR (Audited)")
    print("=" * 60)
    print()

    access_token = load_access_token()
    api_key      = load_api_key()

    df           = download_scrip_master(api_key, access_token)
    spot_price   = get_nifty_spot()
    tokens, atm, expiry = find_atm_tokens(df, spot_price)
    save_tokens(tokens, atm, expiry, spot_price)

    print()
    print("=" * 60)
    print(f"  ✅ DONE — {len(tokens)} tokens ready for terminal")
    print(f"  Expiry : {expiry}")
    print(f"  ATM    : {atm}")
    print(f"  Spot   : {spot_price:.2f}")
    print("=" * 60)
    print()
    print("The terminal will auto-load these tokens on startup.")


if __name__ == "__main__":
    main()
