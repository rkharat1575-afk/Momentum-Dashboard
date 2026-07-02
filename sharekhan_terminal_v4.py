"""
SK TERMINAL v4.2 — STRIKES IN MULTIPLES OF 100
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import json, os, time, requests, threading
from datetime import datetime
from collections import deque, defaultdict
import options_math
import hm_engine

st.set_page_config(page_title="SK Terminal v4.2", page_icon="📈", layout="wide", initial_sidebar_state="expanded")

# Helper to load .env manually if python-dotenv is not installed
import os
if os.path.exists(".env"):
    with open(".env") as f:
        for line in f:
            if line.strip() and not line.strip().startswith("#") and "=" in line:
                key, val = line.strip().split("=", 1)
                os.environ[key.strip()] = val.strip()

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
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
        from datetime import datetime
        futures = futures[futures['expiry_dt'].dt.date >= datetime.now().date()]
        futures = futures.sort_values('expiry_dt')
        if not futures.empty:
            return f"NF{int(futures.iloc[0]['scripCode'])}"
    except Exception as e:
        pass
    return "NF62329"

FUTURES_TOKEN    = get_nifty_futures_token()
STRIKE_STEP      = 100  # Nifty strikes in multiples of 100

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for _ in range(3):
        try:
            r = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=5)
            if r.status_code == 200: break
        except:
            import time
            time.sleep(1)

def log_trade(direction, strike, opt_type, entry, sl, tgt1, tgt2, score, signals, ticks_ref=None, scrip_ref=None):
    """Log every signal to a fast CSV journal instead of locking Excel."""
    log_file = "trade_journal.csv"
    date_str = datetime.now().strftime("%d/%m/%Y")
    time_str = datetime.now().strftime("%H:%M:%S")

    # Find token for this strike
    token = ""
    for t, tick in (ticks_ref or {}).items():
        try:
            code = int("".join(filter(str.isdigit, t)))
            if code in (scrip_ref or {}):
                info = scrip_ref[code]
                if int(info["strike"]) == strike and info["optionType"] == opt_type:
                    token = t
                    break
        except: pass

    # Append to CSV
    row_data = {
        "Date": date_str, "Time": time_str, "Direction": direction, "Type": opt_type, "Strike": strike,
        "Entry": entry, "SL": sl, "Target1": tgt1, "Target2": tgt2, "Score": score,
        "15min High": "", "15min Low": "", "15min Close": "",
        "30min High": "", "30min Low": "", "30min Close": "",
        "45min High": "", "45min Low": "", "45min Close": "",
        "60min High": "", "60min Low": "", "60min Close": "",
        "Result": "OPEN", "Exit Price": "", "P&L": "", "Notes": "; ".join(signals[:2]),
        "15pt Audit (2H)": "TRACKING..."
    }
    
    import pandas as pd
    df_new = pd.DataFrame([row_data])
    try:
        if not os.path.exists(log_file):
            df_new.to_csv(log_file, index=False)
        else:
            df_new.to_csv(log_file, mode='a', header=False, index=False)
    except PermissionError:
        print("WARNING: trade_journal.csv is open in another program. Cannot append trade.")
        st.toast("⚠️ Please close trade_journal.csv in Excel so new trades can be recorded!")
    except Exception as e:
        print(f"Error logging trade: {e}")

    try:
        df_full = pd.read_csv(log_file)
        row_idx = len(df_full) - 1
    except:
        row_idx = 0

    st.session_state["active_trades"].append({
        "token":        token,
        "row":          row_idx,
        "trigger_time": datetime.now(),
        "entry":        entry,
        "high":         entry,
        "low":          entry,
        "direction":    direction,
        "hit_15_pt":    False
    })

def update_signal_tracker(ticks, scrip_map):
    """
    Track price of triggered options at 15/30/45/60 min intervals.
    Updates trade_journal.csv with High/Low/Close at each interval.
    """
    if not st.session_state.get("active_trades"):
        return

    log_file = "trade_journal.csv"
    if not os.path.exists(log_file):
        return

    now = datetime.now()
    updated = False
    
    import pandas as pd
    try:
        df = pd.read_csv(log_file)
    except:
        return

    for trade in st.session_state["active_trades"][:]:
        trigger_time = trade["trigger_time"]
        elapsed_min  = (now - trigger_time).total_seconds() / 60
        token        = trade["token"]
        row_idx      = trade["row"]

        curr_ltp = float(ticks.get(token, {}).get("ltp", 0))
        if curr_ltp == 0: continue

        entry = trade.get("entry", curr_ltp)

        trade["high"] = max(trade.get("high", curr_ltp), curr_ltp)
        trade["low"]  = min(trade.get("low",  curr_ltp), curr_ltp)

        if not trade.get("hit_15_pt") and curr_ltp >= entry + 15:
            trade["hit_15_pt"] = True
            if row_idx < len(df):
                df.at[row_idx, "15pt Audit (2H)"] = f"ACHIEVED ✅ ({int(elapsed_min)}m)"
                updated = True

        intervals = {15: "15min", 30: "30min", 45: "45min", 60: "60min"}
        for mins, prefix in intervals.items():
            key = f"done_{mins}"
            if elapsed_min >= mins and not trade.get(key):
                trade[key] = True
                if row_idx < len(df):
                    df.at[row_idx, f"{prefix} High"] = f"{trade['high']:.1f}"
                    df.at[row_idx, f"{prefix} Low"]  = f"{trade['low']:.1f}"
                    df.at[row_idx, f"{prefix} Close"]= f"{curr_ltp:.1f}"
                    trade["high"] = curr_ltp
                    trade["low"]  = curr_ltp
                    updated = True

        if elapsed_min >= 122:
            if row_idx < len(df):
                if not trade.get("hit_15_pt"):
                    df.at[row_idx, "15pt Audit (2H)"] = "MISSED ❌"
                df.at[row_idx, "Exit Price"] = f"{curr_ltp:.1f}"
                if curr_ltp >= entry + 15:
                    df.at[row_idx, "Result"] = "TGT1 HIT ✅"
                elif curr_ltp <= entry - 15:
                    df.at[row_idx, "Result"] = "SL HIT ❌"
                else:
                    df.at[row_idx, "Result"] = "CLOSED ⌛"
                updated = True
            st.session_state["active_trades"].remove(trade)

    if updated:
        try:
            df.to_csv(log_file, index=False)
        except: pass

def log_hm_sniper_trade(strike, opt_type, entry, ticks_ref=None, scrip_ref=None):
    """Log strictly HM SNIPER trades with fixed +/- 10pt logic"""
    log_file = "HM SNIPER PROFIT OR LOSS FILE.csv"
    date_str = datetime.now().strftime("%d/%m/%Y")
    time_str = datetime.now().strftime("%H:%M:%S")

    # Find token for this strike
    token = ""
    for t, tick in (ticks_ref or {}).items():
        try:
            code = int("".join(filter(str.isdigit, t)))
            if code in (scrip_ref or {}):
                info = scrip_ref[code]
                if int(info["strike"]) == strike and info["optionType"] == opt_type:
                    token = t
                    break
        except: pass

    tgt = round(entry + 10, 1)
    sl = round(entry - 10, 1)

    row_data = {
        "Date": date_str, "Time": time_str, "Strike": strike, "CE/PE": opt_type,
        "Entry Price": entry, "Target": tgt, "Stop Loss": sl, 
        "Status": "PENDING", "P&L": ""
    }
    
    import pandas as pd
    df_new = pd.DataFrame([row_data])
    try:
        if not os.path.exists(log_file):
            df_new.to_csv(log_file, index=False)
        else:
            df_new.to_csv(log_file, mode='a', header=False, index=False)
    except PermissionError:
        print(f"WARNING: {log_file} is open in another program.")
        st.toast(f"⚠️ Please close {log_file} in Excel!")
    except Exception as e:
        print(f"Error logging HM sniper: {e}")

    try:
        df_full = pd.read_csv(log_file)
        row_idx = len(df_full) - 1
    except:
        row_idx = 0

    st.session_state["hm_active_trades"].append({
        "token":   token,
        "row":     row_idx,
        "entry":   entry,
        "target":  tgt,
        "sl":      sl
    })

def update_hm_sniper_tracker(ticks):
    """Track strictly +/- 10pt for HM Sniper trades"""
    if not st.session_state.get("hm_active_trades"):
        return

    log_file = "HM SNIPER PROFIT OR LOSS FILE.csv"
    if not os.path.exists(log_file):
        return

    updated = False
    import pandas as pd
    try:
        df = pd.read_csv(log_file)
    except:
        return

    for trade in st.session_state["hm_active_trades"][:]:
        token   = trade["token"]
        row_idx = trade["row"]
        entry   = trade["entry"]
        target  = trade["target"]
        sl      = trade["sl"]

        curr_ltp = float(ticks.get(token, {}).get("ltp", 0))
        if curr_ltp == 0: continue

        if curr_ltp >= target:
            if row_idx < len(df):
                df.at[row_idx, "Status"] = "TARGET ACHIEVED"
                df.at[row_idx, "P&L"] = "+10"
                updated = True
            st.session_state["hm_active_trades"].remove(trade)
        elif curr_ltp <= sl:
            if row_idx < len(df):
                df.at[row_idx, "Status"] = "FAILED"
                df.at[row_idx, "P&L"] = "-10"
                updated = True
            st.session_state["hm_active_trades"].remove(trade)

    if updated:
        try:
            df.to_csv(log_file, index=False)
        except: pass

def play_alert():
    try:
        import winsound
        for _ in range(3):
            winsound.Beep(1000, 300)
            time.sleep(0.1)
    except: pass

def send_signal_alert(direction, score, signals, strike, ltp, opt_type, sl, tgt1, tgt2):
    emoji = "🟢" if "BULL" in direction else "🔴"
    msg = f"""{emoji} NIFTY SIGNAL — {direction}
━━━━━━━━━━━━━━━━━━━
Trade : BUY {opt_type} {strike}
Entry : {ltp:.1f}
SL    : {sl:.1f}
Tgt 1 : {tgt1:.1f}
Tgt 2 : {tgt2:.1f}
Time  : {datetime.now().strftime('%H:%M:%S')}
Score : {score:+d}
━━━━━━━━━━━━━━━━━━━
""" + "\n".join(f"• {s}" for s in signals[:3])
    threading.Thread(target=send_telegram, args=(msg,), daemon=True).start()
    threading.Thread(target=play_alert, daemon=True).start()

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&display=swap');
html,body,[class*="css"]{background:#0a0e17!important;color:#e0e6f0!important;}
.stApp{background:#0a0e17!important;}
section[data-testid="stSidebar"]{background:#080d16!important;border-right:1px solid #1e3a5f!important;}
.metric-card{background:#0d1526;border:1px solid #1e3a5f;border-radius:6px;padding:10px 14px;margin:3px 0;}
.metric-label{font-family:'JetBrains Mono',monospace;font-size:0.65rem;color:#5a7a9a;text-transform:uppercase;letter-spacing:1.5px;}
.metric-value{font-family:'JetBrains Mono',monospace;font-size:1.3rem;font-weight:700;}
.section-hdr{font-family:'JetBrains Mono',monospace;font-size:0.68rem;color:#00d4ff;text-transform:uppercase;letter-spacing:2px;padding:5px 0;border-bottom:1px solid #1e3a5f;margin-bottom:10px;}
.chain-tbl{width:100%;border-collapse:collapse;font-family:'JetBrains Mono',monospace;font-size:0.76rem;}
.chain-tbl th{background:#0d1e35;color:#5a9abf;padding:7px 10px;text-align:center;font-size:0.64rem;text-transform:uppercase;border-bottom:1px solid #1e3a5f;}
.chain-tbl td{padding:6px 10px;text-align:center;border-bottom:1px solid #0d1828;}
.chain-tbl tr:hover td{background:#0d1e35;}
.ce-col{color:#00e676;}.pe-col{color:#ff4757;}.strike-col{color:#ffd700;font-weight:700;background:#0d1828!important;}
.atm-strike td{background:#1a1200!important;border-top:1px solid #554400;border-bottom:1px solid #554400;}
.signal-bull{background:#003d1e;border:1px solid #00e676;border-radius:4px;padding:8px 12px;font-family:'JetBrains Mono',monospace;color:#00e676;margin:4px 0;}
.signal-bear{background:#3d0000;border:1px solid #ff4757;border-radius:4px;padding:8px 12px;font-family:'JetBrains Mono',monospace;color:#ff4757;margin:4px 0;}
.signal-neut{background:#1a1a00;border:1px solid #ffd700;border-radius:4px;padding:8px 12px;font-family:'JetBrains Mono',monospace;color:#ffd700;margin:4px 0;}
.info-box{background:#0d1e35;border:1px solid #1e3a5f;border-left:3px solid #00d4ff;border-radius:4px;padding:8px 14px;font-family:'JetBrains Mono',monospace;font-size:0.76rem;color:#8ab8d8;margin:6px 0;}
.live-badge{display:inline-block;background:#003d1e;color:#00e676;border:1px solid #00e676;border-radius:4px;padding:2px 10px;font-family:'JetBrains Mono',monospace;font-size:0.72rem;font-weight:700;}
.dead-badge{display:inline-block;background:#3d0000;color:#ff4757;border:1px solid #ff4757;border-radius:4px;padding:2px 10px;font-family:'JetBrains Mono',monospace;font-size:0.72rem;font-weight:700;}
.stButton>button{background:#0d2a4a!important;color:#00d4ff!important;border:1px solid #1e3a5f!important;border-radius:4px!important;font-family:'JetBrains Mono',monospace!important;}
::-webkit-scrollbar{width:4px;}.chain-tbl tr:hover td{background:#0d1e35;}
</style>
""", unsafe_allow_html=True)

for k,v in {
    "tick_history":  defaultdict(lambda: deque(maxlen=300)),
    "pcr_history":   deque(maxlen=100),
    "scrip_map":     {},
    "oi_prev":       {},
    "last_signal":   "",
    "last_alert_time": 0,
    "active_trades":  [],   # List of trades being tracked
    "day_open_oi":    {},   # OI snapshot at 9:15 AM for COI calculation
    "market_opened":  False,
    "max_pain_cache": {},
    "pcr_coi_history":  deque(maxlen=100),
    "futures_history":   deque(maxlen=20),
    "signal_history":    deque(maxlen=10),
    "signal_scores":     deque(maxlen=20),  # Track confidence over time
    "vix_history":       deque(maxlen=100),
    "scalper_ce":        deque(maxlen=60),  # 1-min scalper data
    "scalper_pe":        deque(maxlen=60),
    "vwap_data":         defaultdict(lambda: {"prev_vol": 0, "recent_vols": deque(maxlen=20), "vwap": 0, "is_spike": False}),
    "hm_pending":        None,              # Tracks active pullback signal
    "hm_active_trades":  [],                # Tracks executed HM Sniper trades for strict +/- 10pt
}.items():
    if k not in st.session_state: st.session_state[k] = v

def load_scrip_map():
    if os.path.exists("nf_scrip_master_expanded.csv"):
        try:
            df=pd.read_csv("nf_scrip_master_expanded.csv")
            smap={}
            for _,row in df.iterrows():
                try:
                    code=int(row["scripCode"])
                    smap[code]={"strike":float(row["strike"]),"optionType":str(row["optionType"]),"expiry":str(row["expiry"]),"symbol":str(row["tradingSymbol"])}
                except: pass
            return smap
        except: return {}
    return {}

def read_live_ticks():
    if not os.path.exists("live_ticks.json"): return {},False
    try:
        age=time.time()-os.path.getmtime("live_ticks.json")
        with open("live_ticks.json") as f: ticks=json.load(f)
        return ticks,age<120
    except: return {},False

def process_whale_signals(ticks):
    if not ticks: return
    vwap_state = st.session_state["vwap_data"]
    for token, tick in ticks.items():
        try:
            ltp = float(tick.get("ltp", 0))
            total_vol = int(tick.get("qty", 0))
            if ltp == 0 or total_vol == 0: continue
            
            state = vwap_state[token]
            prev_vol = state["prev_vol"]
            tick_vol = max(0, total_vol - prev_vol)
            
            if tick_vol > 0:
                state["recent_vols"].append(tick_vol)
                
            state["prev_vol"] = total_vol
            
            # The exchange 'avgPrice' is the true mathematically perfect VWAP from 9:15 AM
            state["vwap"] = float(tick.get("avgPrice", ltp))
            
            avg_vol = sum(state["recent_vols"]) / len(state["recent_vols"]) if len(state["recent_vols"]) > 0 else 0
            state["is_spike"] = (avg_vol > 0 and tick_vol > (avg_vol * 3))
        except: pass

def build_chain(ticks,scrip_map,expiry_filter=None):
    chain={}
    for token,tick in ticks.items():
        try:
            code=int(''.join(filter(str.isdigit,token)))
            if code not in scrip_map: continue
            info=scrip_map[code]
            if expiry_filter and info["expiry"]!=expiry_filter: continue
            strike=int(info["strike"])
            opt=info["optionType"]
            if opt not in("CE","PE"): continue
            if strike not in chain: chain[strike]={}
            chain[strike][opt]=tick
        except: pass
    return chain

def get_expiries(ticks,scrip_map):
    expiries=set()
    for token in ticks:
        try:
            code=int(''.join(filter(str.isdigit,token)))
            if code in scrip_map: expiries.add(scrip_map[code]["expiry"])
        except: pass
    return sorted(expiries)

def classify_oi(strike, opt, tick):
    """
    NK Sir / CA Nitin Murarka COI Methodology:
    LBU = Long Buildup  : Price↑ OI↑ → Bullish
    SBU = Short Buildup : Price↓ OI↑ → Bearish  
    SC  = Short Covering: Price↑ OI↓ → Bullish
    LU  = Long Unwinding: Price↓ OI↓ → Bearish
    
    Significance tiers based on OI change %:
    MILD     < 2%
    STRONG   2-5%
    CRITICAL > 5%
    """
    key  = f"{opt}_{strike}"
    prev = st.session_state["oi_prev"].get(key, {})
    curr_ltp = float(tick.get("ltp", 0))
    curr_oi  = float(tick.get("currentOI", 0))
    prev_ltp = float(prev.get("ltp", curr_ltp))
    prev_oi  = float(prev.get("oi",  curr_oi))
    st.session_state["oi_prev"][key] = {"ltp": curr_ltp, "oi": curr_oi}

    if curr_ltp == prev_ltp and curr_oi == prev_oi:
        return "─", 0, "NONE"

    price_up = curr_ltp > prev_ltp
    oi_up    = curr_oi  > prev_oi

    # OI change percentage for significance
    oi_chg_pct = abs(curr_oi - prev_oi) / prev_oi * 100 if prev_oi > 0 else 0

    if oi_chg_pct < 0.1:
        return "─", 0, "NONE"

    tier = "CRITICAL" if oi_chg_pct > 5 else "STRONG" if oi_chg_pct > 2 else "MILD"
    tier_sym = "🔥" if tier == "CRITICAL" else "⚡" if tier == "STRONG" else ""

    if price_up and oi_up:
        return f"{tier_sym}🟢LBU", 1, tier   # Long Buildup — Bullish
    elif not price_up and oi_up:
        return f"{tier_sym}🔴SBU", -1, tier  # Short Buildup — Bearish
    elif price_up and not oi_up:
        return f"{tier_sym}🔵SC",  1, tier   # Short Covering — Bullish
    else:
        return f"{tier_sym}🟡LU",  -1, tier  # Long Unwinding — Bearish


def get_coi_score(chain, atm_strike):
    """Calculate overall COI score from ATM ±3 strikes."""
    score = 0
    signals = []
    for strike in sorted(chain.keys()):
        if abs(strike - atm_strike) > 300: continue
        ce = chain[strike].get("CE", {})
        pe = chain[strike].get("PE", {})
        ce_sig, ce_val, ce_tier = classify_oi(strike, "CE", ce)
        pe_sig, pe_val, pe_tier = classify_oi(strike, "PE", pe)

        # CE signals: LBU/SC on CE = Bullish for market
        if ce_val != 0 and ce_tier != "NONE":
            weight = 3 if ce_tier=="CRITICAL" else 2 if ce_tier=="STRONG" else 1
            score += ce_val * weight
            if ce_tier in ("STRONG","CRITICAL"):
                signals.append(f"CE {strike}: {ce_sig} ({ce_tier})")

        # PE signals: SBU on PE = Bullish (put writers adding), LBU on PE = Bearish
        if pe_val != 0 and pe_tier != "NONE":
            weight = 3 if pe_tier=="CRITICAL" else 2 if pe_tier=="STRONG" else 1
            score -= pe_val * weight  # PE inverse
            if pe_tier in ("STRONG","CRITICAL"):
                signals.append(f"PE {strike}: {pe_sig} ({pe_tier})")

    return score, signals[:4]

def capture_day_open_oi(ticks):
    """
    Capture OI snapshot at market open (9:15-9:25 AM) for ALL tokens.
    COI = Current OI - Opening OI. Tracking by token prevents bugs if expiry changes mid-day.
    """
    now = datetime.now()
    market_open_time = now.replace(hour=9, minute=15, second=0)
    capture_end_time = now.replace(hour=9, minute=25, second=0)

    if market_open_time <= now <= capture_end_time and not st.session_state["market_opened"]:
        snapshot = {}
        for token, tick in ticks.items():
            snapshot[token] = {
                "OI": float(tick.get("currentOI", 0)),
                "LTP": float(tick.get("ltp", 0)),
            }
        if snapshot:
            st.session_state["day_open_oi"]   = snapshot
            st.session_state["market_opened"] = True
            print(f"✅ Day open OI captured for all tokens at {now.strftime('%H:%M:%S')}")


def get_coi_from_open(chain, strike, opt_type):
    """
    Change in OI from day open — NK Sir methodology.
    Returns: (coi_value, coi_pct, direction_label)
    """
    open_snap = st.session_state.get("day_open_oi", {})
    tick = chain.get(strike, {}).get(opt_type, {})
    token = f"{tick.get('exchangeCode', 'NF')}{int(tick.get('scripCode', 0))}"
    
    if not open_snap or token not in open_snap:
        return 0, 0, "─"

    curr_oi = float(tick.get("currentOI", 0))
    open_oi = float(open_snap[token].get("OI", curr_oi))
    curr_ltp = float(tick.get("ltp", 0))
    open_ltp = float(open_snap[token].get("LTP", curr_ltp))

    coi = curr_oi - open_oi
    coi_pct = (coi / open_oi * 100) if open_oi > 0 else 0

    price_up = curr_ltp > open_ltp
    oi_up    = coi > 0

    if abs(coi_pct) < 0.5: return coi, coi_pct, "─"

    tier = "🔥" if abs(coi_pct)>10 else "⚡" if abs(coi_pct)>5 else ""

    if price_up and oi_up:       return coi, coi_pct, f"{tier}🟢LBU"
    elif not price_up and oi_up: return coi, coi_pct, f"{tier}🔴SBU"
    elif price_up and not oi_up: return coi, coi_pct, f"{tier}🔵SC"
    else:                        return coi, coi_pct, f"{tier}🟡LU"


def calculate_max_pain(chain):
    """
    Max Pain = Strike where total option sellers lose minimum.
    = Strike where sum of (|strike - S| * OI) is minimum for all S.
    """
    strikes = sorted(chain.keys())
    if len(strikes) < 3:
        return 0

    min_pain = float('inf')
    max_pain_strike = strikes[0]

    for test_strike in strikes:
        total_pain = 0
        for s in strikes:
            ce_oi = float(chain[s].get("CE",{}).get("currentOI",0))
            pe_oi = float(chain[s].get("PE",{}).get("currentOI",0))
            # CE pain: if test_strike > s, CE expires ITM
            if test_strike > s:
                total_pain += (test_strike - s) * ce_oi
            # PE pain: if test_strike < s, PE expires ITM
            if test_strike < s:
                total_pain += (s - test_strike) * pe_oi

        if total_pain < min_pain:
            min_pain = total_pain
            max_pain_strike = test_strike

    return max_pain_strike


def calculate_pcr_coi(chain):
    """
    PCR based on Change in OI (more dynamic than total OI PCR).
    PCR(COI) = Sum of PE COI / Sum of CE COI across all strikes.
    """
    open_snap = st.session_state.get("day_open_oi", {})
    if not open_snap:
        return 0

    total_ce_coi = 0
    total_pe_coi = 0

    for strike in chain:
        ce_tick = chain[strike].get("CE", {})
        pe_tick = chain[strike].get("PE", {})
        ce_token = f"{ce_tick.get('exchangeCode', 'NF')}{int(ce_tick.get('scripCode', 0))}"
        pe_token = f"{pe_tick.get('exchangeCode', 'NF')}{int(pe_tick.get('scripCode', 0))}"
        
        if ce_token not in open_snap or pe_token not in open_snap: continue
        
        curr_ce_oi = float(ce_tick.get("currentOI",0))
        curr_pe_oi = float(pe_tick.get("currentOI",0))
        open_ce_oi = float(open_snap[ce_token].get("OI",curr_ce_oi))
        open_pe_oi = float(open_snap[pe_token].get("OI",curr_pe_oi))

        ce_coi = curr_ce_oi - open_ce_oi
        pe_coi = curr_pe_oi - open_pe_oi

        if ce_coi > 0: total_ce_coi += ce_coi
        if pe_coi > 0: total_pe_coi += pe_coi

    return round(total_pe_coi / total_ce_coi, 2) if total_ce_coi > 0 else 0


def get_price_trend():
    """
    Detect Nifty trend from last 5 futures price points.
    Returns: UPTREND / DOWNTREND / SIDEWAYS
    """
    history = list(st.session_state.get("futures_history", []))
    if len(history) < 3:
        return "SIDEWAYS", 0

    prices = [h[1] for h in history[-5:]]
    # Linear trend: compare first half vs second half
    mid = len(prices) // 2
    avg_first = sum(prices[:mid]) / mid if mid > 0 else prices[0]
    avg_last  = sum(prices[mid:]) / (len(prices)-mid)
    change    = avg_last - avg_first
    change_pct = (change / avg_first * 100) if avg_first > 0 else 0

    if change_pct > 0.15:   return "UPTREND",   round(change_pct, 2)
    elif change_pct < -0.15: return "DOWNTREND", round(change_pct, 2)
    else:                    return "SIDEWAYS",  round(change_pct, 2)


def score_strike(chain, strike, opt_type, atm_strike, futures_ltp, selected_expiry):
    """
    SCALPER SCORING:
    Prioritizes Momentum, Institutional Spikes, Delta > 0.45, and High Gamma.
    """
    tick = chain.get(strike, {}).get(opt_type, {})
    if not tick: return 0, {}

    ltp    = float(tick.get("ltp", 0))
    vol    = float(tick.get("qty", 0))
    bid    = float(tick.get("bidPrice", 0))
    ask    = float(tick.get("offPrice", ltp))
    
    # 0. Volume Filter: Reject illiquid strikes
    if ltp < 15 or vol == 0: return 0, {} # Too deep OTM or no volume

    score = 0
    token = f"{tick.get('exchangeCode', 'NF')}{int(tick.get('scripCode', 0))}"
    vwap_info = st.session_state["vwap_data"].get(token, {})
    vwap = vwap_info.get("vwap", 0)
    is_spike = vwap_info.get("is_spike", False)

    # 1. Scalper Core Trigger: LTP must be above Option's VWAP
    if vwap > 0:
        if ltp > vwap: score += 40
        else: score -= 20 # Negative penalty if fighting option VWAP
        
        # 2. Institutional Spike confirmation
        if is_spike and ltp > vwap: score += 30

    # 3. Spread (Scalpers need tight spreads)
    spread_pct = ((ask - bid) / ltp * 100) if ltp > 0 else 100
    if spread_pct < 1.0: score += 10
    elif spread_pct > 3.0: return 0, {} # Reject if spread is too wide

    # 4. Options Math: Greeks & Microstructure
    T = options_math.calculate_time_to_expiry(selected_expiry)
    S = futures_ltp if futures_ltp > 0 else atm_strike
    
    iv = options_math.calculate_implied_volatility(S, strike, T, options_math.RISK_FREE_RATE, ltp, opt_type)
    delta, gamma = options_math.calculate_greeks(S, strike, T, options_math.RISK_FREE_RATE, iv, opt_type)
    
    # Delta sweet spot for scalping is 0.45 to 0.65 (ATM / slightly ITM)
    abs_delta = abs(delta)
    if 0.45 <= abs_delta <= 0.65:
        score += 20
    elif 0.35 <= abs_delta < 0.45:
        score += 5
        
    # Gamma Scoring (Explosiveness)
    gamma_score = options_math.score_gamma(gamma, ltp)
    score += gamma_score
        
    ratio, imb_str, imb_score = options_math.get_order_book_imbalance(tick)
    score += imb_score
    
    greeks = {"delta": delta, "gamma": gamma, "iv": iv, "imbalance": imb_str, "vwap": vwap, "is_spike": is_spike}
    return round(min(100, max(0, score))), greeks


def get_time_filter():
    """
    Professional time-of-day filter.
    Avoid trading in first 20 min and last 30 min.
    """
    now = datetime.now()
    t   = now.hour * 60 + now.minute

    if t < 9*60+20:   return "AVOID", "⚠ Pre-market / First 20 min — Wait for settlement"
    if t > 15*60:     return "AVOID", "⚠ Last 30 min — Avoid new trades"
    if 12*60 <= t <= 13*60+30: return "CAUTION", "⚡ Choppy Zone / Lunch hour — Strict criteria"
    return "TRADE",   "✅ Optimal trading window"


def find_best_strike(chain, direction, atm_strike, futures_ltp, selected_expiry):
    """
    Scalping Strike Selector:
    Only CE for Bullish, PE for Bearish.
    Looks for ATM or slightly ITM options for delta > 0.45.
    """
    opt_type = "CE" if "BULL" in direction else "PE"
    candidates = []

    strikes_to_check = sorted(chain.keys())
    for s in strikes_to_check:
        # For Scalping, check ATM and 2 ITM strikes for high delta
        if opt_type == "CE" and (s > atm_strike or s < atm_strike - STRIKE_STEP*2): continue
        if opt_type == "PE" and (s < atm_strike or s > atm_strike + STRIKE_STEP*2): continue

        ltp = float(chain.get(s,{}).get(opt_type,{}).get("ltp",0))
        if ltp < 30: continue  # Need premium for scalping margin

        sc, greeks = score_strike(chain, s, opt_type, atm_strike, futures_ltp, selected_expiry)
        candidates.append((s, ltp, sc, greeks))

    if not candidates: return 0, 0, opt_type, 0, {}

    # Sort by score descending
    candidates.sort(key=lambda x: x[2], reverse=True)
    best = candidates[0]
    return best[0], best[1], opt_type, best[2], best[3]


# ── VIX TOKEN (India VIX scrip code in NF exchange) ─────────────
VIX_TOKEN = "NC26023"  # India VIX token — update if needed

def get_vix(ticks):
    """Get India VIX from live ticks."""
    vix = float(ticks.get(VIX_TOKEN, {}).get("ltp", 0))
    if vix == 0:
        # Try common VIX scrip codes
        for t in ["NC26023","NF26023","NC26017"]:
            v = float(ticks.get(t,{}).get("ltp",0))
            if 8 < v < 100:
                return round(v, 2)
    return round(vix, 2) if 8 < vix < 100 else 0


def calculate_iv_estimate(ltp, strike, futures_price, days_to_expiry=7):
    """
    Quick IV estimate using simplified Black-Scholes approximation.
    Good enough for relative comparison between strikes.
    """
    try:
        import math
        if ltp <= 0 or futures_price <= 0 or days_to_expiry <= 0:
            return 0
        t = days_to_expiry / 365
        atm_price = futures_price
        # Brenner-Subrahmanyam approximation
        iv = (ltp / atm_price) * math.sqrt(2 * math.pi / t)
        return round(iv * 100, 1)  # as percentage
    except:
        return 0


def get_signal_confidence(score, coi_score, pcr, trend, trend_pct, vix, time_status):
    """
    Confidence score 0-100 for signal.
    Professional traders only trade >60% confidence.
    """
    confidence = 0

    # Base from OI score (max 30)
    confidence += min(30, abs(score) * 7)

    # COI confirmation (max 25)
    confidence += min(25, abs(coi_score) * 5)

    # PCR alignment (max 15)
    if pcr > 1.1 and score > 0:   confidence += 15
    elif pcr < 0.8 and score < 0: confidence += 15
    elif 0.9 < pcr < 1.1:         confidence += 5

    # Trend alignment (max 15)
    if trend == "UPTREND"   and score > 0: confidence += 15
    elif trend == "DOWNTREND" and score < 0: confidence += 15
    elif trend == "SIDEWAYS": confidence += 3

    # VIX filter (max 15)
    if 0 < vix < 15:    confidence += 15  # Low VIX — good for buying
    elif 15 <= vix < 20: confidence += 10  # Moderate
    elif 20 <= vix < 25: confidence += 5   # High — cautious
    elif vix >= 25:      confidence += 0   # Very high — avoid

    # Time penalty
    if time_status == "CAUTION": confidence -= 10
    if time_status == "AVOID":   confidence -= 30

    return max(0, min(100, round(confidence)))


def get_position_size(capital, ltp, lot_size=65):
    """
    Position sizing: Risk max 2% of capital per trade.
    SL = 40% of premium.
    """
    try:
        risk_per_trade = capital * 0.02  # 2% risk
        sl_per_lot     = ltp * 0.40 * lot_size
        lots           = int(risk_per_trade / sl_per_lot) if sl_per_lot > 0 else 1
        lots           = max(1, min(lots, 10))  # Min 1, Max 10 lots
        margin_needed  = ltp * lot_size * lots
        return lots, round(margin_needed)
    except:
        return 1, 0


def generate_signal(chain,atm,pcr):
    signals,score=[],0
    strikes=sorted(chain.keys())
    ce_ois={s:float(chain[s].get("CE",{}).get("currentOI",0)) for s in strikes}
    pe_ois={s:float(chain[s].get("PE",{}).get("currentOI",0)) for s in strikes}
    ce_wall=max(ce_ois,key=ce_ois.get) if ce_ois else atm
    pe_wall=max(pe_ois,key=pe_ois.get) if pe_ois else atm
    dist_ce=ce_wall-atm; dist_pe=atm-pe_wall
    if dist_pe<dist_ce and dist_pe>=0: signals.append(f"Spot near PE Wall {pe_wall} → Support"); score+=2
    elif dist_ce<dist_pe and dist_ce>=0: signals.append(f"Spot near CE Wall {ce_wall} → Resistance"); score-=1
    else: signals.append(f"CE Wall:{ce_wall} | PE Wall:{pe_wall}")
    atm_d=chain.get(atm,{})
    ce_atm=float(atm_d.get("CE",{}).get("currentOI",0))
    pe_atm=float(atm_d.get("PE",{}).get("currentOI",0))
    ratio=pe_atm/ce_atm if ce_atm else 1
    if ratio>1.3: signals.append(f"PE/CE ratio {ratio:.2f} → Put writers active (Bullish)"); score+=2
    elif ratio<0.7: signals.append(f"PE/CE ratio {ratio:.2f} → Call writers active (Bearish)"); score-=2
    else: signals.append(f"PE/CE ratio {ratio:.2f} → Neutral")
    if pcr>=1.2: signals.append(f"PCR {pcr:.2f} → Bullish"); score+=1
    elif pcr<=0.6: signals.append(f"PCR {pcr:.2f} → Bearish"); score-=1
    else: signals.append(f"PCR {pcr:.2f} → Neutral")
    ce_ab=sum(float(chain[s].get("CE",{}).get("currentOI",0)) for s in strikes if s>atm)
    pe_be=sum(float(chain[s].get("PE",{}).get("currentOI",0)) for s in strikes if s<atm)
    if pe_be>ce_ab*1.2: signals.append("Strong PE OI below → Support expected"); score+=1
    elif ce_ab>pe_be*1.2: signals.append("Strong CE OI above → Resistance expected"); score-=1
    if score>=3: d,css,em="BULLISH","signal-bull","🟢"
    elif score<=-3: d,css,em="BEARISH","signal-bear","🔴"
    elif score>=1: d,css,em="MILD BULLISH","signal-bull","🟡"
    elif score<=-1: d,css,em="MILD BEARISH","signal-bear","🟡"
    else: d,css,em="NEUTRAL","signal-neut","🟡"
    return d,css,em,signals,score

def fmt_qty(v):
    try:
        v=float(v)
        if v>=10_000_000: return f"{v/10_000_000:.1f}Cr"
        if v>=100_000: return f"{v/100_000:.1f}L"
        if v>=1_000: return f"{v/1_000:.1f}K"
        return str(int(v))
    except: return "0"

def chg_html(val):
    try:
        val=float(val)
        c="#00e676" if val>=0 else "#ff4757"
        a="▲" if val>=0 else "▼"
        return f'<span style="color:{c}">{a}{abs(val):.1f}%</span>'
    except: return "-"

# ── SIDEBAR ──────────────────────────────────────────────────────
with st.sidebar:
    st.markdown('<div style="font-family:JetBrains Mono,monospace;font-weight:700;color:#00d4ff;font-size:1.1rem;letter-spacing:2px">⚡ SK TERMINAL v4.2</div>', unsafe_allow_html=True)
    st.divider()
    ticks,is_live=read_live_ticks()
    if is_live and ticks: st.markdown(f'<span class="live-badge">● LIVE — {len(ticks)} tokens</span>',unsafe_allow_html=True)
    else:
        st.markdown('<span class="dead-badge">● OFFLINE — run tick_live.py</span>',unsafe_allow_html=True)
        st.markdown('<div class="info-box">Open new CMD:<br>cd C:\\sharekhan_terminal<br>python tick_live.py</div>',unsafe_allow_html=True)
    st.divider()
    if st.button("📥 Load Scrip Master"):
        st.session_state["scrip_map"]=load_scrip_map()
        st.success(f"Loaded {len(st.session_state['scrip_map'])} scrips")
    if not st.session_state["scrip_map"]: st.session_state["scrip_map"]=load_scrip_map()
    scrip_map=st.session_state["scrip_map"]
    if scrip_map: st.markdown(f'<div class="info-box">Scrip map: {len(scrip_map)} ✅</div>',unsafe_allow_html=True)
    st.divider()
    st.markdown('<div class="section-hdr">📅 EXPIRY FILTER</div>',unsafe_allow_html=True)
    avail_exp=get_expiries(ticks,scrip_map) if ticks and scrip_map else ["12/05/2026"]
    # Sort expiries by date and auto-select nearest
    try:
        avail_exp_sorted = sorted(avail_exp,
            key=lambda x: pd.to_datetime(x, dayfirst=True, errors="coerce"))
    except:
        avail_exp_sorted = avail_exp
    selected_expiry = st.selectbox("Select Expiry", avail_exp_sorted, index=0,
                                   help="Nearest expiry auto-selected")
    if avail_exp_sorted:
        st.markdown(f'<div class="info-box" style="font-size:0.65rem">✅ Nearest: {avail_exp_sorted[0]}</div>',unsafe_allow_html=True)
    st.markdown('<div class="section-hdr">🎯 STRIKES RANGE</div>',unsafe_allow_html=True)
    strikes_range=st.slider("Strikes each side of ATM",3,15,5)
    st.divider()
    st.markdown('<div class="section-hdr">📱 TELEGRAM ALERTS</div>',unsafe_allow_html=True)
    alerts_enabled=st.checkbox("Enable Alerts",value=True)
    alert_interval=st.slider("Min mins between alerts",5,60,15)
    if st.button("🔔 Test Alert"):
        send_telegram("✅ SK Terminal v4.2 — Test alert working!")
        st.success("Sent!")
    st.divider()
    auto_refresh=st.checkbox("Auto Refresh",value=True)
    refresh_rate=st.slider("Refresh (s)",5,60,30)
    st.divider()
    if ticks:
        st.markdown('<div style="font-family:JetBrains Mono,monospace;font-size:0.68rem;color:#5a7a9a">LIVE TICKS:</div>',unsafe_allow_html=True)
        for token,tick in list(ticks.items())[:5]:
            st.markdown(f'<div style="font-family:JetBrains Mono,monospace;font-size:0.65rem;color:#8ab8d8">{token}: <span style="color:#00e676">{tick.get("ltp",0)}</span> @ {tick.get("_ts","--")}</div>',unsafe_allow_html=True)

# ── MAIN ─────────────────────────────────────────────────────────
now=datetime.now()
mkt_open=now.replace(hour=9,minute=15)<=now<=now.replace(hour=15,minute=30)
chain=build_chain(ticks,scrip_map,selected_expiry) if ticks and scrip_map else {}
futures_ltp=float(ticks.get(FUTURES_TOKEN,{}).get("ltp",0)) if ticks else 0

# Process ticks for Whale Logic
if ticks: process_whale_signals(ticks)

# Capture day open OI at market open for all tokens
if ticks: capture_day_open_oi(ticks)

# Track futures price for trend detection
if futures_ltp > 0:
    st.session_state["futures_history"].append((datetime.now(), futures_ltp))

# Get VIX
vix = get_vix(ticks) if ticks else 0
if vix > 0: st.session_state["vix_history"].append((datetime.now(), vix))

# Calculate Max Pain + PCR(COI)
max_pain   = calculate_max_pain(chain) if chain else 0
pcr_coi    = calculate_pcr_coi(chain) if chain else 0
if pcr_coi: st.session_state["pcr_coi_history"].append((datetime.now(), pcr_coi))

# Get trend and time filter
trend, trend_pct   = get_price_trend()
time_status, time_msg = get_time_filter()

# ATM in multiples of 100
atm_strike=24000
if futures_ltp>0:
    atm_strike=round(futures_ltp/STRIKE_STEP)*STRIKE_STEP
elif chain:
    strikes=sorted(chain.keys())
    best_diff=float('inf')
    for s in strikes:
        ce_l=float(chain[s].get("CE",{}).get("ltp",0))
        pe_l=float(chain[s].get("PE",{}).get("ltp",0))
        if ce_l and pe_l:
            diff=abs(ce_l-pe_l)
            if diff<best_diff: best_diff=diff; atm_strike=s

st.markdown(f"""
<div style="background:linear-gradient(135deg,#0d1526,#091020);border:1px solid #1e3a5f;border-radius:6px;padding:12px 20px;margin-bottom:14px;display:flex;align-items:center;justify-content:space-between;">
  <span style="font-family:'JetBrains Mono',monospace;font-size:1.05rem;font-weight:700;color:#00d4ff;letter-spacing:2px">📈 SK TERMINAL v4.2 — NIFTY {selected_expiry}</span>
  <span style="font-family:'JetBrains Mono',monospace;font-size:0.76rem;color:#5a9abf">
    {now.strftime('%d %b %Y  %H:%M:%S')} &nbsp;|&nbsp; {'🟢 MARKET OPEN' if mkt_open else '🔴 MARKET CLOSED'} &nbsp;|&nbsp; {'🟢 LIVE' if (is_live and ticks) else '🟡 WAITING FOR tick_live.py'}
  </span>
</div>
""",unsafe_allow_html=True)

atm_ce=chain.get(atm_strike,{}).get("CE",{})
atm_pe=chain.get(atm_strike,{}).get("PE",{})
atm_ce_ltp=float(atm_ce.get("ltp",0))
atm_pe_ltp=float(atm_pe.get("ltp",0))
atm_ce_oi=float(atm_ce.get("currentOI",0))
atm_pe_oi=float(atm_pe.get("currentOI",0))
total_ce_oi=sum(float(chain[s].get("CE",{}).get("currentOI",0)) for s in chain)
total_pe_oi=sum(float(chain[s].get("PE",{}).get("currentOI",0)) for s in chain)
pcr=round(total_pe_oi/total_ce_oi,2) if total_ce_oi else 0
if pcr: st.session_state["pcr_history"].append((datetime.now(),pcr))
if atm_ce_ltp: st.session_state["scalper_ce"].append((datetime.now(), atm_ce_ltp))
if atm_pe_ltp: st.session_state["scalper_pe"].append((datetime.now(), atm_pe_ltp))
ce_ois_all={s:float(chain[s].get("CE",{}).get("currentOI",0)) for s in chain}
pe_ois_all={s:float(chain[s].get("PE",{}).get("currentOI",0)) for s in chain}
ce_wall=max(ce_ois_all,key=ce_ois_all.get) if ce_ois_all else "--"
pe_wall=max(pe_ois_all,key=pe_ois_all.get) if pe_ois_all else "--"
nc20000 = float(ticks.get("NC20000",{}).get("ltp",0)) if ticks else 0
spot_ltp = nc20000 if nc20000 > 20000 else (round(futures_ltp - 50, 2) if futures_ltp > 0 else 0)
pcr_color="#00e676" if pcr>=1.0 else "#ff4757" if pcr<0.7 else "#ffd700"
pcr_signal="BULLISH" if pcr>=1.0 else "BEARISH" if pcr<0.7 else "NEUTRAL"

# ATM always uses FUTURES price (correct for options pricing)
# Display both Spot and Futures

c1,c2,c3,c4,c5,c6=st.columns([2,1.3,1.3,1.3,1.3,1.3])
with c1:
    fut_color = "#ffd700"
    spot_color = "#00d4ff"
    st.markdown(f"""<div class="metric-card" style="border-left:3px solid #ffd700">
      <div class="metric-label">NIFTY FUTURES (ATM Reference)</div>
      <div style="font-family:'JetBrains Mono',monospace;font-size:1.9rem;font-weight:700;color:{fut_color}">{f"{futures_ltp:,.2f}" if futures_ltp else "Waiting..."}</div>
      <div style="font-family:'JetBrains Mono',monospace;font-size:0.82rem;color:{spot_color}">Spot: {f"{spot_ltp:,.2f}" if spot_ltp else "--"}</div>
      <div style="font-family:'JetBrains Mono',monospace;font-size:0.72rem;color:#5a7a9a">ATM:{atm_strike} | {selected_expiry}</div>
    </div>""",unsafe_allow_html=True)

for col,label,val,color,sub in [
    (c2,f"ATM CE ({atm_strike})",f"{atm_ce_ltp:.1f}" if atm_ce_ltp else "--","#00e676",f"OI:{fmt_qty(atm_ce_oi)}"),
    (c3,f"ATM PE ({atm_strike})",f"{atm_pe_ltp:.1f}" if atm_pe_ltp else "--","#ff4757",f"OI:{fmt_qty(atm_pe_oi)}"),
    (c4,"PCR (TOTAL OI)",f"{pcr:.2f}" if pcr else "--",pcr_color,pcr_signal),
    (c5,"MAX PAIN",str(max_pain) if max_pain else "--","#ff9900",f"CE Wall:{ce_wall}"),
    (c6,"INDIA VIX",f"{vix:.2f}" if vix else "--",
     "#00e676" if vix<15 else "#ffd700" if vix<20 else "#ff4757",
     "LOW✅" if vix<15 else "MID⚡" if vix<20 else "HIGH🔴"),
]:
    with col:
        st.markdown(f"""<div class="metric-card" style="border-left:3px solid {color}">
          <div class="metric-label">{label}</div>
          <div class="metric-value" style="color:{color}">{val}</div>
          <div style="font-family:'JetBrains Mono',monospace;font-size:0.64rem;color:#5a7a9a">{sub}</div>
        </div>""",unsafe_allow_html=True)

st.markdown("<br>",unsafe_allow_html=True)
sig_col,chain_col=st.columns([1,3])

with sig_col:
    st.markdown('<div class="section-hdr">🎯 SIGNAL ENGINE</div>',unsafe_allow_html=True)
    if chain:
        direction,css,emoji,signals,score=generate_signal(chain,atm_strike,pcr)
        coi_score, coi_signals = get_coi_score(chain, atm_strike)
        total_score = score + (1 if coi_score > 2 else -1 if coi_score < -2 else 0)

        # Re-evaluate with COI
        if total_score >= 3: fin_dir,fin_css,fin_em = "BULLISH","signal-bull","🟢"
        elif total_score <= -3: fin_dir,fin_css,fin_em = "BEARISH","signal-bear","🔴"
        elif total_score >= 1: fin_dir,fin_css,fin_em = "MILD BULLISH","signal-bull","🟡"
        elif total_score <= -1: fin_dir,fin_css,fin_em = "MILD BEARISH","signal-bear","🟡"
        else: fin_dir,fin_css,fin_em = direction,css,emoji

        # ── SCALPER GATEKEEPER ──
        futures_vwap = st.session_state["vwap_data"].get(FUTURES_TOKEN, {}).get("vwap", futures_ltp)
        futures_above_vwap = futures_ltp > futures_vwap if futures_vwap > 0 else True
        
        # Override OI direction if it fights immediate momentum
        if futures_above_vwap and trend != "DOWNTREND":
            fin_dir,fin_css,fin_em = "BULLISH (Scalp)","signal-bull","🟢"
        elif not futures_above_vwap and trend != "UPTREND":
            fin_dir,fin_css,fin_em = "BEARISH (Scalp)","signal-bear","🔴"
        else:
            fin_dir,fin_css,fin_em = "NEUTRAL (Chop)","signal-neut","🟡"

        # Calculate everything ONCE before display
        best_strike, best_ltp, best_type, strike_score, best_greeks = find_best_strike(chain, fin_dir, atm_strike, futures_ltp, selected_expiry)
        confidence = get_signal_confidence(total_score, coi_score, pcr, trend, trend_pct, vix, time_status)
        lots, margin = get_position_size(200000, best_ltp) if best_ltp > 0 else (1, 0)
        direction = fin_dir
        
        is_spike = best_greeks.get("is_spike", False)
        imbalance = best_greeks.get("imbalance", "NEUTRAL")

        st.markdown(f'<div class="{fin_css}"><b>{fin_em} {fin_dir}</b><br>OI Score: {score:+d} | COI Score: {coi_score:+d}</div>',unsafe_allow_html=True)
        
        # Confidence bar
        conf_c = "#00e676" if confidence>=70 else "#ffd700" if confidence>=50 else "#ff4757"
        conf_l = "🔥 HIGH" if confidence>=70 else "⚡ MED" if confidence>=50 else "⚠ LOW"
        st.markdown(f'<div style="font-family:JetBrains Mono,monospace;font-size:0.82rem;color:{conf_c};font-weight:700">Confidence: {confidence}% {conf_l}</div>',unsafe_allow_html=True)
        
        # Time + Trend + VIX inline
        tc = "#ff4757" if time_status=="AVOID" else "#ffd700" if time_status=="CAUTION" else "#00e676"
        tr_c = "#00e676" if trend=="UPTREND" else "#ff4757" if trend=="DOWNTREND" else "#ffd700"
        vix_c = "#00e676" if 0<vix<15 else "#ffd700" if vix<20 else "#ff4757"
        
        f_vwap_c = "#00e676" if futures_above_vwap else "#ff4757"
        st.markdown(f'<div style="font-family:JetBrains Mono,monospace;font-size:0.75rem;color:{f_vwap_c};font-weight:bold;margin-top:6px;border-bottom:1px solid #1e3a5f;padding-bottom:4px">FUTURES > VWAP: {"YES 🟢" if futures_above_vwap else "NO 🔴"}</div>',unsafe_allow_html=True)
        
        st.markdown(f'<div style="font-family:JetBrains Mono,monospace;font-size:0.68rem;color:{tc}">{time_msg}</div>',unsafe_allow_html=True)
        st.markdown(f'<div style="font-family:JetBrains Mono,monospace;font-size:0.68rem;color:{tr_c}">Trend: {trend} ({trend_pct:+.2f}%)</div>',unsafe_allow_html=True)
        if vix>0: st.markdown(f'<div style="font-family:JetBrains Mono,monospace;font-size:0.68rem;color:{vix_c}">VIX: {vix:.2f}</div>',unsafe_allow_html=True)

        st.markdown("<br>",unsafe_allow_html=True)
        st.markdown('<div class="section-hdr">🎯 SCALPING STRIKE</div>',unsafe_allow_html=True)

        if best_strike>0 and "NEUTRAL" not in direction and time_status!="AVOID":
            # SCALPER TIGHT SL (15 pts) AND TARGETS
            iv_est_val = best_greeks.get("iv", 0.15) if best_greeks.get("iv", 0) > 0 else 0.15
            vix_hist = st.session_state.get("vix_history", [])
            vix_val = vix_hist[-1][1] if vix_hist and isinstance(vix_hist[-1], tuple) else (vix_hist[-1] if vix_hist else 15)
            sl, tgt1, tgt2 = options_math.calculate_dynamic_targets(best_ltp, iv_est_val, vix_val)
            
            css_trade = "signal-bull" if "BULL" in direction else "signal-bear"
            iv_est = round(best_greeks.get("iv", 0) * 100, 1)
            delta = round(best_greeks.get("delta", 0), 2)
            imbalance = best_greeks.get("imbalance", "NEUTRAL")
            
            vwap = best_greeks.get("vwap", 0)
            is_spike = best_greeks.get("is_spike", False)
            spike_text = "🐋 VOLUME SPIKE!" if is_spike else ""
            
            has_momentum = (best_ltp > vwap) if vwap > 0 else True
            
            if strike_score >= 60 and has_momentum:
                strength = "🔥 GREEN LIGHT (Momentum)"
            else:
                strength = "⚠ WAIT (No Option Momentum)"
                css_trade = "signal-neut"  # Downgrade visually if fighting momentum

            action_advice = ""
            if "BULL" in direction: # CE Trade
                if "BUY WALL" in imbalance: action_advice = "(🚀 IDEAL FOR CE)"
                elif "ABSORBING" in imbalance: action_advice = "(👍 GOOD FOR CE)"
                elif "SELL WALL" in imbalance: action_advice = "(⚠️ DANGER: AVOID CE)"
                elif "AGGRESSIVE" in imbalance: action_advice = "(⚠️ CAUTION)"
                else: action_advice = "(⚖️ WAIT FOR VOL)"
            else: # PE Trade
                if "SELL WALL" in imbalance: action_advice = "(🚀 IDEAL FOR PE)"
                elif "AGGRESSIVE" in imbalance: action_advice = "(👍 GOOD FOR PE)"
                elif "BUY WALL" in imbalance: action_advice = "(⚠️ DANGER: AVOID PE)"
                elif "ABSORBING" in imbalance: action_advice = "(⚠️ CAUTION)"
                else: action_advice = "(⚖️ WAIT FOR VOL)"

            st.markdown(f"""<div class="{css_trade}">
            <b>BUY {best_type} {best_strike}</b> {strength} <span style="color:#00d4ff">{spike_text}</span><br>
            Strike Score : {strike_score}/100<br>
            Δ Delta: {delta} | IV: {iv_est}%<br>
            Entry : {best_ltp:.1f} (Opt VWAP: {vwap:.1f})<br>
            SL    : {sl:.1f} (Max -15 pts)<br>
            Tgt 1 : {tgt1:.1f} (+10 pts Scalp)<br>
            Tgt 2 : {tgt2:.1f} (+20 pts)<br>
            Imbalance: {imbalance} <span style="color:#ffd700"><b>{action_advice}</b></span>
            </div>""",unsafe_allow_html=True)
        elif confidence < 60 and best_strike > 0:
            st.markdown(f'<div class="signal-neut">⚠ LOW CONFIDENCE ({confidence}%) — WAIT<br>Need ≥60% to trade</div>',unsafe_allow_html=True)
        elif time_status == "AVOID":
            st.markdown(f'<div class="signal-neut">⏳ {time_msg}</div>',unsafe_allow_html=True)
        else:
            st.markdown('<div class="signal-neut">WAIT — No clear signal</div>',unsafe_allow_html=True)

        # ── SIGNAL VALIDATION (Matches UI "GREEN LIGHT") ──
        vwap = best_greeks.get("vwap", 0)
        has_momentum = (best_ltp > vwap) if vwap > 0 else True
        is_whale_activity = is_spike or "BUY WALL" in imbalance or "ABSORBING" in imbalance
        
        is_valid_signal = (
            best_strike > 0 and 
            "NEUTRAL" not in direction and 
            time_status != "AVOID" and 
            confidence >= 60 and 
            strike_score >= 60 and 
            has_momentum
        )

        # Telegram alert + Trade Log
        if alerts_enabled and is_valid_signal:
            now_ts=time.time()
            sig_key=f"{direction}_{best_strike}_{best_type}"
            # Cooldown of 15 minutes (900 seconds) between alerts to prevent spam during a sustained move
            time_ok = (now_ts - st.session_state.get("last_alert_time", 0)) > 900
            
            if sig_key != st.session_state.get("last_signal", "") and time_ok and mkt_open:
                iv_est_val = best_greeks.get("iv", 0.15) if 'best_greeks' in locals() and best_greeks.get("iv", 0) > 0 else 0.15
                vix_hist = st.session_state.get("vix_history", [])
                vix_val = vix_hist[-1][1] if vix_hist and isinstance(vix_hist[-1], tuple) else (vix_hist[-1] if vix_hist else 15)
                sl, tgt1, tgt2 = options_math.calculate_dynamic_targets(best_ltp, iv_est_val, vix_val)
                send_signal_alert(direction,score,signals,best_strike,best_ltp,best_type,sl,tgt1,tgt2)
                log_trade(direction,best_strike,best_type,best_ltp,sl,tgt1,tgt2,score,signals,ticks,scrip_map)
                st.session_state["last_signal"]=sig_key
                st.session_state["last_alert_time"]=now_ts
                st.success(f"🔔 Alert sent! Logged to trade_journal.xlsx")
    else:
        st.markdown('<div class="info-box">Waiting for data...</div>',unsafe_allow_html=True)

    # --- Hilega Milega Engine (Isolated) ---
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown('<div class="section-hdr">🚀 HILEGA MILEGA ENGINE</div>', unsafe_allow_html=True)
    
    # Warmup History Fetch
    if "hm_warmup_df" not in st.session_state:
        st.session_state["hm_warmup_df"] = hm_engine.get_warmup_candles(is_bank_nifty=False)
        
    hist_ticks = list(st.session_state.get("futures_history", []))
    hm_df_live = hm_engine.resample_ticks_to_candles(hist_ticks, timeframe='5min')
    is_banknifty = False # Using Nifty currently
    
    hm_sig, hm_strike, hm_opt_type, hm_rsi, hm_wma, hm_ema, hm_sma = hm_engine.process_hm_logic(
        hm_df_live.copy() if not hm_df_live.empty else hm_df_live, 
        futures_ltp, 
        is_banknifty, 
        warmup_df=st.session_state["hm_warmup_df"]
    )
    
    total_candles = len(hm_df_live) + len(st.session_state["hm_warmup_df"])
    
    if total_candles < 22:
        st.markdown('<div class="info-box">⏳ Accumulating tick data for HM...</div>', unsafe_allow_html=True)
    else:
        
        if hm_sig == "BULLISH":
            hm_css = "signal-bull"
            hm_em = "🟢"
        elif hm_sig == "BEARISH":
            hm_css = "signal-bear"
            hm_em = "🔴"
        else:
            hm_css = "signal-neut"
            hm_em = "🟡"
            
        st.markdown(f'''<div class="{hm_css}">
        <b>{hm_em} {hm_sig}</b><br>
        RSI(9): {hm_rsi} | WMA(21): {hm_wma} | EMA(3): {hm_ema}<br>
        Target Strike: {hm_opt_type} {hm_strike} (Delta ~0.60)
        </div>''', unsafe_allow_html=True)
        
        # Hilega Milega Execution (Pullback Logic)
        if hm_sig != "NEUTRAL":
            hm_sig_key = f"HM_{hm_sig}_{hm_strike}_{hm_opt_type}"
            
            # 5-minute cooldown check before staging
            hm_time_ok = (time.time() - st.session_state.get("last_hm_alert_time", 0)) > 300
            
            # If we don't already have this signal pending AND cooldown is passed, stage it
            current_pending = st.session_state.get("hm_pending")
            if (not current_pending or current_pending["key"] != hm_sig_key) and hm_time_ok:
                st.session_state["hm_pending"] = {
                    "key": hm_sig_key,
                    "sig": hm_sig,
                    "strike": hm_strike,
                    "opt_type": hm_opt_type,
                    "sma": hm_sma,
                    "rsi": hm_rsi,
                    "wma": hm_wma,
                    "ema": hm_ema,
                    "staged_time": time.time()
                }
                # Initial Momentum Alert removed to reduce Telegram spam
                
        # Evaluate Pending Signal
        pending = st.session_state.get("hm_pending")
        if pending:
            # Check if trend reversed completely (cancel condition)
            if (pending["sig"] == "BULLISH" and hm_sig == "BEARISH") or \
               (pending["sig"] == "BEARISH" and hm_sig == "BULLISH"):
                st.session_state["hm_pending"] = None
                import threading
                threading.Thread(target=send_telegram, args=("❌ HM Signal Cancelled: Trend Reversed",), daemon=True).start()
            
            else:
                # Check for Pullback Execution (10-point buffer on futures_ltp)
                sma_target = pending["sma"]
                pullback_hit = False
                
                if pending["sig"] == "BULLISH" and futures_ltp <= (sma_target + 10):
                    pullback_hit = True
                elif pending["sig"] == "BEARISH" and futures_ltp >= (sma_target - 10):
                    pullback_hit = True
                    
                if pullback_hit:
                    # Execute ONLY if we have actual Option Premium data!
                    hm_opt_ltp = float(chain.get(int(pending["strike"]), {}).get(pending["opt_type"], {}).get("ltp", 0)) if chain else 0
                    
                    if hm_opt_ltp > 0:
                        entry_price = hm_opt_ltp
                        hm_sl = round(entry_price * 0.85, 1)
                        hm_tgt1 = round(entry_price * 1.20, 1)
                        hm_tgt2 = round(entry_price * 1.50, 1)
                        
                        log_trade(
                            direction=f"HM_{pending['sig']}",
                            strike=pending["strike"],
                            opt_type=pending["opt_type"],
                            entry=entry_price,
                            sl=hm_sl,
                            tgt1=hm_tgt1,
                            tgt2=hm_tgt2,
                            score=0,
                            signals=[f"RSI:{pending['rsi']}", f"WMA:{pending['wma']}", f"PULLBACK HIT"],
                            ticks_ref=ticks,
                            scrip_ref=scrip_map
                        )
                        
                        log_hm_sniper_trade(
                            strike=pending["strike"],
                            opt_type=pending["opt_type"],
                            entry=entry_price,
                            ticks_ref=ticks,
                            scrip_ref=scrip_map
                        )
                        
                        msg = f"🔥 HM SNIPER EXECUTED!\nTrade: BUY {pending['opt_type']} {pending['strike']}\nEntry: {entry_price}\nSL: {hm_sl}"
                        import threading
                        threading.Thread(target=send_telegram, args=(msg,), daemon=True).start()
                        st.success("🔥 HM Sniper Executed! Logged to trade_journal.csv")
                        
                        # Clear pending
                        st.session_state["hm_pending"] = None
                        st.session_state["last_hm_signal"] = pending["key"]
                        st.session_state["last_hm_alert_time"] = time.time()
                    
        # UI Display for pending state
        if pending:
            st.markdown(f'<div class="info-box">⏳ SNIPER WAITING: {pending["sig"]} {pending["opt_type"]} {pending["strike"]} to touch {pending["sma"]:.1f}</div>', unsafe_allow_html=True)

with chain_col:
    st.markdown('<div class="section-hdr">📋 LIVE OPTION CHAIN</div>',unsafe_allow_html=True)
    if not chain:
        st.markdown('<div class="info-box">⏳ Waiting for tick_live.py + scrip master...</div>',unsafe_allow_html=True)
    else:
        all_s=sorted(chain.keys())
        atm_idx=min(range(len(all_s)),key=lambda i:abs(all_s[i]-atm_strike))
        visible=all_s[max(0,atm_idx-strikes_range):atm_idx+strikes_range+1]
        rows=""
        for strike in sorted(visible,reverse=True):
            ce=chain[strike].get("CE",{}); pe=chain[strike].get("PE",{})
            is_atm=(strike==atm_strike); rc="atm-strike" if is_atm else ""
            ce_ltp=float(ce.get("ltp",0)); pe_ltp=float(pe.get("ltp",0))
            ce_oi=float(ce.get("currentOI",0)); pe_oi=float(pe.get("currentOI",0))
            ce_vol=float(ce.get("qty",0)); pe_vol=float(pe.get("qty",0))
            ce_bid=float(ce.get("bidPrice",0)); ce_ask=float(ce.get("offPrice",0))
            pe_bid=float(pe.get("bidPrice",0)); pe_ask=float(pe.get("offPrice",0))
            ce_open=float(ce.get("open",0)) or float(ce.get("close",0))
            pe_open=float(pe.get("open",0)) or float(pe.get("close",0))
            ce_chg=round((ce_ltp-ce_open)/ce_open*100,1) if ce_open and ce_ltp else 0
            pe_chg=round((pe_ltp-pe_open)/pe_open*100,1) if pe_open and pe_ltp else 0
            # Use COI from day open if available, else tick-to-tick
            if st.session_state.get("day_open_oi"):
                _,ce_coi_pct,ce_sig = get_coi_from_open(chain,strike,"CE")
                _,pe_coi_pct,pe_sig = get_coi_from_open(chain,strike,"PE")
                ce_coi_str = f"{ce_coi_pct:+.1f}%" if ce_coi_pct else "─"
                pe_coi_str = f"{pe_coi_pct:+.1f}%" if pe_coi_pct else "─"
            else:
                ce_sig,_,_ = classify_oi(strike,"CE",ce)
                pe_sig,_,_ = classify_oi(strike,"PE",pe)
                ce_coi_str = "─"
                pe_coi_str = "─"
            if ce_ltp: st.session_state["tick_history"][f"CE_{strike}"].append((datetime.now(),ce_ltp))
            if pe_ltp: st.session_state["tick_history"][f"PE_{strike}"].append((datetime.now(),pe_ltp))
            rows+=f"""<tr class="{rc}">
              <td class="ce-col">{fmt_qty(ce_oi)}</td>
              <td class="ce-col" style="font-size:0.68rem">{ce_sig}</td>
              <td class="ce-col" style="font-size:0.68rem">{ce_coi_str}</td>
              <td class="ce-col">{fmt_qty(ce_vol)}</td>
              <td class="ce-col">{chg_html(ce_chg)}</td>
              <td class="ce-col" style="font-weight:700">{ce_ltp:.1f}</td>
              <td class="ce-col" style="font-size:0.68rem">{ce_bid:.1f}/{ce_ask:.1f}</td>
              <td class="strike-col">{'⭐' if is_atm else ''}{strike}</td>
              <td class="pe-col" style="font-size:0.68rem">{pe_bid:.1f}/{pe_ask:.1f}</td>
              <td class="pe-col" style="font-weight:700">{pe_ltp:.1f}</td>
              <td class="pe-col">{chg_html(pe_chg)}</td>
              <td class="pe-col">{fmt_qty(pe_vol)}</td>
              <td class="pe-col" style="font-size:0.68rem">{pe_sig}</td>
              <td class="pe-col" style="font-size:0.68rem">{pe_coi_str}</td>
              <td class="pe-col">{fmt_qty(pe_oi)}</td>
            </tr>"""
        st.markdown(f"""<div style="overflow-x:auto"><table class="chain-tbl">
          <thead>
            <tr><th colspan="7" style="color:#00e676;background:#001a0d">── CALLS (CE) ──</th>
            <th style="color:#ffd700;background:#0a0800">STRIKE</th>
            <th colspan="7" style="color:#ff4757;background:#1a0000">── PUTS (PE) ──</th></tr>
            <tr><th>OI</th><th>SIG</th><th>COI%</th><th>VOL</th><th>CHG%</th><th>LTP</th><th>BID/ASK</th>
            <th></th><th>BID/ASK</th><th>LTP</th><th>CHG%</th><th>VOL</th><th>SIG</th><th>COI%</th><th>OI</th></tr>
          </thead><tbody>{rows}</tbody></table></div>""",unsafe_allow_html=True)

st.markdown("<br>",unsafe_allow_html=True)
st.markdown('<div class="section-hdr">📈 LIVE CHARTS</div>',unsafe_allow_html=True)
ch1,ch2,ch3=st.columns(3)
chart_configs = [
    ("scalper_ce", f"ATM CE {atm_strike} (Scalper)", "#00e676", "scalper"),
    ("scalper_pe", f"ATM PE {atm_strike} (Scalper)", "#ff4757", "scalper"),
    ("vix",        "INDIA VIX",                       "#a78bfa", "vix"),
]
for col, (key, label, color, mode) in zip([ch1,ch2,ch3], chart_configs):
    if mode == "scalper":
        history = list(st.session_state.get(key, deque()))
    elif mode == "vix":
        history = list(st.session_state.get("vix_history", deque()))
    else:
        history = list(st.session_state["tick_history"].get(key, deque()))
    with col:
        if len(history)>=2:
            try:
                times=[h[0] for h in history]; values=[h[1] for h in history]
                fig=go.Figure(go.Scatter(x=times,y=values,mode="lines",line=dict(color=color,width=1.5),fill="tozeroy",fillcolor=f"rgba({int(color[1:3],16)},{int(color[3:5],16)},{int(color[5:7],16)},0.08)"))
                if key=="PCR": fig.add_hline(y=1.0,line=dict(color="#ffffff",width=0.5,dash="dash"))
                if mode=="vix":
                    fig.add_hline(y=15,line=dict(color="#00e676",width=0.5,dash="dash"),annotation_text="15",annotation_font=dict(size=8,color="#00e676"))
                    fig.add_hline(y=20,line=dict(color="#ff4757",width=0.5,dash="dash"),annotation_text="20",annotation_font=dict(size=8,color="#ff4757"))
                fig.update_layout(title=dict(text=f"{label}: {values[-1]:.2f}",font=dict(family="JetBrains Mono",size=10,color=color),x=0.04),
                    plot_bgcolor="#0a0e17",paper_bgcolor="#0d1526",font=dict(family="JetBrains Mono",color="#5a7a9a",size=8),
                    margin=dict(l=40,r=10,t=28,b=28),height=160,
                    xaxis=dict(showgrid=False,tickformat="%H:%M:%S",tickfont=dict(size=7)),
                    yaxis=dict(showgrid=True,gridcolor="#0d1828",tickfont=dict(size=8)),showlegend=False)
                st.plotly_chart(fig, width="stretch",config={"displayModeBar":False})
            except Exception as e:
                st.error(f"Chart Render Error: {e}")
        else:
            st.markdown(f'<div class="info-box" style="height:160px;display:flex;align-items:center;justify-content:center;text-align:center">⏳ {label}<br>Building chart...</div>',unsafe_allow_html=True)

if chain:
    st.markdown("<br>",unsafe_allow_html=True)
    oi1,oi2=st.columns([3,1])
    with oi1:
        st.markdown('<div class="section-hdr">📊 OI DISTRIBUTION</div>',unsafe_allow_html=True)
        ss=sorted(chain.keys())
        # Filter only visible strikes for cleaner chart
        vis_ss = sorted(chain.keys())
        atm_i  = min(range(len(vis_ss)), key=lambda i: abs(vis_ss[i]-atm_strike))
        chart_ss = vis_ss[max(0,atm_i-8):atm_i+9]

        ce_vals = [float(chain[s].get("CE",{}).get("currentOI",0)) for s in chart_ss]
        pe_vals = [float(chain[s].get("PE",{}).get("currentOI",0)) for s in chart_ss]
        x_labels = [str(s) for s in chart_ss]

        try:
            fig2 = go.Figure()
            fig2.add_trace(go.Bar(name="CE OI", x=x_labels, y=ce_vals,
                marker_color="#ff4757", opacity=0.8,
                text=[f"{v/100000:.1f}L" if v>0 else "" for v in ce_vals],
                textposition="outside", textfont=dict(size=8, color="#ff4757")))
            fig2.add_trace(go.Bar(name="PE OI", x=x_labels, y=pe_vals,
                marker_color="#00e676", opacity=0.8,
                text=[f"{v/100000:.1f}L" if v>0 else "" for v in pe_vals],
                textposition="outside", textfont=dict(size=8, color="#00e676")))

            # ATM line - use numeric index
            atm_str = str(atm_strike)
            if atm_str in x_labels:
                atm_idx = x_labels.index(atm_str)
                fig2.add_vrect(
                    x0=atm_idx-0.5,
                    x1=atm_idx+0.5,
                    fillcolor="rgba(255,215,0,0.08)",
                    layer="below", line_width=0)
                fig2.add_annotation(
                    x=atm_idx, y=1, yref="paper",
                    text=f"ATM {atm_strike}",
                    font=dict(color="#ffd700",size=10,family="JetBrains Mono"),
                    showarrow=False, yanchor="bottom")

            fig2.update_layout(
                barmode="group", plot_bgcolor="#0a0e17", paper_bgcolor="#0d1526",
                font=dict(family="JetBrains Mono", color="#5a7a9a", size=9),
                margin=dict(l=50,r=20,t=40,b=60), height=300,
                xaxis=dict(
                    type="category",
                    showgrid=False,
                    tickfont=dict(size=9,color="#8ab8d8"),
                    title=dict(text="Strike Price",font=dict(size=9,color="#5a7a9a")),
                    linecolor="#1e3a5f"),
                yaxis=dict(showgrid=True, gridcolor="#0d1828", tickfont=dict(size=9),
                           title=dict(text="Open Interest",font=dict(size=9,color="#5a7a9a"))),
                legend=dict(font=dict(size=9), bgcolor="rgba(0,0,0,0)",
                            orientation="h", y=1.08),
                bargap=0.2, bargroupgap=0.05)
            st.plotly_chart(fig2, width="stretch", config={"displayModeBar":False})
        except Exception as e:
            st.error(f"OI Chart Error: {e}")
    with oi2:
        st.markdown('<div class="section-hdr">📖 OI LEGEND</div>',unsafe_allow_html=True)
        st.markdown("""<div style="font-family:'JetBrains Mono',monospace;font-size:0.78rem;line-height:2">
        <span style="color:#00e676">🟢 LB</span> Long Buildup<br>
        <span style="color:#ff4757">🔴 SB</span> Short Buildup<br>
        <span style="color:#ffd700">🟡 LU</span> Long Unwinding<br>
        <span style="color:#00aaff">🔵 SC</span> Short Covering<br>
        <span style="color:#8a9ab8">─</span> No Change</div>""",unsafe_allow_html=True)

# ── TRADE JOURNAL ────────────────────────────────────────────────
if os.path.exists("trade_journal.csv"):
    with st.expander("📒 TRADE JOURNAL", expanded=False):
        try:
            df_journal = pd.read_csv("trade_journal.csv")
            df_journal = df_journal.astype(str).replace('None','')
            st.dataframe(df_journal, width="stretch", height=250)
            # Analytics
            total = len(df_journal)
            open_trades = len(df_journal[df_journal["Result"]=="OPEN"])
            st.markdown(f'<div class="info-box">Total signals: {total} | Open: {open_trades}</div>', unsafe_allow_html=True)
        except Exception as e:
            st.error(str(e))

st.markdown("""<div style="text-align:center;font-family:'JetBrains Mono',monospace;font-size:0.62rem;color:#1a3a5a;padding:10px;border-top:1px solid #0d1828;margin-top:16px">
  SK TERMINAL v4.2 | NSE F&O | ⚠ For personal use only.</div>""",unsafe_allow_html=True)

# Update signal tracker every refresh
if ticks and st.session_state.get("active_trades"):
    update_signal_tracker(ticks, scrip_map)

if ticks and st.session_state.get("hm_active_trades"):
    update_hm_sniper_tracker(ticks)

if auto_refresh: time.sleep(refresh_rate); st.rerun()
