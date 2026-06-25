"""
╔══════════════════════════════════════════════════════════════════╗
║      SHAREKHAN LIVE TRADING TERMINAL — Nifty Options Focus      ║
║      Tick-by-Tick WebSocket Dashboard via Streamlit             ║
╚══════════════════════════════════════════════════════════════════╝

Usage:
    1. Run daily_login.py first to save access_token.txt
    2. streamlit run sharekhan_terminal.py

Install:
    pip install shareconnect websocket-client streamlit pandas plotly requests
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import threading
import time
import json
import os
import re
from datetime import datetime
from collections import deque, defaultdict
import queue

# ─────────────────────────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Sharekhan Live Terminal",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ─────────────────────────────────────────────────────────────────
# DARK TERMINAL CSS
# ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Rajdhani:wght@400;500;600;700&display=swap');

html, body, [class*="css"] {
    font-family: 'Rajdhani', sans-serif !important;
    background: #0a0e17 !important;
    color: #e0e6f0 !important;
}

.stApp { background: #0a0e17 !important; }

/* HEADER */
.terminal-header {
    background: linear-gradient(135deg, #0d1526 0%, #091020 100%);
    border: 1px solid #1e3a5f;
    border-radius: 6px;
    padding: 12px 20px;
    margin-bottom: 16px;
    display: flex;
    align-items: center;
    justify-content: space-between;
}

.terminal-title {
    font-family: 'JetBrains Mono', monospace;
    font-size: 1.1rem;
    font-weight: 700;
    color: #00d4ff;
    letter-spacing: 2px;
    text-transform: uppercase;
}

/* METRIC CARDS */
.metric-card {
    background: linear-gradient(135deg, #0d1526 0%, #111827 100%);
    border: 1px solid #1e3a5f;
    border-radius: 6px;
    padding: 12px 16px;
    margin: 4px 0;
    font-family: 'JetBrains Mono', monospace;
}

.metric-label {
    font-size: 0.68rem;
    color: #5a7a9a;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    font-family: 'JetBrains Mono', monospace;
}

.metric-value {
    font-size: 1.4rem;
    font-weight: 700;
    font-family: 'JetBrains Mono', monospace;
}

.metric-green { color: #00e676; }
.metric-red { color: #ff4757; }
.metric-blue { color: #00d4ff; }
.metric-yellow { color: #ffd700; }
.metric-white { color: #e0e6f0; }

/* STATUS BADGE */
.status-connected {
    display: inline-block;
    background: #003d1e;
    color: #00e676;
    border: 1px solid #00e676;
    border-radius: 4px;
    padding: 2px 10px;
    font-size: 0.72rem;
    font-family: 'JetBrains Mono', monospace;
    font-weight: 700;
    letter-spacing: 1px;
}

.status-disconnected {
    display: inline-block;
    background: #3d0000;
    color: #ff4757;
    border: 1px solid #ff4757;
    border-radius: 4px;
    padding: 2px 10px;
    font-size: 0.72rem;
    font-family: 'JetBrains Mono', monospace;
    font-weight: 700;
    letter-spacing: 1px;
}

/* OPTION CHAIN TABLE */
.chain-table {
    width: 100%;
    border-collapse: collapse;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.78rem;
}

.chain-table th {
    background: #0d1e35;
    color: #5a9abf;
    padding: 8px 12px;
    text-align: center;
    font-weight: 600;
    letter-spacing: 1px;
    font-size: 0.68rem;
    text-transform: uppercase;
    border-bottom: 1px solid #1e3a5f;
}

.chain-table td {
    padding: 7px 12px;
    text-align: center;
    border-bottom: 1px solid #0d1828;
    transition: background 0.1s;
}

.chain-table tr:hover td { background: #0d1e35; }

.ce-col { color: #00e676; }
.pe-col { color: #ff4757; }
.strike-col {
    color: #ffd700;
    font-weight: 700;
    background: #0d1828 !important;
    font-size: 0.85rem;
}

.atm-strike td {
    background: #1a1200 !important;
    border-top: 1px solid #ffd700;
    border-bottom: 1px solid #ffd700;
}

/* TICK TABLE */
.tick-row-up { color: #00e676; font-weight: 600; }
.tick-row-down { color: #ff4757; font-weight: 600; }

/* SECTION HEADERS */
.section-header {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.72rem;
    color: #00d4ff;
    text-transform: uppercase;
    letter-spacing: 2px;
    padding: 6px 0;
    border-bottom: 1px solid #1e3a5f;
    margin-bottom: 12px;
}

/* SIDEBAR */
section[data-testid="stSidebar"] {
    background: #080d16 !important;
    border-right: 1px solid #1e3a5f !important;
}

/* Buttons */
.stButton>button {
    background: #0d2a4a !important;
    color: #00d4ff !important;
    border: 1px solid #1e3a5f !important;
    border-radius: 4px !important;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.78rem !important;
    letter-spacing: 1px !important;
    font-weight: 600 !important;
    padding: 6px 16px !important;
}
.stButton>button:hover {
    background: #1e3a5f !important;
    border-color: #00d4ff !important;
}

/* Inputs */
.stTextInput>div>div>input {
    background: #0d1526 !important;
    color: #e0e6f0 !important;
    border: 1px solid #1e3a5f !important;
    font-family: 'JetBrains Mono', monospace !important;
}

/* Expander */
.streamlit-expanderHeader {
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.78rem !important;
    color: #5a9abf !important;
    background: #0a0e17 !important;
}

/* Scrollbar */
::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: #0a0e17; }
::-webkit-scrollbar-thumb { background: #1e3a5f; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #2a5a8f; }

/* Alert box */
.info-box {
    background: #0d1e35;
    border: 1px solid #1e3a5f;
    border-left: 3px solid #00d4ff;
    border-radius: 4px;
    padding: 10px 16px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.8rem;
    color: #8ab8d8;
    margin: 8px 0;
}

.warn-box {
    background: #1e1400;
    border: 1px solid #ffd700;
    border-left: 3px solid #ffd700;
    border-radius: 4px;
    padding: 10px 16px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.8rem;
    color: #c8a800;
    margin: 8px 0;
}
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────
# SESSION STATE INITIALIZATION
# ─────────────────────────────────────────────────────────────────
def init_state():
    defaults = {
        "access_token": "",
        "api_key": "",
        "secret_key": "",
        "ws_connected": False,
        "ws_thread": None,
        "tick_data": {},          # token -> latest tick dict
        "tick_history": defaultdict(lambda: deque(maxlen=500)),  # token -> deque of (time, ltp)
        "scrip_master": None,
        "subscribed_tokens": [],
        "tick_queue": queue.Queue(),
        "login_url": "",
        "last_update": None,
        "total_ticks": 0,
        "positions": [],
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_state()


# ─────────────────────────────────────────────────────────────────
# SHAREKHAN API WRAPPER (Safe import)
# ─────────────────────────────────────────────────────────────────
SHAREKHAN_AVAILABLE = False
try:
    from SharekhanApi.sharekhanConnect import SharekhanConnect
    from SharekhanApi.sharekhanWebsocket import SharekhanWebSocket
    SHAREKHAN_AVAILABLE = True
except ImportError:
    pass


def get_login_url(api_key, vendor_key="", version_id=None):
    if not SHAREKHAN_AVAILABLE:
        return None, "shareconnect not installed. Run: pip install shareconnect"
    try:
        login = SharekhanConnect(api_key)
        url = login.login_url(vendor_key=vendor_key, version_id=version_id)
        return url, None
    except Exception as e:
        return None, str(e)


def generate_access_token(api_key, request_token, secret_key, state=12345, version_id=None):
    if not SHAREKHAN_AVAILABLE:
        return None, "shareconnect not installed"
    try:
        login = SharekhanConnect(api_key)
        session = login.generate_session_without_versionId(request_token, secret_key)
        access_token = login.get_access_token(api_key, session, state)
        return access_token, None
    except Exception as e:
        return None, str(e)


def load_scrip_master(api_key, access_token, exchange="NF"):
    if not SHAREKHAN_AVAILABLE:
        return None, "shareconnect not installed"
    try:
        sk = SharekhanConnect(api_key, access_token)
        data = sk.master(exchange)
        df = pd.DataFrame(data)
        return df, None
    except Exception as e:
        return None, str(e)


def get_positions(api_key, access_token, customer_id):
    if not SHAREKHAN_AVAILABLE:
        return [], "shareconnect not installed"
    try:
        sk = SharekhanConnect(api_key, access_token)
        result = sk.trades(customer_id)
        return result, None
    except Exception as e:
        return [], str(e)


# ─────────────────────────────────────────────────────────────────
# WEBSOCKET MANAGER
# ─────────────────────────────────────────────────────────────────
def start_websocket(access_token, tokens_to_subscribe):
    """Start WebSocket in a background thread."""
    if not SHAREKHAN_AVAILABLE:
        return False, "shareconnect not installed"

    try:
        sws = SharekhanWebSocket(access_token)

        subscribe_msg = {
            "action": "subscribe",
            "key": ["feed"],
            "value": [""]
        }

        def on_open(wsapp):
            st.session_state["ws_connected"] = True
            sws.subscribe(subscribe_msg)
            # Subscribe to specific tokens for depth
            if tokens_to_subscribe:
                depth_msg = {
                    "action": "feed",
                    "key": ["depth"],
                    "value": [",".join(tokens_to_subscribe)]
                }
                sws.fetchData(depth_msg)

        def on_data(wsapp, message):
            try:
                if isinstance(message, str):
                    data = json.loads(message)
                else:
                    data = message

                st.session_state["tick_queue"].put(data)
                st.session_state["total_ticks"] += 1
                st.session_state["last_update"] = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            except Exception:
                pass

        def on_error(wsapp, error):
            st.session_state["ws_connected"] = False

        def on_close(wsapp):
            st.session_state["ws_connected"] = False

        sws.on_open = on_open
        sws.on_data = on_data
        sws.on_error = on_error
        sws.on_close = on_close

        def run():
            sws.connect()

        t = threading.Thread(target=run, daemon=True)
        t.start()
        st.session_state["ws_thread"] = t
        return True, None

    except Exception as e:
        return False, str(e)


def process_tick_queue():
    """Pull ticks from queue into session state tick_data."""
    processed = 0
    while not st.session_state["tick_queue"].empty() and processed < 100:
        try:
            data = st.session_state["tick_queue"].get_nowait()
            # data could be a list or dict
            if isinstance(data, list):
                for tick in data:
                    _process_single_tick(tick)
            elif isinstance(data, dict):
                _process_single_tick(data)
            processed += 1
        except queue.Empty:
            break


def _process_single_tick(tick):
    token = tick.get("token") or tick.get("ScripToken") or tick.get("scripToken")
    if not token:
        return
    token = str(token)

    # Normalize field names
    normalized = {
        "token": token,
        "ltp": float(tick.get("LTP") or tick.get("ltp") or tick.get("LastRate") or 0),
        "ltq": int(tick.get("LTQ") or tick.get("ltq") or tick.get("LastQty") or 0),
        "volume": int(tick.get("Volume") or tick.get("volume") or tick.get("TotalQty") or 0),
        "open": float(tick.get("Open") or tick.get("open") or tick.get("OpenRate") or 0),
        "high": float(tick.get("High") or tick.get("high") or 0),
        "low": float(tick.get("Low") or tick.get("low") or 0),
        "close": float(tick.get("PClose") or tick.get("Close") or tick.get("close") or 0),
        "bid": float(tick.get("BidPrice") or tick.get("bid") or 0),
        "bid_qty": int(tick.get("BidQuantity") or tick.get("BidQty") or 0),
        "ask": float(tick.get("OfferPrice") or tick.get("ask") or 0),
        "ask_qty": int(tick.get("OfferQuantity") or tick.get("OfferQty") or 0),
        "total_buy_qty": int(tick.get("TotalBuyQty") or 0),
        "total_sell_qty": int(tick.get("TotalSellQty") or 0),
        "oi": int(tick.get("OI") or tick.get("oi") or tick.get("OpenInterest") or 0),
        "timestamp": datetime.now().strftime("%H:%M:%S.%f")[:-3],
    }

    # Calculate change %
    prev_ltp = st.session_state["tick_data"].get(token, {}).get("ltp", normalized["ltp"])
    if prev_ltp > 0:
        normalized["chg_pct"] = round((normalized["ltp"] - prev_ltp) / prev_ltp * 100, 3)
    else:
        normalized["chg_pct"] = 0.0

    # Change from close
    if normalized["close"] > 0:
        normalized["day_chg_pct"] = round(
            (normalized["ltp"] - normalized["close"]) / normalized["close"] * 100, 2
        )
    else:
        normalized["day_chg_pct"] = 0.0

    st.session_state["tick_data"][token] = normalized
    st.session_state["tick_history"][token].append(
        (datetime.now(), normalized["ltp"])
    )


# ─────────────────────────────────────────────────────────────────
# DEMO DATA GENERATOR (when not connected to real API)
# ─────────────────────────────────────────────────────────────────
import random

DEMO_TOKENS = {
    "NF_CE_24500": {"symbol": "NIFTY24MAY24500CE", "type": "CE", "strike": 24500, "base_ltp": 145.0},
    "NF_CE_24600": {"symbol": "NIFTY24MAY24600CE", "type": "CE", "strike": 24600, "base_ltp": 95.0},
    "NF_CE_24700": {"symbol": "NIFTY24MAY24700CE", "type": "CE", "strike": 24700, "base_ltp": 52.0},
    "NF_CE_24800": {"symbol": "NIFTY24MAY24800CE", "type": "CE", "strike": 24800, "base_ltp": 22.0},
    "NF_CE_24900": {"symbol": "NIFTY24MAY24900CE", "type": "CE", "strike": 24900, "base_ltp": 8.5},
    "NF_ATM":      {"symbol": "NIFTY SPOT",        "type": "IDX", "strike": 0,     "base_ltp": 24620.0},
    "NF_PE_24600": {"symbol": "NIFTY24MAY24600PE", "type": "PE", "strike": 24600, "base_ltp": 75.0},
    "NF_PE_24500": {"symbol": "NIFTY24MAY24500PE", "type": "PE", "strike": 24500, "base_ltp": 30.0},
    "NF_PE_24400": {"symbol": "NIFTY24MAY24400PE", "type": "PE", "strike": 24400, "base_ltp": 12.0},
    "NF_PE_24300": {"symbol": "NIFTY24MAY24300PE", "type": "PE", "strike": 24300, "base_ltp": 4.5},
}

# Initialize demo data
if "demo_prices" not in st.session_state:
    st.session_state["demo_prices"] = {k: v["base_ltp"] for k, v in DEMO_TOKENS.items()}
    st.session_state["demo_oi"] = {k: random.randint(50000, 500000) for k in DEMO_TOKENS}
    st.session_state["demo_vol"] = {k: random.randint(1000, 50000) for k in DEMO_TOKENS}


def update_demo_data():
    """Simulate live tick movement."""
    for token, info in DEMO_TOKENS.items():
        price = st.session_state["demo_prices"][token]
        # Random walk with mean reversion
        change_pct = random.gauss(0, 0.003)
        new_price = max(0.05, price * (1 + change_pct))
        st.session_state["demo_prices"][token] = round(new_price, 2)

        # Simulate tick
        tick = {
            "token": token,
            "LTP": new_price,
            "LTQ": random.randint(25, 500),
            "TotalQty": st.session_state["demo_vol"][token] + random.randint(0, 200),
            "High": new_price * 1.02,
            "Low": new_price * 0.98,
            "OpenRate": info["base_ltp"],
            "PClose": info["base_ltp"],
            "BidPrice": new_price - random.uniform(0.1, 0.5),
            "BidQuantity": random.randint(100, 2000),
            "OfferPrice": new_price + random.uniform(0.1, 0.5),
            "OfferQuantity": random.randint(100, 2000),
            "TotalBuyQty": random.randint(50000, 200000),
            "TotalSellQty": random.randint(50000, 200000),
            "OI": st.session_state["demo_oi"][token] + random.randint(-500, 500),
        }
        st.session_state["demo_vol"][token] = int(tick["TotalQty"])
        _process_single_tick(tick)


# ─────────────────────────────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────────────────────────────
def color_val(val, positive_green=True):
    if val > 0:
        color = "#00e676" if positive_green else "#ff4757"
        symbol = "▲"
    elif val < 0:
        color = "#ff4757" if positive_green else "#00e676"
        symbol = "▼"
    else:
        color = "#8a9ab8"
        symbol = "─"
    return f'<span style="color:{color}">{symbol} {abs(val):.2f}</span>'


def fmt_price(val, decimals=2):
    return f'<span style="font-family:JetBrains Mono,monospace;font-weight:600">{val:,.{decimals}f}</span>'


def fmt_qty(val):
    if val >= 10_000_000:
        return f"{val/10_000_000:.1f}Cr"
    elif val >= 100_000:
        return f"{val/100_000:.1f}L"
    elif val >= 1000:
        return f"{val/1000:.1f}K"
    return str(val)


# ─────────────────────────────────────────────────────────────────
# SIDEBAR — AUTHENTICATION & SETTINGS
# ─────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown('<div class="terminal-title">⚡ SK TERMINAL</div>', unsafe_allow_html=True)
    st.markdown("---")

    # Try to load saved token
    if os.path.exists("access_token.txt") and not st.session_state["access_token"]:
        with open("access_token.txt") as f:
            st.session_state["access_token"] = f.read().strip()

    st.markdown('<div class="section-header">🔐 Authentication</div>', unsafe_allow_html=True)

    api_key = st.text_input("API Key", value=st.session_state["api_key"],
                             type="password", key="api_key_input")
    secret_key = st.text_input("Secret Key", value=st.session_state["secret_key"],
                                type="password", key="secret_key_input")

    if api_key:
        st.session_state["api_key"] = api_key
    if secret_key:
        st.session_state["secret_key"] = secret_key

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Get Login URL"):
            if api_key:
                url, err = get_login_url(api_key)
                if url:
                    st.session_state["login_url"] = url
                else:
                    if not SHAREKHAN_AVAILABLE:
                        st.session_state["login_url"] = "DEMO_MODE"

    if st.session_state["login_url"] and st.session_state["login_url"] != "DEMO_MODE":
        st.markdown(
            f'<div class="info-box">📎 <a href="{st.session_state["login_url"]}" target="_blank" '
            f'style="color:#00d4ff">Open Login URL</a><br><small>Login → copy request_token from redirect URL</small></div>',
            unsafe_allow_html=True
        )
        req_token = st.text_input("request_token (from redirect URL)", key="req_token_input")
        if st.button("Generate Access Token") and req_token:
            token, err = generate_access_token(api_key, req_token, secret_key)
            if token:
                st.session_state["access_token"] = token
                with open("access_token.txt", "w") as f:
                    f.write(token)
                st.success("✅ Token saved!")
            else:
                st.error(f"Error: {err}")

    st.markdown("---")
    st.markdown('<div class="section-header">🔌 Connection</div>', unsafe_allow_html=True)

    mode = st.radio("Mode", ["🔴 Demo (Simulated)", "🟢 Live (Real API)"],
                    index=0, key="mode_radio")
    demo_mode = "Demo" in mode

    access_token_display = st.session_state["access_token"][:20] + "..." if len(
        st.session_state["access_token"]) > 20 else st.session_state["access_token"]

    if st.session_state["access_token"]:
        st.markdown(f'<div class="info-box">Token: {access_token_display}</div>',
                    unsafe_allow_html=True)
    else:
        if not demo_mode:
            st.markdown('<div class="warn-box">⚠ No access token found.<br>Run daily_login.py or use Demo mode.</div>',
                        unsafe_allow_html=True)

    if not demo_mode:
        # Token entry for live mode
        tokens_raw = st.text_area(
            "WebSocket Tokens (one per line)",
            placeholder="NF37833\nNF37834\nNF37835",
            height=100,
            key="tokens_input"
        )
        if st.button("▶ Connect Live WebSocket") and st.session_state["access_token"]:
            tokens = [t.strip() for t in tokens_raw.split("\n") if t.strip()]
            ok, err = start_websocket(st.session_state["access_token"], tokens)
            if ok:
                st.success("WebSocket connecting...")
            else:
                st.error(f"Error: {err}")

    st.markdown("---")
    st.markdown('<div class="section-header">📊 Display Settings</div>', unsafe_allow_html=True)
    auto_refresh = st.checkbox("Auto Refresh", value=True, key="auto_refresh")
    refresh_rate = st.slider("Refresh (seconds)", 0.5, 5.0, 1.0, 0.5, key="refresh_rate")

    if not demo_mode and SHAREKHAN_AVAILABLE and st.session_state["access_token"]:
        if st.button("📥 Load Scrip Master (NF)"):
            df, err = load_scrip_master(api_key, st.session_state["access_token"], "NF")
            if df is not None:
                st.session_state["scrip_master"] = df
                st.success(f"Loaded {len(df)} scrips")
            else:
                st.error(str(err))

    st.markdown("---")
    # Connection status
    if st.session_state["ws_connected"] or demo_mode:
        st.markdown('<span class="status-connected">● CONNECTED</span>', unsafe_allow_html=True)
    else:
        st.markdown('<span class="status-disconnected">● DISCONNECTED</span>', unsafe_allow_html=True)

    if st.session_state["last_update"]:
        st.markdown(f'<div style="font-family:JetBrains Mono,monospace;font-size:0.68rem;color:#3a6a8a;margin-top:4px">Last tick: {st.session_state["last_update"]}</div>',
                    unsafe_allow_html=True)
    st.markdown(f'<div style="font-family:JetBrains Mono,monospace;font-size:0.68rem;color:#3a6a8a">Total ticks: {st.session_state["total_ticks"]}</div>',
                unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────
# UPDATE DATA
# ─────────────────────────────────────────────────────────────────
demo_mode = "Demo" in st.session_state.get("mode_radio", "Demo")

if demo_mode:
    update_demo_data()
    st.session_state["ws_connected"] = True
    if st.session_state["last_update"] is None:
        st.session_state["last_update"] = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    st.session_state["last_update"] = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    st.session_state["total_ticks"] += len(DEMO_TOKENS)
else:
    process_tick_queue()


# ─────────────────────────────────────────────────────────────────
# MAIN TERMINAL HEADER
# ─────────────────────────────────────────────────────────────────
now = datetime.now()
market_open = now.replace(hour=9, minute=15, second=0) <= now <= now.replace(hour=15, minute=30, second=0)
market_status = "🟢 MARKET OPEN" if market_open else "🔴 MARKET CLOSED"

st.markdown(f"""
<div class="terminal-header">
    <span class="terminal-title">📈 SHAREKHAN LIVE TERMINAL — NIFTY OPTIONS</span>
    <span style="font-family:JetBrains Mono,monospace;font-size:0.78rem;color:#5a9abf">
        {now.strftime("%d %b %Y  %H:%M:%S")} &nbsp;|&nbsp; {market_status}
        &nbsp;|&nbsp; {"🟡 DEMO MODE" if demo_mode else "🟢 LIVE MODE"}
    </span>
</div>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────
# ROW 1 — NIFTY SPOT + KEY METRICS
# ─────────────────────────────────────────────────────────────────
td = st.session_state["tick_data"]
nifty_tick = td.get("NF_ATM", {})
nifty_ltp = nifty_tick.get("ltp", 24620.0)
nifty_chg = nifty_tick.get("day_chg_pct", 0.12)
nifty_chg_pts = nifty_ltp - nifty_tick.get("close", nifty_ltp * 0.9988)

col1, col2, col3, col4, col5, col6 = st.columns([2, 1.5, 1.5, 1.5, 1.5, 1.5])

with col1:
    chg_color = "#00e676" if nifty_chg >= 0 else "#ff4757"
    arrow = "▲" if nifty_chg >= 0 else "▼"
    st.markdown(f"""
    <div class="metric-card" style="border-left: 3px solid #ffd700;">
        <div class="metric-label">NIFTY 50 SPOT</div>
        <div style="font-family:JetBrains Mono,monospace;font-size:2rem;font-weight:700;color:#ffd700">{nifty_ltp:,.2f}</div>
        <div style="font-family:JetBrains Mono,monospace;font-size:0.85rem;color:{chg_color}">{arrow} {abs(nifty_chg_pts):.2f} ({abs(nifty_chg):.2f}%)</div>
    </div>
    """, unsafe_allow_html=True)

metrics_data = [
    ("PCR (COI)", "0.87", "#ff9900", "⬆ Bullish"),
    ("ATM CE", f"{td.get('NF_CE_24600', {}).get('ltp', 95.0):.1f}", "#00e676", "24600"),
    ("ATM PE", f"{td.get('NF_PE_24600', {}).get('ltp', 75.0):.1f}", "#ff4757", "24600"),
    ("VIX", "14.23", "#a78bfa", "LOW"),
    ("Max Pain", "24500", "#00d4ff", "Strike"),
]

for i, (label, val, color, sub) in enumerate(metrics_data):
    cols_list = [col2, col3, col4, col5, col6]
    with cols_list[i]:
        st.markdown(f"""
        <div class="metric-card" style="border-left: 3px solid {color};">
            <div class="metric-label">{label}</div>
            <div class="metric-value" style="color:{color}">{val}</div>
            <div style="font-family:JetBrains Mono,monospace;font-size:0.68rem;color:#5a7a9a">{sub}</div>
        </div>
        """, unsafe_allow_html=True)


st.markdown("<br>", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────
# ROW 2 — OPTION CHAIN + LIVE TICK PANEL
# ─────────────────────────────────────────────────────────────────
chain_col, tick_col = st.columns([3, 2])

with chain_col:
    st.markdown('<div class="section-header">📋 LIVE OPTION CHAIN — NIFTY WEEKLY</div>', unsafe_allow_html=True)

    # Build chain table
    strikes = [24900, 24800, 24700, 24600, 24500, 24400, 24300]
    atm_strike = 24600

    chain_rows = []
    for strike in strikes:
        ce_token = f"NF_CE_{strike}"
        pe_token = f"NF_PE_{strike}"
        ce = td.get(ce_token, {})
        pe = td.get(pe_token, {})

        ce_ltp = ce.get("ltp", 0)
        pe_ltp = pe.get("ltp", 0)
        ce_oi = ce.get("oi", random.randint(50000, 400000))
        pe_oi = pe.get("oi", random.randint(50000, 400000))
        ce_vol = ce.get("volume", random.randint(1000, 30000))
        pe_vol = pe.get("volume", random.randint(1000, 30000))
        ce_chg = ce.get("day_chg_pct", random.uniform(-5, 5))
        pe_chg = pe.get("day_chg_pct", random.uniform(-5, 5))
        ce_bid = ce.get("bid", max(0, ce_ltp - 0.5))
        ce_ask = ce.get("ask", ce_ltp + 0.5)
        pe_bid = pe.get("bid", max(0, pe_ltp - 0.5))
        pe_ask = pe.get("ask", pe_ltp + 0.5)

        is_atm = strike == atm_strike
        row_class = 'atm-strike' if is_atm else ''

        ce_chg_html = f'<span style="color:{"#00e676" if ce_chg >= 0 else "#ff4757"}">{"▲" if ce_chg >= 0 else "▼"}{abs(ce_chg):.1f}%</span>'
        pe_chg_html = f'<span style="color:{"#00e676" if pe_chg >= 0 else "#ff4757"}">{"▲" if pe_chg >= 0 else "▼"}{abs(pe_chg):.1f}%</span>'

        chain_rows.append(f"""
        <tr class="{row_class}">
            <td class="ce-col" style="font-family:JetBrains Mono,monospace">{fmt_qty(ce_oi)}</td>
            <td class="ce-col">{fmt_qty(ce_vol)}</td>
            <td class="ce-col">{ce_chg_html}</td>
            <td class="ce-col" style="font-weight:700;font-size:0.88rem">{ce_ltp:.1f}</td>
            <td class="ce-col" style="font-size:0.72rem;color:#3a7a5a">{ce_bid:.1f}/{ce_ask:.1f}</td>
            <td class="strike-col">{'⭐ ' if is_atm else ''}{strike}</td>
            <td class="pe-col" style="font-size:0.72rem;color:#7a3a3a">{pe_bid:.1f}/{pe_ask:.1f}</td>
            <td class="pe-col" style="font-weight:700;font-size:0.88rem">{pe_ltp:.1f}</td>
            <td class="pe-col">{pe_chg_html}</td>
            <td class="pe-col">{fmt_qty(pe_vol)}</td>
            <td class="pe-col" style="font-family:JetBrains Mono,monospace">{fmt_qty(pe_oi)}</td>
        </tr>
        """)

    chain_html = f"""
    <div style="overflow-x:auto">
    <table class="chain-table">
        <thead>
            <tr>
                <th colspan="5" style="color:#00e676;background:#001a0d">── CALLS (CE) ──</th>
                <th style="color:#ffd700;background:#0a0800">STRIKE</th>
                <th colspan="5" style="color:#ff4757;background:#1a0000">── PUTS (PE) ──</th>
            </tr>
            <tr>
                <th>OI</th><th>VOL</th><th>CHG%</th><th>LTP</th><th>BID/ASK</th>
                <th></th>
                <th>BID/ASK</th><th>LTP</th><th>CHG%</th><th>VOL</th><th>OI</th>
            </tr>
        </thead>
        <tbody>
            {"".join(chain_rows)}
        </tbody>
    </table>
    </div>
    """
    st.markdown(chain_html, unsafe_allow_html=True)


with tick_col:
    st.markdown('<div class="section-header">⚡ LIVE TICK STREAM</div>', unsafe_allow_html=True)

    # Live tick table
    tick_rows = []
    tokens_to_show = list(DEMO_TOKENS.keys()) if demo_mode else list(td.keys())[:15]

    for token in tokens_to_show:
        info = DEMO_TOKENS.get(token, {})
        tick = td.get(token, {})
        if not tick:
            continue

        ltp = tick.get("ltp", 0)
        chg_pct = tick.get("chg_pct", 0)
        vol = tick.get("volume", 0)
        ts = tick.get("timestamp", "--")
        tick_type = info.get("type", "")
        symbol = info.get("symbol", token)

        color = "#00e676" if chg_pct >= 0 else "#ff4757"
        arrow = "▲" if chg_pct >= 0 else "▼"
        type_color = "#00e676" if tick_type == "CE" else "#ff4757" if tick_type == "PE" else "#ffd700"

        tick_rows.append(f"""
        <tr>
            <td style="font-family:JetBrains Mono,monospace;font-size:0.7rem;color:#5a7a9a">{ts}</td>
            <td style="font-size:0.72rem;color:{type_color};font-weight:600">{tick_type or "IDX"}</td>
            <td style="font-family:JetBrains Mono,monospace;font-size:0.75rem;color:#8ab8d8;max-width:120px;overflow:hidden">{symbol[:16]}</td>
            <td style="font-family:JetBrains Mono,monospace;font-weight:700;font-size:0.85rem;color:{color}">{ltp:.1f}</td>
            <td style="font-size:0.72rem;color:{color}">{arrow}{abs(chg_pct):.3f}%</td>
            <td style="font-family:JetBrains Mono,monospace;font-size:0.7rem;color:#5a7a9a">{fmt_qty(vol)}</td>
        </tr>
        """)

    tick_html = f"""
    <div style="overflow-y:auto;max-height:320px">
    <table class="chain-table">
        <thead>
            <tr><th>TIME</th><th>TYPE</th><th>SYMBOL</th><th>LTP</th><th>TICK%</th><th>VOL</th></tr>
        </thead>
        <tbody>
            {"".join(tick_rows)}
        </tbody>
    </table>
    </div>
    """
    st.markdown(tick_html, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # Market Depth for ATM CE
    st.markdown('<div class="section-header">📊 MARKET DEPTH — ATM CE (24600)</div>', unsafe_allow_html=True)

    atm_ce_tick = td.get("NF_CE_24600", {})
    bid_p = atm_ce_tick.get("bid", 94.5)
    ask_p = atm_ce_tick.get("ask", 95.5)
    bq = atm_ce_tick.get("bid_qty", 1250)
    aq = atm_ce_tick.get("ask_qty", 975)

    # Generate 5-level depth
    depth_rows = ""
    for i in range(5):
        b_price = round(bid_p - i * 0.5, 1)
        a_price = round(ask_p + i * 0.5, 1)
        b_qty = max(25, int(bq * (1 - i * 0.18) + random.randint(-50, 50)))
        a_qty = max(25, int(aq * (1 - i * 0.18) + random.randint(-50, 50)))
        depth_rows += f"""
        <tr>
            <td style="color:#00e676;font-family:JetBrains Mono,monospace;font-size:0.78rem">{b_qty}</td>
            <td style="color:#00e676;font-family:JetBrains Mono,monospace;font-weight:700">{b_price}</td>
            <td style="color:#ff4757;font-family:JetBrains Mono,monospace;font-weight:700">{a_price}</td>
            <td style="color:#ff4757;font-family:JetBrains Mono,monospace;font-size:0.78rem">{a_qty}</td>
        </tr>
        """

    depth_html = f"""
    <table class="chain-table" style="width:100%">
        <thead>
            <tr>
                <th style="color:#00e676">BID QTY</th>
                <th style="color:#00e676">BID</th>
                <th style="color:#ff4757">ASK</th>
                <th style="color:#ff4757">ASK QTY</th>
            </tr>
        </thead>
        <tbody>{depth_rows}</tbody>
    </table>
    """
    st.markdown(depth_html, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────
# ROW 3 — TICK CHARTS
# ─────────────────────────────────────────────────────────────────
st.markdown("<br>", unsafe_allow_html=True)
st.markdown('<div class="section-header">📈 PRICE CHARTS — TICK BY TICK</div>', unsafe_allow_html=True)

chart_col1, chart_col2, chart_col3 = st.columns(3)

chart_configs = [
    ("NF_ATM",    "NIFTY SPOT",       "#ffd700"),
    ("NF_CE_24600", "24600 CE",       "#00e676"),
    ("NF_PE_24600", "24600 PE",       "#ff4757"),
]

for i, (token, label, color) in enumerate(chart_configs):
    history = list(st.session_state["tick_history"].get(token, deque()))
    col_ref = [chart_col1, chart_col2, chart_col3][i]

    with col_ref:
        if len(history) >= 2:
            times = [h[0] for h in history]
            prices = [h[1] for h in history]

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=times,
                y=prices,
                mode="lines",
                line=dict(color=color, width=1.5),
                fill="tozeroy",
                fillcolor=color.replace("#", "rgba(") + ",0.08)" if color.startswith("#") else f"rgba(0,200,100,0.08)",
                name=label
            ))

            fig.update_layout(
                title=dict(text=label, font=dict(family="JetBrains Mono", size=11, color=color), x=0.05),
                plot_bgcolor="#0a0e17",
                paper_bgcolor="#0d1526",
                font=dict(family="JetBrains Mono", color="#5a7a9a", size=9),
                margin=dict(l=40, r=10, t=30, b=30),
                height=180,
                xaxis=dict(showgrid=False, showticklabels=True, tickformat="%H:%M:%S",
                           tickfont=dict(size=7), linecolor="#1e3a5f"),
                yaxis=dict(showgrid=True, gridcolor="#0d1828", tickfont=dict(size=8),
                           linecolor="#1e3a5f"),
                showlegend=False,
                hovermode="x unified",
            )

            current_price = prices[-1] if prices else 0
            fig.add_annotation(
                x=times[-1], y=current_price,
                text=f" {current_price:.1f}",
                font=dict(color=color, size=10, family="JetBrains Mono"),
                showarrow=False, xanchor="left"
            )

            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        else:
            st.markdown(f'<div class="info-box" style="height:180px;display:flex;align-items:center;justify-content:center">Waiting for ticks: {label}</div>',
                        unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────
# ROW 4 — OI BAR CHART + POSITIONS
# ─────────────────────────────────────────────────────────────────
oi_col, pos_col = st.columns([2, 1])

with oi_col:
    st.markdown('<div class="section-header">📊 OPEN INTEREST DISTRIBUTION</div>', unsafe_allow_html=True)

    strikes_oi = [24300, 24400, 24500, 24600, 24700, 24800, 24900]
    ce_oi_vals = []
    pe_oi_vals = []
    for s in strikes_oi:
        ce_t = f"NF_CE_{s}"
        pe_t = f"NF_PE_{s}"
        ce_oi_vals.append(td.get(ce_t, {}).get("oi", random.randint(50000, 400000)))
        pe_oi_vals.append(td.get(pe_t, {}).get("oi", random.randint(50000, 400000)))

    fig_oi = go.Figure()
    fig_oi.add_trace(go.Bar(
        name="CE OI",
        x=[str(s) for s in strikes_oi],
        y=ce_oi_vals,
        marker_color="#00e676",
        opacity=0.85
    ))
    fig_oi.add_trace(go.Bar(
        name="PE OI",
        x=[str(s) for s in strikes_oi],
        y=pe_oi_vals,
        marker_color="#ff4757",
        opacity=0.85
    ))

    fig_oi.update_layout(
        barmode="group",
        plot_bgcolor="#0a0e17",
        paper_bgcolor="#0d1526",
        font=dict(family="JetBrains Mono", color="#5a7a9a", size=9),
        margin=dict(l=40, r=20, t=20, b=40),
        height=200,
        xaxis=dict(showgrid=False, linecolor="#1e3a5f", title="Strike",
                   title_font=dict(size=9), tickfont=dict(size=8)),
        yaxis=dict(showgrid=True, gridcolor="#0d1828", linecolor="#1e3a5f",
                   title="OI", title_font=dict(size=9), tickfont=dict(size=8)),
        legend=dict(font=dict(size=9), bgcolor="rgba(0,0,0,0)"),
        hovermode="x unified",
    )

    # ATM line
    atm_idx = strikes_oi.index(24600)
    fig_oi.add_vline(x=atm_idx, line=dict(color="#ffd700", width=1, dash="dash"),
                     annotation_text="ATM", annotation_font=dict(color="#ffd700", size=9))

    st.plotly_chart(fig_oi, use_container_width=True, config={"displayModeBar": False})


with pos_col:
    st.markdown('<div class="section-header">💼 POSITIONS P&L</div>', unsafe_allow_html=True)

    # Demo positions
    positions = [
        {"symbol": "NIFTY24600CE", "qty": 50, "avg": 88.5, "ltp": td.get("NF_CE_24600", {}).get("ltp", 95.0)},
        {"symbol": "NIFTY24500PE", "qty": 50, "avg": 35.0, "ltp": td.get("NF_PE_24500", {}).get("ltp", 30.0)},
    ]

    total_pnl = 0
    pos_rows = ""
    for p in positions:
        pnl = (p["ltp"] - p["avg"]) * p["qty"]
        total_pnl += pnl
        pnl_color = "#00e676" if pnl >= 0 else "#ff4757"
        pnl_arrow = "▲" if pnl >= 0 else "▼"
        pos_rows += f"""
        <tr>
            <td style="font-family:JetBrains Mono,monospace;font-size:0.72rem;color:#8ab8d8">{p["symbol"]}</td>
            <td style="font-family:JetBrains Mono,monospace;font-size:0.72rem">{p["qty"]}</td>
            <td style="font-family:JetBrains Mono,monospace;font-size:0.72rem;color:#5a7a9a">{p["avg"]:.1f}</td>
            <td style="font-family:JetBrains Mono,monospace;font-size:0.72rem">{p["ltp"]:.1f}</td>
            <td style="font-family:JetBrains Mono,monospace;font-size:0.78rem;color:{pnl_color};font-weight:700">{pnl_arrow} ₹{abs(pnl):.0f}</td>
        </tr>
        """

    total_color = "#00e676" if total_pnl >= 0 else "#ff4757"
    pos_html = f"""
    <table class="chain-table" style="width:100%">
        <thead>
            <tr><th>SYMBOL</th><th>QTY</th><th>AVG</th><th>LTP</th><th>P&L</th></tr>
        </thead>
        <tbody>
            {pos_rows}
            <tr style="border-top:1px solid #1e3a5f">
                <td colspan="4" style="font-family:JetBrains Mono,monospace;font-size:0.75rem;color:#5a7a9a;font-weight:700">TOTAL P&L</td>
                <td style="font-family:JetBrains Mono,monospace;font-weight:700;color:{total_color};font-size:0.9rem">
                    {"▲" if total_pnl >= 0 else "▼"} ₹{abs(total_pnl):.0f}
                </td>
            </tr>
        </tbody>
    </table>
    """
    st.markdown(pos_html, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────
# ROW 5 — SCRIP MASTER BROWSER (expandable)
# ─────────────────────────────────────────────────────────────────
if st.session_state.get("scrip_master") is not None:
    with st.expander("📂 Scrip Master Browser (NF)", expanded=False):
        df_sm = st.session_state["scrip_master"]
        search = st.text_input("Filter by symbol", placeholder="NIFTY", key="scrip_search")
        if search:
            df_sm = df_sm[df_sm.apply(
                lambda row: row.astype(str).str.contains(search.upper(), case=False).any(), axis=1
            )]
        st.dataframe(df_sm.head(200), use_container_width=True, height=300)


# ─────────────────────────────────────────────────────────────────
# FOOTER
# ─────────────────────────────────────────────────────────────────
st.markdown("<br>", unsafe_allow_html=True)
st.markdown("""
<div style="
    text-align:center;
    font-family:JetBrains Mono,monospace;
    font-size:0.65rem;
    color:#2a4a6a;
    padding:10px;
    border-top:1px solid #0d1828;
">
    SHAREKHAN LIVE TERMINAL &nbsp;|&nbsp; NSE F&O &nbsp;|&nbsp;
    For support: api@sharekhan.com &nbsp;|&nbsp;
    ⚠ Trading involves risk. Use at your own discretion.
</div>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────
# AUTO REFRESH
# ─────────────────────────────────────────────────────────────────
if st.session_state.get("auto_refresh", True):
    refresh_rate = st.session_state.get("refresh_rate", 1.0)
    time.sleep(refresh_rate)
    st.rerun()
