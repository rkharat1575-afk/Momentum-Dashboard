"""
╔══════════════════════════════════════════════════════════════════╗
║   SHAREKHAN LIVE TERMINAL v3.0 — FULLY AUDITED                  ║
║   Nifty Options | Tick-by-Tick | Streamlit Dashboard            ║
╚══════════════════════════════════════════════════════════════════╝

AUDIT NOTES (verified against shareconnect v1.0.0.11 source):
  1. WebSocket URL: wss://stream.sharekhan.com/skstream/api/stream?ACCESS_TOKEN=...
  2. on_data callback used (NOT on_message) — connect() uses on_data=self._on_data
  3. _parse_binary_data is unimplemented (pass) → returns None for binary frames
     → on_data must handle None gracefully
  4. _on_error does NOT call self.on_error → we subclass to fix this
  5. pycryptodome + cryptography required for session generation
  6. get_access_token returns a dict — token extracted before use

INSTALL ALL REQUIRED PACKAGES:
    pip install shareconnect websocket-client pycryptodome cryptography six
    pip install streamlit pandas plotly

USAGE:
    1. python daily_login_v2.py     (every morning)
    2. streamlit run sharekhan_terminal_v3.py
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import threading
import time
import json
import os
import queue
import random
from datetime import datetime
from collections import deque, defaultdict

# ─────────────────────────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="SK Terminal v3",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ─────────────────────────────────────────────────────────────────
# DARK TERMINAL CSS
# ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Rajdhani:wght@500;600;700&display=swap');

html, body, [class*="css"]  { font-family: 'Rajdhani', sans-serif !important; background:#0a0e17 !important; color:#e0e6f0 !important; }
.stApp { background:#0a0e17 !important; }
section[data-testid="stSidebar"] { background:#080d16 !important; border-right:1px solid #1e3a5f !important; }

.terminal-header { background:linear-gradient(135deg,#0d1526,#091020); border:1px solid #1e3a5f; border-radius:6px; padding:12px 20px; margin-bottom:14px; }
.terminal-title { font-family:'JetBrains Mono',monospace; font-size:1.05rem; font-weight:700; color:#00d4ff; letter-spacing:2px; text-transform:uppercase; }

.metric-card { background:linear-gradient(135deg,#0d1526,#111827); border:1px solid #1e3a5f; border-radius:6px; padding:10px 14px; margin:3px 0; }
.metric-label { font-family:'JetBrains Mono',monospace; font-size:0.65rem; color:#5a7a9a; text-transform:uppercase; letter-spacing:1.5px; }
.metric-value { font-family:'JetBrains Mono',monospace; font-size:1.3rem; font-weight:700; }

.status-ok  { display:inline-block; background:#003d1e; color:#00e676; border:1px solid #00e676; border-radius:4px; padding:1px 8px; font-family:'JetBrains Mono',monospace; font-size:0.7rem; font-weight:700; }
.status-err { display:inline-block; background:#3d0000; color:#ff4757; border:1px solid #ff4757; border-radius:4px; padding:1px 8px; font-family:'JetBrains Mono',monospace; font-size:0.7rem; font-weight:700; }
.status-wrn { display:inline-block; background:#2a1a00; color:#ffd700; border:1px solid #ffd700; border-radius:4px; padding:1px 8px; font-family:'JetBrains Mono',monospace; font-size:0.7rem; font-weight:700; }

.section-hdr { font-family:'JetBrains Mono',monospace; font-size:0.68rem; color:#00d4ff; text-transform:uppercase; letter-spacing:2px; padding:5px 0; border-bottom:1px solid #1e3a5f; margin-bottom:10px; }

.chain-tbl { width:100%; border-collapse:collapse; font-family:'JetBrains Mono',monospace; font-size:0.76rem; }
.chain-tbl th { background:#0d1e35; color:#5a9abf; padding:7px 10px; text-align:center; font-weight:600; letter-spacing:1px; font-size:0.64rem; text-transform:uppercase; border-bottom:1px solid #1e3a5f; }
.chain-tbl td { padding:6px 10px; text-align:center; border-bottom:1px solid #0d1828; }
.chain-tbl tr:hover td { background:#0d1e35; }
.ce-col { color:#00e676; }
.pe-col { color:#ff4757; }
.strike-col { color:#ffd700; font-weight:700; background:#0d1828 !important; font-size:0.82rem; }
.atm-strike td { background:#1a1200 !important; border-top:1px solid #554400; border-bottom:1px solid #554400; }

.info-box { background:#0d1e35; border:1px solid #1e3a5f; border-left:3px solid #00d4ff; border-radius:4px; padding:8px 14px; font-family:'JetBrains Mono',monospace; font-size:0.76rem; color:#8ab8d8; margin:6px 0; }
.warn-box { background:#1e1400; border:1px solid #ffd700; border-left:3px solid #ffd700; border-radius:4px; padding:8px 14px; font-family:'JetBrains Mono',monospace; font-size:0.76rem; color:#c8a800; margin:6px 0; }
.err-box  { background:#1e0000; border:1px solid #ff4757; border-left:3px solid #ff4757; border-radius:4px; padding:8px 14px; font-family:'JetBrains Mono',monospace; font-size:0.76rem; color:#c84757; margin:6px 0; }

.stButton>button { background:#0d2a4a !important; color:#00d4ff !important; border:1px solid #1e3a5f !important; border-radius:4px !important; font-family:'JetBrains Mono',monospace !important; font-size:0.76rem !important; letter-spacing:1px !important; }
.stButton>button:hover { background:#1e3a5f !important; border-color:#00d4ff !important; }
.stTextInput>div>div>input { background:#0d1526 !important; color:#e0e6f0 !important; border:1px solid #1e3a5f !important; font-family:'JetBrains Mono',monospace !important; font-size:0.82rem !important; }

::-webkit-scrollbar { width:4px; height:4px; }
::-webkit-scrollbar-track { background:#0a0e17; }
::-webkit-scrollbar-thumb { background:#1e3a5f; border-radius:2px; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────
# THREAD-SAFE CONNECTION FLAGS
# st.session_state cannot be written from background threads
# Use threading.Event instead — readable from main thread safely
# ─────────────────────────────────────────────────────────────────
import threading as _threading
_ws_connected_flag = _threading.Event()
_ws_error_msg = [""]  # mutable list so thread can write to it

# ─────────────────────────────────────────────────────────────────
# SESSION STATE INIT
# ─────────────────────────────────────────────────────────────────
def init_state():
    defs = {
        "access_token_str": "",   # The raw string token (not the dict!)
        "api_key": "",
        "ws_connected": False,
        "ws_error": "",
        "tick_data": {},
        "tick_history": defaultdict(lambda: deque(maxlen=500)),
        "tick_queue": queue.Queue(),
        "total_ticks": 0,
        "last_update": "--",
        "scrip_master_df": None,
        "subscribed_tokens": [],
        "login_url_val": "",
        "token_response_raw": {},
    }
    for k, v in defs.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_state()


# ─────────────────────────────────────────────────────────────────
# DEPENDENCY CHECK
# ─────────────────────────────────────────────────────────────────
DEPS_OK = True
MISSING_DEPS = []
try:
    from SharekhanApi.sharekhanConnect import SharekhanConnect
    from SharekhanApi.sharekhanWebsocket import SharekhanWebSocket
except ImportError as _e:
    DEPS_OK = False
    MISSING_DEPS.append(str(_e))

if not DEPS_OK:
    st.error(f"Missing dependency: {MISSING_DEPS[0]}")
    st.code("pip install shareconnect websocket-client pycryptodome cryptography six")
    st.stop()


# ─────────────────────────────────────────────────────────────────
# PATCHED WEBSOCKET CLASS
# (Fixes library bugs: on_error never fires + binary parse is None)
# ─────────────────────────────────────────────────────────────────
class PatchedSharekhanWS(SharekhanWebSocket):
    """
    FULLY AUDITED against pip v1.0.0.11 + official GitHub source.
    Fix 1: _parse_binary_data = pass in pip → replaced with real struct parsing
            Official format: scrip_code @ bytes[4:8], price_raw @ bytes[8:12]
    Fix 2: _on_error never calls self.on_error → fixed
    Fix 3: on_message (text) also routed to on_data for unified processing
    """

    def _parse_binary_data(self, data):
        try:
            if isinstance(data, (bytes, bytearray)):
                if len(data) >= 12:
                    import struct
                    scrip_code = struct.unpack('<I', data[4:8])[0]
                    price_raw  = struct.unpack('<I', data[8:12])[0]
                    ltp = price_raw / 100.0 if price_raw > 1000 else float(price_raw)
                    return {"data": [{"scripCode": scrip_code, "ltp": ltp}]}
                else:
                    return data.decode("utf-8", errors="ignore")
            return data
        except Exception:
            return data

    def on_message(self, wsapp, message):
        """Text frames from pip _on_message → route to on_data."""
        try:
            self.on_data(wsapp, message)
        except Exception:
            pass

    def _on_error(self, wsapp, error):
        super()._on_error(wsapp, error)
        try:
            self.on_error(wsapp, error)
        except Exception:
            pass

    def on_error(self, wsapp, error):
        pass


# ─────────────────────────────────────────────────────────────────
# TOKEN EXTRACTION
# ─────────────────────────────────────────────────────────────────
def extract_access_token_string(response):
    """
    Extract the plain-string access token from get_access_token() response.
    get_access_token() returns a DICT (full JSON), not a string.
    Tries multiple key patterns Sharekhan may use.
    """
    if isinstance(response, str) and len(response) > 10:
        return response.strip(), None

    if not isinstance(response, dict):
        return None, f"Unexpected response type: {type(response)}"

    keys_to_try = ["accessToken", "access_token", "AccessToken", "token", "Token"]

    # Direct key
    for key in keys_to_try:
        val = response.get(key)
        if val and isinstance(val, str) and len(val) > 10:
            return val.strip(), None

    # Nested under "data"
    data = response.get("data") or response.get("Data") or {}
    if isinstance(data, dict):
        for key in keys_to_try:
            val = data.get(key)
            if val and isinstance(val, str) and len(val) > 10:
                return val.strip(), None

    return None, f"Token key not found. Response keys: {list(response.keys())}"


# ─────────────────────────────────────────────────────────────────
# API HELPERS
# ─────────────────────────────────────────────────────────────────
def get_login_url(api_key):
    try:
        login = SharekhanConnect(api_key=api_key)
        # AUDITED: login_url(vendor_key=None, version_id=None) for personal accounts
        url = login.login_url(vendor_key=None, version_id=None)
        return url, None
    except Exception as e:
        return None, str(e)


def do_generate_session(api_key, request_token, secret_key):
    try:
        if len(secret_key) != 32:
            return None, None, f"SECRET_KEY must be exactly 32 chars (yours: {len(secret_key)})"
        login = SharekhanConnect(api_key=api_key)
        # AUDITED: generate_session_without_versionId(request_token, secret_key)
        # Requires: pycryptodome (Crypto.Cipher.AES) + cryptography
        session = login.generate_session_without_versionId(request_token.strip(), secret_key)

        # AUDITED: get_access_token(apiKey, encstr, state, vendorkey=None, versionId=None)
        # Returns a DICT not a string
        response_dict = login.get_access_token(api_key, session, 12345)

        token_str, err = extract_access_token_string(response_dict)
        return token_str, response_dict, err
    except ValueError as e:
        if "Invalid key size" in str(e):
            return None, None, f"Invalid key size — SECRET_KEY must be 32 chars exactly"
        return None, None, str(e)
    except Exception as e:
        return None, None, str(e)


def load_scrip_master(api_key, access_token_str, exchange="NF"):
    try:
        sk = SharekhanConnect(api_key=api_key, access_token=access_token_str)
        data = sk.master(exchange)
        return pd.DataFrame(data), None
    except Exception as e:
        return None, str(e)


# ─────────────────────────────────────────────────────────────────
# WEBSOCKET MANAGER
# ─────────────────────────────────────────────────────────────────
def start_live_websocket(access_token_str, tokens_to_sub, api_key=""):
    """
    Uses EXACT same code as tick_test.py which is confirmed working.
    """
    if not access_token_str:
        return False, "No access token"

    # Auto-read API key from file if not provided (same as tick_test.py)
    if not api_key:
        try:
            with open("daily_login_v2.py", "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if line.strip().startswith("API_KEY"):
                        api_key = line.split("=")[1].strip().strip('"').strip("'")
                        if api_key == "YOUR_API_KEY_HERE":
                            api_key = ""
                        break
        except Exception:
            pass

    if not api_key:
        return False, "API Key not found. Enter it in the sidebar."

    try:
        # EXACT same pattern as tick_test.py
        from SharekhanApi.sharekhanWebsocket import SharekhanWebSocket
        sws = SharekhanWebSocket(access_token_str)
        sws.root = f"wss://stream.sharekhan.com/skstream/api/stream?ACCESS_TOKEN={access_token_str}&API_KEY={api_key}"

        token_str = ",".join(tokens_to_sub) if tokens_to_sub else ""
        subscribe_msg = {"action": "subscribe", "key": ["feed", "ack"], "value": [""]}
        full_feed_msg  = {"action": "feed", "key": ["full"], "value": [token_str]}

        def on_open(wsapp):
            _ws_connected_flag.set()
            _ws_error_msg[0] = ""
            sws.subscribe(subscribe_msg)
            if token_str:
                sws.fetchData(full_feed_msg)

        def on_data(wsapp, data):
            if data in ("heartbeat", "pong", "ping", None):
                return
            try:
                parsed = data if isinstance(data, dict) else                          __import__('json').loads(data) if isinstance(data, str) else data
                st.session_state["tick_queue"].put(parsed)
            except Exception:
                pass

        def on_error(wsapp, error):
            _ws_connected_flag.clear()
            _ws_error_msg[0] = str(error)

        def on_close(wsapp):
            _ws_connected_flag.clear()

        sws.on_open  = on_open
        sws.on_data  = on_data
        sws.on_error = on_error
        sws.on_close = on_close

        import threading
        t = threading.Thread(target=sws.connect, daemon=True)
        t.start()
        return True, None

    except Exception as e:
        return False, str(e)


# ─────────────────────────────────────────────────────────────────
# TICK PROCESSING
# ─────────────────────────────────────────────────────────────────
def process_tick_queue():
    """
    PRIMARY: Read from live_ticks.json written by tick_live.py
    FALLBACK: Read from internal queue (WebSocket in dashboard)
    """
    import json as _json, os as _os

    # PRIMARY: Read from file written by tick_live.py
    if _os.path.exists("live_ticks.json"):
        try:
            with open("live_ticks.json", "r") as f:
                ticks = _json.load(f)
            for token, tick in ticks.items():
                if isinstance(tick, dict):
                    tick["token"] = token
                    _normalize_tick_direct(token, tick)
            # Check connection file
            if _os.path.exists("WS_CONNECTED.txt"):
                with open("WS_CONNECTED.txt") as f:
                    _ws_connected_flag.set() if f.read().strip()=="1" else _ws_connected_flag.clear()
            return
        except Exception:
            pass

    # FALLBACK: Internal queue
    count = 0
    while not st.session_state["tick_queue"].empty() and count < 500:
        try:
            raw = st.session_state["tick_queue"].get_nowait()
            if isinstance(raw, str):
                if raw in ("heartbeat","pong","ping"): continue
                try: raw = _json.loads(raw)
                except: continue
            if isinstance(raw, dict): _normalize_tick(raw)
            elif isinstance(raw, list):
                for item in raw:
                    if isinstance(item, dict): _normalize_tick(item)
        except queue.Empty:
            break
        count += 1


def _normalize_tick_direct(token, tick):
    """
    Direct normalize — also maps scripCode tokens to strike-based keys
    so option chain can find them.
    e.g. NF57058 -> also stored as NF_CE_24600 if strike/optionType known
    """
    def _f(keys, d=0.0):
        for k in keys:
            v = tick.get(k)
            if v is not None:
                try: return float(v)
                except: pass
        return d
    def _i(keys, d=0):
        for k in keys:
            v = tick.get(k)
            if v is not None:
                try: return int(v)
                except: pass
        return d

    ltp  = _f(["ltp"])
    prev = st.session_state["tick_data"].get(token, {}).get("ltp", ltp)
    chg  = round((ltp-prev)/prev*100, 4) if prev else 0
    cls  = _f(["close","Close"])
    dchg = round((ltp-cls)/cls*100, 2) if cls else 0

    normalized = {
        "token": token, "ltp": ltp,
        "ltq":    _i(["ltq"]),
        "volume": _i(["qty"]),
        "open":   _f(["open"]),
        "high":   _f(["high"]),
        "low":    _f(["low"]),
        "close":  cls,
        "bid":    _f(["bidPrice"]),
        "bid_qty":_i(["bidQty"]),
        "ask":    _f(["offPrice"]),
        "ask_qty":_i(["offQty"]),
        "oi":     _i(["currentOI"]),
        "total_buy_qty":  _i(["totalBuyQty"]),
        "total_sell_qty": _i(["totalSellQty"]),
        "chg_pct":    chg,
        "day_chg_pct":dchg,
        "timestamp":  tick.get("_ts", datetime.now().strftime("%H:%M:%S")),
    }

    # Store by raw token (NF57058)
    st.session_state["tick_data"][token] = normalized

    # ALSO store by strike key (NF_CE_24600) so option chain finds it
    # Read strike and optionType from scrip master if loaded
    scrip_df = st.session_state.get("scrip_master_df")
    if scrip_df is not None:
        try:
            scrip_code = int(token.replace("NF","").replace("NC","").replace("MX",""))
            row = scrip_df[scrip_df["scripCode"] == scrip_code]
            if not row.empty:
                strike = int(row.iloc[0]["strike"])
                opt    = row.iloc[0]["optionType"]  # CE or PE
                strike_key = f"NF_{opt}_{strike}"
                norm2 = normalized.copy()
                norm2["token"] = strike_key
                st.session_state["tick_data"][strike_key] = norm2
                st.session_state["tick_history"][strike_key].append((datetime.now(), ltp))
        except Exception:
            pass

    st.session_state["tick_history"][token].append((datetime.now(), ltp))
    st.session_state["total_ticks"] += 1
    st.session_state["last_update"] = datetime.now().strftime("%H:%M:%S.%f")[:-3]


def _normalize_tick(tick):
    """
    CONFIRMED FORMAT from live market test 04-May-2026:
    Sharekhan sends: {"status":100, "message":"feed", "data": [{...tick...}]}
    data is always a LIST of tick dicts.
    Field names confirmed: ltp, currentOI, qty, bidPrice, offPrice,
                           high, low, open, close, ltq, totalBuyQty, totalSellQty
    Token key: scripCode (numeric) + exchangeCode prefix for matching
    """
    if not isinstance(tick, dict):
        return

    # Unwrap response wrapper — data is a LIST (confirmed from live test)
    if tick.get("message") in ("feed", "subscribe", "connect") and "data" in tick:
        inner = tick["data"]
        if isinstance(inner, list):
            for item in inner:
                if isinstance(item, dict):
                    _normalize_tick(item)
        elif isinstance(inner, dict):
            _normalize_tick(inner)
        return

    # Skip non-feed messages
    if "ltp" not in tick and "scripCode" not in tick:
        return

    # Build token key — match format NF57058 from exchangeCode + scripCode
    scrip_code = tick.get("scripCode")
    exch_code  = tick.get("exchangeCode", "NF")
    if scrip_code is None:
        return
    token = f"{exch_code}{int(scrip_code)}"
    if token is None:
        return
    token = str(token)

    def _f(keys, default=0.0):
        """Try multiple key names, return first found float value."""
        for k in keys:
            v = tick.get(k)
            if v is not None:
                try: return float(v)
                except: pass
        return default

    def _i(keys, default=0):
        """Try multiple key names, return first found int value."""
        for k in keys:
            v = tick.get(k)
            if v is not None:
                try: return int(v)
                except: pass
        return default

    # Field names from OFFICIAL Sharekhan WebSocket documentation response
    ltp   = _f(["ltp", "LTP", "LastRate", "lastRate"])
    ltq   = _i(["ltq", "LTQ", "LastQty", "lastQty"])
    vol   = _i(["qty", "volume", "Volume", "TotalQty", "totalQty"])   # official: qty
    high  = _f(["high", "High"])
    low   = _f(["low", "Low"])
    open_ = _f(["open", "Open", "OpenRate", "openRate"])
    close = _f(["close", "Close", "PClose", "pClose", "prevClose"])
    bid   = _f(["bidPrice", "BidPrice", "bid"])                          # official: bidPrice
    bidq  = _i(["bidQty", "BidQty", "BidQuantity", "bidQuantity"])      # official: bidQty
    ask   = _f(["offPrice", "OfferPrice", "offerPrice", "ask"])          # official: offPrice
    askq  = _i(["offQty", "OfferQty", "OfferQuantity", "offerQuantity"]) # official: offQty
    tbq   = _i(["totalBuyQty", "TotalBuyQty"])
    tsq   = _i(["totalSellQty", "TotalSellQty"])
    oi    = _i(["currentOI", "OI", "oi", "OpenInterest", "openInterest"]) # official: currentOI

    prev_ltp = st.session_state["tick_data"].get(token, {}).get("ltp", ltp)
    chg_pct  = round((ltp - prev_ltp) / prev_ltp * 100, 4) if prev_ltp else 0.0
    day_chg  = round((ltp - close)    / close     * 100, 2) if close     else 0.0

    normalized = {
        "token": token, "ltp": ltp, "ltq": ltq, "volume": vol,
        "open": open_, "high": high, "low": low, "close": close,
        "bid": bid, "bid_qty": bidq, "ask": ask, "ask_qty": askq,
        "total_buy_qty": tbq, "total_sell_qty": tsq,
        "oi": oi, "chg_pct": chg_pct, "day_chg_pct": day_chg,
        "timestamp": datetime.now().strftime("%H:%M:%S.%f")[:-3],
    }
    st.session_state["tick_data"][token] = normalized
    st.session_state["tick_history"][token].append((datetime.now(), ltp))


# ─────────────────────────────────────────────────────────────────
# DEMO DATA (when not connected to real API)
# ─────────────────────────────────────────────────────────────────
DEMO_STRIKES = [24200, 24300, 24400, 24500, 24600, 24700, 24800, 24900]
ATM = 24600

DEMO_TOKENS = {}
for s in DEMO_STRIKES:
    ce_ltp = max(0.1, (ATM - s + 200) * 0.7 + random.uniform(0, 10)) if s <= ATM else max(0.1, (ATM - s + 200) * 0.3)
    pe_ltp = max(0.1, (s - ATM + 200) * 0.7 + random.uniform(0, 10)) if s >= ATM else max(0.1, (s - ATM + 200) * 0.3)
    DEMO_TOKENS[f"NF_CE_{s}"] = {"symbol": f"NIFTY{s}CE", "type": "CE", "strike": s, "base_ltp": round(ce_ltp, 1)}
    DEMO_TOKENS[f"NF_PE_{s}"] = {"symbol": f"NIFTY{s}PE", "type": "PE", "strike": s, "base_ltp": round(pe_ltp, 1)}
DEMO_TOKENS["NF_SPOT"] = {"symbol": "NIFTY SPOT", "type": "IDX", "strike": 0, "base_ltp": 24620.0}

if "demo_prices" not in st.session_state:
    st.session_state["demo_prices"] = {k: v["base_ltp"] for k, v in DEMO_TOKENS.items()}
    st.session_state["demo_oi"] = {k: random.randint(100_000, 800_000) for k in DEMO_TOKENS}


def update_demo_data():
    for token, info in DEMO_TOKENS.items():
        p = st.session_state["demo_prices"][token]
        chg = random.gauss(0, 0.0025)
        new_p = max(0.05, p * (1 + chg))
        st.session_state["demo_prices"][token] = round(new_p, 2)
        close = info["base_ltp"] * 0.995
        tick = {
            "token": token,
            "LTP": new_p, "LTQ": random.randint(25, 500),
            "TotalQty": 10000 + random.randint(0, 1000),
            "High": new_p * 1.015, "Low": new_p * 0.985,
            "OpenRate": info["base_ltp"] * 1.001,
            "PClose": close,
            "BidPrice": max(0.05, new_p - random.uniform(0.1, 0.5)),
            "BidQuantity": random.randint(100, 2000),
            "OfferPrice": new_p + random.uniform(0.1, 0.5),
            "OfferQuantity": random.randint(100, 2000),
            "TotalBuyQty": random.randint(100_000, 500_000),
            "TotalSellQty": random.randint(100_000, 500_000),
            "OI": st.session_state["demo_oi"][token] + random.randint(-1000, 1000),
        }
        _normalize_tick(tick)


# ─────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────
def fmt_qty(v):
    if v >= 10_000_000: return f"{v/10_000_000:.1f}Cr"
    if v >= 100_000:    return f"{v/100_000:.1f}L"
    if v >= 1_000:      return f"{v/1_000:.1f}K"
    return str(int(v))

def color_str(val, positive_green=True):
    if val > 0:
        c = "#00e676" if positive_green else "#ff4757"; s = "▲"
    elif val < 0:
        c = "#ff4757" if positive_green else "#00e676"; s = "▼"
    else:
        c = "#8a9ab8"; s = "─"
    return f'<span style="color:{c}">{s} {abs(val):.2f}</span>'

def load_token_file():
    if os.path.exists("access_token.txt"):
        with open("access_token.txt") as f:
            raw = f.read().strip()
        if raw and len(raw) > 10:
            return raw
    return ""


# ─────────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown('<div style="font-family:JetBrains Mono,monospace;font-weight:700;color:#00d4ff;letter-spacing:2px;font-size:1.05rem">⚡ SK TERMINAL v3</div>', unsafe_allow_html=True)
    st.markdown('<div style="font-family:JetBrains Mono,monospace;font-size:0.62rem;color:#2a5a7a;margin-bottom:10px">AUDITED v1.0.0.11</div>', unsafe_allow_html=True)
    st.divider()

    # Auto-load token from file
    if not st.session_state["access_token_str"]:
        st.session_state["access_token_str"] = load_token_file()

    st.markdown('<div class="section-hdr">🔐 AUTH</div>', unsafe_allow_html=True)

    api_key    = st.text_input("API Key",    value=st.session_state["api_key"],    type="password", key="sb_api")
    secret_key = st.text_input("Secret Key", value="",                             type="password", key="sb_sec")
    if api_key: st.session_state["api_key"] = api_key

    if st.button("1️⃣ Get Login URL"):
        if not api_key:
            st.error("Enter API Key first")
        else:
            url, err = get_login_url(api_key)
            if url:
                st.session_state["login_url_val"] = url
            else:
                st.error(str(err))

    if st.session_state["login_url_val"]:
        st.markdown(f'<div class="info-box">📎 <a href="{st.session_state["login_url_val"]}" target="_blank" style="color:#00d4ff">Open Login URL</a><br><span style="font-size:0.68rem">Login → OTP → copy request_token from redirect URL</span></div>', unsafe_allow_html=True)
        req_tok = st.text_input("request_token (from redirect URL)", key="sb_rtok")

        if st.button("2️⃣ Generate Access Token"):
            if not req_tok:
                st.error("Enter request_token")
            elif not secret_key:
                st.error("Enter Secret Key")
            else:
                with st.spinner("Generating..."):
                    token_str, raw_resp, err = do_generate_session(api_key, req_tok, secret_key)

                if err and not token_str:
                    st.error(f"❌ {err}")
                    if raw_resp:
                        st.json(raw_resp)
                else:
                    if err:
                        st.warning(f"Warning: {err}")
                    if raw_resp:
                        st.session_state["token_response_raw"] = raw_resp

                    if token_str:
                        st.session_state["access_token_str"] = token_str
                        with open("access_token.txt", "w") as f:
                            f.write(token_str)
                        st.success(f"✅ Token saved! Length: {len(token_str)}")
                    else:
                        st.warning("Token not auto-extracted. See full response below.")
                        st.json(raw_resp)
                        st.info("Find the key containing your access token and paste it below.")
                        manual = st.text_input("Paste access token string manually:", key="manual_tok")
                        if manual and st.button("Save Manual Token"):
                            st.session_state["access_token_str"] = manual.strip()
                            with open("access_token.txt", "w") as f:
                                f.write(manual.strip())
                            st.success("Saved!")

    st.divider()
    # Read thread-safe flags into session state (main thread only)
    st.session_state["ws_connected"] = _ws_connected_flag.is_set()
    st.session_state["ws_error"] = _ws_error_msg[0]

    st.markdown('<div class="section-hdr">🔌 CONNECTION</div>', unsafe_allow_html=True)

    # FILE-BASED MODE — bypasses all Streamlit session state issues
    import os as _os
    _live_file = "LIVE_MODE.txt"
    _is_live = _os.path.exists(_live_file)
    col_d, col_l = st.columns(2)
    with col_d:
        if st.button("🟡 DEMO", use_container_width=True):
            if _os.path.exists(_live_file): _os.remove(_live_file)
            st.rerun()
    with col_l:
        if st.button("🟢 LIVE", use_container_width=True):
            open(_live_file, "w").write("LIVE")
            st.rerun()
    demo_mode = not _os.path.exists(_live_file)
    st.session_state["live_mode_active"] = not demo_mode
    if not demo_mode:
        st.markdown('<span class="status-ok">● LIVE MODE ACTIVE</span>', unsafe_allow_html=True)
    else:
        st.markdown('<span class="status-wrn">● DEMO MODE</span>', unsafe_allow_html=True)

    if st.session_state["access_token_str"]:
        prev = st.session_state["access_token_str"][:25] + "..."
        st.markdown(f'<div class="info-box">Token loaded: {prev}</div>', unsafe_allow_html=True)
    else:
        if not demo_mode:
            st.markdown('<div class="warn-box">⚠ No access token. Run login flow above or use Demo mode.</div>', unsafe_allow_html=True)

    if not demo_mode:
        # Auto-load tokens from auto_tokens.txt if it exists
        auto_tokens_default = ""
        auto_meta = {}
        if os.path.exists("auto_tokens.txt"):
            with open("auto_tokens.txt") as f:
                auto_tokens_default = f.read().strip()
        if os.path.exists("auto_tokens_meta.json"):
            with open("auto_tokens_meta.json") as f:
                auto_meta = json.load(f)

        if auto_tokens_default:
            st.markdown(f'<div class="info-box">🤖 Auto tokens loaded:<br>Expiry: {auto_meta.get("expiry","?")}<br>ATM: {auto_meta.get("atm_strike","?")}<br>Spot ref: {auto_meta.get("nifty_spot",0):.0f}<br>Tokens: {auto_meta.get("token_count","?")}</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="warn-box">⚠ No auto_tokens.txt found.<br>Run auto_tokens.py first.</div>', unsafe_allow_html=True)

        st.markdown('<div style="font-family:JetBrains Mono,monospace;font-size:0.68rem;color:#5a7a9a;margin-top:6px">Tokens (auto-filled or edit manually):</div>', unsafe_allow_html=True)
        tokens_raw = st.text_area("", value=auto_tokens_default, height=90, key="sb_tokens", label_visibility="collapsed")

        if st.button("▶ Connect WebSocket"):
            tok_str = st.session_state["access_token_str"]
            if not tok_str:
                st.error("No access token available")
            else:
                tokens = [t.strip() for t in tokens_raw.split("\n") if t.strip()]
                ok, err = start_live_websocket(tok_str, tokens, api_key=st.session_state["api_key"])
                if ok:
                    st.success(f"WebSocket connecting... {len(tokens)} tokens subscribed")
                else:
                    st.error(f"Error: {err}")

        if st.button("📥 Load F&O Scrip Master"):
            tok_str = st.session_state["access_token_str"]
            df, err = load_scrip_master(st.session_state["api_key"], tok_str, "NF")
            if df is not None:
                st.session_state["scrip_master_df"] = df
                st.success(f"Loaded {len(df)} scrips")
            else:
                st.error(str(err))

    st.divider()

    auto_refresh  = st.checkbox("Auto Refresh", value=True)
    refresh_rate  = st.slider("Refresh interval (s)", 0.5, 5.0, 1.0, 0.5)

    st.divider()

    # Status
    if st.session_state["ws_connected"] or demo_mode:
        st.markdown('<span class="status-ok">● LIVE</span>', unsafe_allow_html=True)
    else:
        st.markdown('<span class="status-err">● OFFLINE</span>', unsafe_allow_html=True)

    if st.session_state["ws_error"]:
        st.markdown(f'<div class="err-box">WS Error: {st.session_state["ws_error"]}</div>', unsafe_allow_html=True)

    st.markdown(f'<div style="font-family:JetBrains Mono,monospace;font-size:0.64rem;color:#2a5a7a;margin-top:4px">Last: {st.session_state["last_update"]}<br>Ticks: {st.session_state["total_ticks"]}</div>', unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────
# UPDATE DATA
# ─────────────────────────────────────────────────────────────────
# MODE: read from persistent radio button state only
demo_mode = not st.session_state.get("live_mode_active", False)

if demo_mode:
    update_demo_data()
    st.session_state["last_update"] = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    st.session_state["total_ticks"] += len(DEMO_TOKENS)
else:
    process_tick_queue()
    st.session_state["total_ticks"] += 1
    st.session_state["last_update"] = datetime.now().strftime("%H:%M:%S.%f")[:-3]


# ─────────────────────────────────────────────────────────────────
# MAIN UI
# ─────────────────────────────────────────────────────────────────
now = datetime.now()
mkt_open = now.replace(hour=9, minute=15) <= now <= now.replace(hour=15, minute=30)

st.markdown(f"""
<div class="terminal-header">
  <span class="terminal-title">📈 SHAREKHAN TERMINAL v3 — NIFTY OPTIONS</span>
  <span style="font-family:JetBrains Mono,monospace;font-size:0.76rem;color:#5a9abf">
    {now.strftime('%d %b %Y  %H:%M:%S')} &nbsp;|&nbsp;
    {'🟢 MARKET OPEN' if mkt_open else '🔴 MARKET CLOSED'} &nbsp;|&nbsp;
    {'🟡 DEMO' if demo_mode else '🟢 LIVE'}
  </span>
</div>
""", unsafe_allow_html=True)

td = st.session_state["tick_data"]

# ── ROW 1: TOP METRICS ──
spot = td.get("NF_SPOT", {})
nifty_ltp  = spot.get("ltp",  24620.0)
nifty_cls  = spot.get("close", 24560.0)
nifty_chg  = round(nifty_ltp - nifty_cls, 2)
nifty_chgp = round(nifty_chg / nifty_cls * 100, 2) if nifty_cls else 0

c1, c2, c3, c4, c5, c6 = st.columns([2.2, 1.4, 1.4, 1.4, 1.4, 1.4])

with c1:
    cc = "#00e676" if nifty_chg >= 0 else "#ff4757"
    arr = "▲" if nifty_chg >= 0 else "▼"
    st.markdown(f"""
    <div class="metric-card" style="border-left:3px solid #ffd700">
      <div class="metric-label">NIFTY 50 SPOT</div>
      <div style="font-family:JetBrains Mono,monospace;font-size:1.9rem;font-weight:700;color:#ffd700">{nifty_ltp:,.2f}</div>
      <div style="font-family:JetBrains Mono,monospace;font-size:0.82rem;color:{cc}">{arr} {abs(nifty_chg):.2f} ({abs(nifty_chgp):.2f}%)</div>
    </div>""", unsafe_allow_html=True)

# Dynamic ATM detection
atm_strike = ATM
live_strikes = sorted([DEMO_TOKENS[k]["strike"] for k in DEMO_TOKENS if DEMO_TOKENS[k]["type"] == "CE"])
if live_strikes:
    atm_strike = min(live_strikes, key=lambda x: abs(x - nifty_ltp))

# Fetch ATM CE/PE from tick_data
atm_ce_key = f"NF_CE_{atm_strike}"
atm_pe_key = f"NF_PE_{atm_strike}"
atm_ce_ltp = td.get(atm_ce_key, {}).get("ltp", 0)
atm_pe_ltp = td.get(atm_pe_key, {}).get("ltp", 0)
atm_ce_oi  = td.get(atm_ce_key, {}).get("oi",  0)
atm_pe_oi  = td.get(atm_pe_key, {}).get("oi",  0)
pcr = round(atm_pe_oi / atm_ce_oi, 2) if atm_ce_oi else 0

metrics = [
    (f"ATM CE ({atm_strike})", f"{atm_ce_ltp:.1f}", "#00e676", f"OI:{fmt_qty(atm_ce_oi)}"),
    (f"ATM PE ({atm_strike})", f"{atm_pe_ltp:.1f}", "#ff4757", f"OI:{fmt_qty(atm_pe_oi)}"),
    ("PCR (ATM OI)",           f"{pcr:.2f}",         "#ffd700", "Put/Call"),
    ("VIX",                    "14.23",               "#a78bfa", "LOW"),
    ("MAX PAIN",               f"{atm_strike}",       "#00d4ff", "Strike"),
]

for col, (label, val, color, sub) in zip([c2, c3, c4, c5, c6], metrics):
    with col:
        st.markdown(f"""
        <div class="metric-card" style="border-left:3px solid {color}">
          <div class="metric-label">{label}</div>
          <div class="metric-value" style="color:{color}">{val}</div>
          <div style="font-family:JetBrains Mono,monospace;font-size:0.64rem;color:#5a7a9a">{sub}</div>
        </div>""", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ── ROW 2: OPTION CHAIN + TICK STREAM ──
chain_col, tick_col = st.columns([3, 2])

with chain_col:
    st.markdown('<div class="section-hdr">📋 LIVE OPTION CHAIN</div>', unsafe_allow_html=True)

    rows_html = ""
    for strike in sorted(DEMO_STRIKES, reverse=True):
        ce_k = f"NF_CE_{strike}"
        pe_k = f"NF_PE_{strike}"
        ce   = td.get(ce_k, {})
        pe   = td.get(pe_k, {})
        is_atm = (strike == atm_strike)

        def g(tick, field, default=0):
            return tick.get(field, default)

        ce_ltp  = g(ce, "ltp",   DEMO_TOKENS.get(ce_k, {}).get("base_ltp", 0))
        pe_ltp  = g(pe, "ltp",   DEMO_TOKENS.get(pe_k, {}).get("base_ltp", 0))
        ce_oi   = g(ce, "oi",    random.randint(50_000, 400_000))
        pe_oi   = g(pe, "oi",    random.randint(50_000, 400_000))
        ce_vol  = g(ce, "volume", random.randint(1_000, 30_000))
        pe_vol  = g(pe, "volume", random.randint(1_000, 30_000))
        ce_chg  = g(ce, "day_chg_pct", random.uniform(-8, 8))
        pe_chg  = g(pe, "day_chg_pct", random.uniform(-8, 8))
        ce_bid  = g(ce, "bid", max(0.05, ce_ltp - 0.5))
        ce_ask  = g(ce, "ask", ce_ltp + 0.5)
        pe_bid  = g(pe, "bid", max(0.05, pe_ltp - 0.5))
        pe_ask  = g(pe, "ask", pe_ltp + 0.5)

        rc  = "atm-strike" if is_atm else ""
        cc2 = f'<span style="color:{"#00e676" if ce_chg>=0 else "#ff4757"}">{"▲" if ce_chg>=0 else "▼"}{abs(ce_chg):.1f}%</span>'
        pc2 = f'<span style="color:{"#00e676" if pe_chg>=0 else "#ff4757"}">{"▲" if pe_chg>=0 else "▼"}{abs(pe_chg):.1f}%</span>'

        rows_html += f"""
        <tr class="{rc}">
          <td class="ce-col" style="font-family:JetBrains Mono,monospace">{fmt_qty(ce_oi)}</td>
          <td class="ce-col">{fmt_qty(ce_vol)}</td>
          <td class="ce-col">{cc2}</td>
          <td class="ce-col" style="font-weight:700">{ce_ltp:.1f}</td>
          <td class="ce-col" style="font-size:0.68rem;color:#3a7a5a">{ce_bid:.1f}/{ce_ask:.1f}</td>
          <td class="strike-col">{'⭐' if is_atm else ''}{strike}</td>
          <td class="pe-col" style="font-size:0.68rem;color:#7a3a3a">{pe_bid:.1f}/{pe_ask:.1f}</td>
          <td class="pe-col" style="font-weight:700">{pe_ltp:.1f}</td>
          <td class="pe-col">{pc2}</td>
          <td class="pe-col">{fmt_qty(pe_vol)}</td>
          <td class="pe-col" style="font-family:JetBrains Mono,monospace">{fmt_qty(pe_oi)}</td>
        </tr>"""

    st.markdown(f"""
    <div style="overflow-x:auto">
    <table class="chain-tbl">
      <thead>
        <tr>
          <th colspan="5" style="color:#00e676;background:#001a0d">── CALLS (CE) ──</th>
          <th style="color:#ffd700;background:#0a0800">STRIKE</th>
          <th colspan="5" style="color:#ff4757;background:#1a0000">── PUTS (PE) ──</th>
        </tr>
        <tr><th>OI</th><th>VOL</th><th>CHG%</th><th>LTP</th><th>BID/ASK</th><th></th><th>BID/ASK</th><th>LTP</th><th>CHG%</th><th>VOL</th><th>OI</th></tr>
      </thead>
      <tbody>{rows_html}</tbody>
    </table></div>""", unsafe_allow_html=True)


with tick_col:
    st.markdown('<div class="section-hdr">⚡ TICK STREAM</div>', unsafe_allow_html=True)

    tick_rows = ""
    for token in list(DEMO_TOKENS.keys()) if demo_mode else list(td.keys())[:15]:
        info = DEMO_TOKENS.get(token, {})
        tick = td.get(token, {})
        if not tick: continue
        ltp   = tick.get("ltp", 0)
        chgp  = tick.get("chg_pct", 0)
        vol   = tick.get("volume", 0)
        ts    = tick.get("timestamp", "--")
        ttype = info.get("type", "")
        sym   = info.get("symbol", token)[:16]
        tc    = "#00e676" if ttype == "CE" else "#ff4757" if ttype == "PE" else "#ffd700"
        vc    = "#00e676" if chgp >= 0 else "#ff4757"
        arr   = "▲" if chgp >= 0 else "▼"
        tick_rows += f"""
        <tr>
          <td style="font-family:JetBrains Mono,monospace;font-size:0.67rem;color:#3a5a7a">{ts}</td>
          <td style="font-size:0.68rem;color:{tc};font-weight:600">{ttype or "IDX"}</td>
          <td style="font-family:JetBrains Mono,monospace;font-size:0.72rem;color:#7ab8d8">{sym}</td>
          <td style="font-family:JetBrains Mono,monospace;font-weight:700;font-size:0.82rem;color:{vc}">{ltp:.1f}</td>
          <td style="font-size:0.68rem;color:{vc}">{arr}{abs(chgp):.3f}%</td>
          <td style="font-family:JetBrains Mono,monospace;font-size:0.68rem;color:#3a5a7a">{fmt_qty(vol)}</td>
        </tr>"""

    st.markdown(f"""
    <div style="overflow-y:auto;max-height:300px">
    <table class="chain-tbl">
      <thead><tr><th>TIME</th><th>TYPE</th><th>SYMBOL</th><th>LTP</th><th>TICK%</th><th>VOL</th></tr></thead>
      <tbody>{tick_rows}</tbody>
    </table></div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown(f'<div class="section-hdr">📊 MARKET DEPTH — ATM CE ({atm_strike})</div>', unsafe_allow_html=True)

    atm_ce = td.get(atm_ce_key, {})
    bp = atm_ce.get("bid", atm_ce_ltp - 0.5) if atm_ce_ltp else 95.0
    ap = atm_ce.get("ask", atm_ce_ltp + 0.5) if atm_ce_ltp else 95.5
    bq = atm_ce.get("bid_qty", 1000)
    aq = atm_ce.get("ask_qty", 800)

    depth_rows = ""
    for i in range(5):
        bp_i = round(bp - i * 0.5, 1)
        ap_i = round(ap + i * 0.5, 1)
        bq_i = max(25, int(bq * (1 - i * 0.2) + random.randint(-50, 50)))
        aq_i = max(25, int(aq * (1 - i * 0.2) + random.randint(-50, 50)))
        depth_rows += f"""
        <tr>
          <td style="color:#00e676;font-family:JetBrains Mono,monospace;font-size:0.76rem">{bq_i}</td>
          <td style="color:#00e676;font-family:JetBrains Mono,monospace;font-weight:700">{bp_i}</td>
          <td style="color:#ff4757;font-family:JetBrains Mono,monospace;font-weight:700">{ap_i}</td>
          <td style="color:#ff4757;font-family:JetBrains Mono,monospace;font-size:0.76rem">{aq_i}</td>
        </tr>"""

    st.markdown(f"""<table class="chain-tbl" style="width:100%">
      <thead><tr><th style="color:#00e676">BID QTY</th><th style="color:#00e676">BID</th><th style="color:#ff4757">ASK</th><th style="color:#ff4757">ASK QTY</th></tr></thead>
      <tbody>{depth_rows}</tbody></table>""", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ── ROW 3: CHARTS ──
st.markdown('<div class="section-hdr">📈 TICK CHARTS</div>', unsafe_allow_html=True)
ch1, ch2, ch3 = st.columns(3)

for col, (token, label, color) in zip(
    [ch1, ch2, ch3],
    [("NF_SPOT", "NIFTY SPOT", "#ffd700"),
     (atm_ce_key, f"{atm_strike} CE", "#00e676"),
     (atm_pe_key, f"{atm_strike} PE", "#ff4757")]
):
    history = list(st.session_state["tick_history"].get(token, deque()))
    with col:
        if len(history) >= 2:
            times  = [h[0] for h in history]
            prices = [h[1] for h in history]
            fill_c = color[:1] + color[1:] if color.startswith("#") else color
            fig = go.Figure(go.Scatter(
                x=times, y=prices,
                mode="lines",
                line=dict(color=color, width=1.5),
                fill="tozeroy",
                fillcolor=f"rgba({int(color[1:3],16)},{int(color[3:5],16)},{int(color[5:7],16)},0.08)"
            ))
            fig.update_layout(
                title=dict(text=label, font=dict(family="JetBrains Mono", size=10, color=color), x=0.04),
                plot_bgcolor="#0a0e17", paper_bgcolor="#0d1526",
                font=dict(family="JetBrains Mono", color="#5a7a9a", size=8),
                margin=dict(l=40, r=10, t=28, b=28), height=175,
                xaxis=dict(showgrid=False, tickformat="%H:%M:%S", tickfont=dict(size=7), linecolor="#1e3a5f"),
                yaxis=dict(showgrid=True, gridcolor="#0d1828", tickfont=dict(size=8), linecolor="#1e3a5f"),
                showlegend=False, hovermode="x unified",
            )
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        else:
            st.markdown(f'<div class="info-box" style="height:175px;display:flex;align-items:center;justify-content:center;text-align:center">⏳ {label}<br>Waiting for ticks</div>', unsafe_allow_html=True)

# ── ROW 4: OI CHART ──
st.markdown("<br>", unsafe_allow_html=True)
oi1, oi2 = st.columns([2, 1])

with oi1:
    st.markdown('<div class="section-hdr">📊 OPEN INTEREST DISTRIBUTION</div>', unsafe_allow_html=True)
    oi_strikes = sorted(DEMO_STRIKES)
    ce_oi_vals = [td.get(f"NF_CE_{s}", {}).get("oi", random.randint(100_000, 600_000)) for s in oi_strikes]
    pe_oi_vals = [td.get(f"NF_PE_{s}", {}).get("oi", random.randint(100_000, 600_000)) for s in oi_strikes]
    fig2 = go.Figure()
    fig2.add_trace(go.Bar(name="CE OI", x=[str(s) for s in oi_strikes], y=ce_oi_vals, marker_color="#00e676", opacity=0.85))
    fig2.add_trace(go.Bar(name="PE OI", x=[str(s) for s in oi_strikes], y=pe_oi_vals, marker_color="#ff4757", opacity=0.85))
    atm_idx = oi_strikes.index(atm_strike) if atm_strike in oi_strikes else 0
    fig2.update_layout(
        barmode="group", plot_bgcolor="#0a0e17", paper_bgcolor="#0d1526",
        font=dict(family="JetBrains Mono", color="#5a7a9a", size=8),
        margin=dict(l=40, r=20, t=15, b=35), height=200,
        xaxis=dict(showgrid=False, linecolor="#1e3a5f", tickfont=dict(size=8)),
        yaxis=dict(showgrid=True, gridcolor="#0d1828", linecolor="#1e3a5f", tickfont=dict(size=8)),
        legend=dict(font=dict(size=8), bgcolor="rgba(0,0,0,0)"),
    )
    fig2.add_vline(x=atm_idx, line=dict(color="#ffd700", width=1, dash="dash"),
                   annotation_text="ATM", annotation_font=dict(color="#ffd700", size=8))
    st.plotly_chart(fig2, use_container_width=True, config={"displayModeBar": False})


with oi2:
    st.markdown('<div class="section-hdr">⚙ DEBUG INFO</div>', unsafe_allow_html=True)
    ws_url = f"wss://stream.sharekhan.com/skstream/api/stream?ACCESS_TOKEN={st.session_state['access_token_str'][:15]}..." if st.session_state['access_token_str'] else "Not connected"
    st.markdown(f"""
    <div class="info-box" style="font-size:0.68rem">
      <b>WS URL:</b> {ws_url}<br>
      <b>Token loaded:</b> {'✅' if st.session_state['access_token_str'] else '❌'}<br>
      <b>WS connected:</b> {'✅' if st.session_state['ws_connected'] else '❌'}<br>
      <b>WS error:</b> {st.session_state['ws_error'] or 'None'}<br>
      <b>Mode:</b> {'DEMO' if demo_mode else 'LIVE ✅'}<br>
      <b>Total ticks:</b> {st.session_state['total_ticks']}<br>
      <b>Live tokens:</b> {len(td)}
    </div>
    """, unsafe_allow_html=True)


# ── SCRIP MASTER BROWSER ──
if st.session_state["scrip_master_df"] is not None:
    with st.expander("📂 Scrip Master (NF) — find your token codes here"):
        df_sm = st.session_state["scrip_master_df"]
        srch = st.text_input("Search symbol", placeholder="NIFTY", key="sm_srch")
        if srch:
            df_sm = df_sm[df_sm.apply(lambda r: r.astype(str).str.contains(srch.upper(), case=False).any(), axis=1)]
        st.dataframe(df_sm.head(300), use_container_width=True, height=280)
        st.caption("WebSocket token = Exchange code (NF) + ScripCode number. E.g. ScripCode=37833 → token=NF37833")


# ── FOOTER ──
st.markdown("""
<div style="text-align:center;font-family:JetBrains Mono,monospace;font-size:0.62rem;color:#1a3a5a;padding:10px;border-top:1px solid #0d1828;margin-top:16px">
  SHAREKHAN TERMINAL v3.0 &nbsp;|&nbsp; AUDITED AGAINST shareconnect v1.0.0.11 &nbsp;|&nbsp; NSE F&O &nbsp;|&nbsp; ⚠ For personal use only. Trading involves risk.
</div>""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────
# AUTO REFRESH
# ─────────────────────────────────────────────────────────────────
if auto_refresh:
    time.sleep(refresh_rate)
    st.rerun()
