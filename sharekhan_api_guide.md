# Sharekhan API — Complete Setup Guide for Live Tick-by-Tick Trading Terminal
## (Nifty Options Focus — NSE F&O)

---

## PART 1 — WHAT YOU HAVE & WHAT YOU NEED

### What You Already Have
| Item | Status |
|---|---|
| Sharekhan Trading Account | ✅ |
| API Key | ✅ |
| API Secret Key (Secure Key) | ✅ |
| Python installed | Verify below |

### What You'll Install
- Python 3.8+ (if not already)
- `shareconnect` — Official Sharekhan Python library
- `websocket-client` — WebSocket support
- `streamlit` — Dashboard UI
- `pandas`, `plotly` — Data + charts

---

## PART 2 — KEY API CONCEPTS

### Authentication Flow (Every Day)
```
Step 1: Use API Key → Generate Login URL
Step 2: Open URL in browser → Log in with your Sharekhan credentials + OTP
Step 3: You are redirected to a URL containing request_token
Step 4: Use request_token + secret_key → Generate Session → Get Access Token
Step 5: Use Access Token for all REST + WebSocket calls (valid for the trading day)
```

### Exchange Codes (Critical for Nifty Options)
| Code | Meaning | Your Use |
|---|---|---|
| `NF` | NSE F&O (Futures & Options) | ✅ Nifty CE/PE options |
| `NC` | NSE Cash (Equities) | |
| `MX` | MCX Commodity | |
| `NX` | NSE Currency | |
| `BS` | BSE Cash | |

### Instrument Types (for Order Placement)
| Code | Meaning |
|---|---|
| `OI` | Option Index (Nifty, BankNifty) |
| `FI` | Future Index |
| `FS` | Future Stocks |
| `OS` | Option Stocks |
| `FUTCUR` | Future Currency |
| `OPTCUR` | Option Currency |

### Token Format for WebSocket
Tokens are formed as: `EXCHANGE_CODE + SCRIPCODE`
- Example: `NF37833` = NSE F&O exchange + scripcode 37833
- You find scripcodes by downloading the Scrip Master: `sharekhan.master("NF")`

### Option Type Codes
| Code | Meaning |
|---|---|
| `CE` | Call Option |
| `PE` | Put Option |
| `XX` | Futures (no option type) |

---

## PART 3 — STEP BY STEP LAPTOP SETUP

### Step 1 — Install Python
Download from https://python.org (3.10 or 3.11 recommended)
During install: ✅ Check "Add Python to PATH"

### Step 2 — Create Project Folder
```
C:\Users\YourName\sharekhan_terminal\
```

### Step 3 — Install Required Packages
Open Command Prompt inside that folder:
```bash
pip install shareconnect
pip install websocket-client
pip install streamlit
pip install pandas
pip install plotly
pip install requests
```

### Step 4 — Create config.py (Store Your Credentials)
```python
# config.py — DO NOT SHARE THIS FILE
API_KEY = "your_api_key_here"
SECRET_KEY = "your_secret_key_here"
STATE = 12345          # Any integer, used for CSRF protection
VERSION_ID = None      # Keep None unless Sharekhan gives you one
VENDOR_KEY = ""        # Keep blank for personal account
```

### Step 5 — Daily Login Procedure
Each market day you must refresh your access token:

```python
# daily_login.py
from SharekhanApi.sharekhanConnect import SharekhanConnect
from config import API_KEY, SECRET_KEY, STATE, VERSION_ID, VENDOR_KEY
import json

# Step 1: Get login URL
login = SharekhanConnect(API_KEY)
url = login.login_url(vendor_key=VENDOR_KEY, version_id=VERSION_ID)
print("OPEN THIS URL IN BROWSER:")
print(url)
print()

# Step 2: After login, Sharekhan redirects you to a URL like:
# https://yourredirecturl.com?request_token=XXXXXXXXXXX&state=12345
# Copy the request_token value from that URL

request_token = input("Paste the request_token from the redirect URL: ").strip()

# Step 3: Generate session and access token
session = login.generate_session_without_versionId(request_token, SECRET_KEY)
access_token = login.get_access_token(API_KEY, session, STATE)

print(f"\nACCESS TOKEN: {access_token}")

# Step 4: Save to file for the dashboard to use
with open("access_token.txt", "w") as f:
    f.write(access_token)

print("\nSaved to access_token.txt — now run the dashboard!")
```

### Step 6 — Download Nifty F&O Scrip Master
Run this once (or at start of each session) to get all scripcodes:

```python
# get_scrip_master.py
from SharekhanApi.sharekhanConnect import SharekhanConnect
from config import API_KEY
import pandas as pd

with open("access_token.txt") as f:
    access_token = f.read().strip()

sk = SharekhanConnect(API_KEY, access_token)
data = sk.master("NF")   # NF = NSE F&O

# Save to CSV for reference
df = pd.DataFrame(data)
df.to_csv("nf_scrip_master.csv", index=False)
print("Scrip master saved! Shape:", df.shape)
print(df.head())
```

Look for rows where TradingSymbol contains "NIFTY" to find Nifty option scripcodes.

### Step 7 — Run the Trading Terminal
```bash
streamlit run sharekhan_terminal.py
```

---

## PART 4 — WEBSOCKET FEED DATA FIELDS

When you subscribe to live ticks, each message contains:

| Field | Description |
|---|---|
| `LTP` | Last Traded Price |
| `LTQ` | Last Traded Quantity |
| `Volume` | Total Volume for the day |
| `Open` | Open price |
| `High` | Day's High |
| `Low` | Day's Low |
| `Close` | Previous day's Close |
| `BidPrice` | Best Bid (Buyer price) |
| `BidQty` | Bid Quantity |
| `OfferPrice` | Best Ask (Seller price) |
| `OfferQty` | Offer Quantity |
| `TotalBuyQty` | Total Buy Quantity in market |
| `TotalSellQty` | Total Sell Quantity in market |
| `OI` | Open Interest (via depth feed) |

### WebSocket Subscribe Message Format
```json
{ "action": "subscribe", "key": ["feed"], "value": [""] }
```

### WebSocket Depth (Market Depth + OI) Format
```json
{ "action": "feed", "key": ["depth"], "value": ["NF37833"] }
```

### WebSocket Unsubscribe Format
```json
{ "action": "unsubscribe", "key": ["feed"], "value": ["NF37833,NF37834"] }
```

---

## PART 5 — REST API ENDPOINTS (via shareconnect library)

| Function | Description |
|---|---|
| `sk.master("NF")` | Get full F&O scrip master (scripcodes) |
| `sk.historicaldata("NF", scripcode, "5minute")` | Historical OHLCV (last 7 days intraday) |
| `sk.holdings(customerId)` | Your holdings |
| `sk.trades(customerId)` | Current day positions |
| `sk.placeOrder(params)` | Place new order |
| `sk.modifyOrder(params)` | Modify existing order |
| `sk.cancelOrder(params)` | Cancel order |

### Historical Data Intervals Available
`1minute`, `5minute`, `10minute`, `15minute`, `30minute`, `60minute`, `daily`, `weekly`, `monthly`

---

## PART 6 — IMPORTANT NOTES FOR NIFTY OPTIONS TRADING

1. **Scrip Master is KEY**: Nifty weekly/monthly option scripcodes change every expiry. Always download fresh scrip master on expiry day.

2. **Token format**: WebSocket tokens = Exchange prefix + scripcode. For NF exchange it's `NF` + the numeric scripcode from master file.

3. **Access token expires**: The access_token is valid only for one trading session. You must run the login flow every morning before 9:15 AM.

4. **Rate limits**: Sharekhan API has rate limits on REST calls. WebSocket is preferred for real-time data — do not poll via REST for live prices.

5. **Market Depth**: Top 5 bid/ask levels are available via the depth subscription.

6. **OI data**: Open Interest is available via the depth feed, not the basic tick feed.

7. **API is FREE**: No additional charges — billed at your normal brokerage rates only for trades.

---

## PART 7 — TROUBLESHOOTING

| Error | Cause | Fix |
|---|---|---|
| `Invalid access token` | Token expired | Re-run daily_login.py |
| `WebSocket connection refused` | Token not set correctly | Check access_token.txt |
| `Scrip not found` | Wrong scripcode | Re-download scrip master |
| `request_token invalid` | Used twice | Each request_token is one-time use |
| Session generate fails | Wrong secret key | Verify in Sharekhan API portal |

---

## PART 8 — WHERE TO GET SCRIPCODES FOR NIFTY OPTIONS

After running `get_scrip_master.py`, open `nf_scrip_master.csv` and filter:
- TradingSymbol containing `NIFTY`  
- OptionType = `CE` or `PE`
- Expiry = current week's/month's expiry date

The WebSocket token will be: `NF` + that row's ScripCode number.
Example: ScripCode = `37833` → WebSocket token = `NF37833`
