import os

file_path = r"C:\sharekhan_terminal\sharekhan_terminal_v4.py"

with open(file_path, "r", encoding="utf-8") as f:
    lines = f.readlines()

def replace_block(lines, start_idx, end_idx, new_block):
    return lines[:start_idx] + [new_block + "\n"] + lines[end_idx+1:]

# We will just rewrite the functions entirely.
# For log_trade (starts ~line 44)
start_log_trade = -1
end_log_trade = -1
for i, line in enumerate(lines):
    if line.startswith("def log_trade("):
        start_log_trade = i
    if start_log_trade != -1 and line.startswith("def update_signal_tracker("):
        end_log_trade = i - 1
        break

new_log_trade = '''def log_trade(direction, strike, opt_type, entry, sl, tgt1, tgt2, score, signals, ticks_ref=None, scrip_ref=None):
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
    if not os.path.exists(log_file):
        df_new.to_csv(log_file, index=False)
    else:
        df_new.to_csv(log_file, mode='a', header=False, index=False)

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
'''

if start_log_trade != -1 and end_log_trade != -1:
    lines = replace_block(lines, start_log_trade, end_log_trade, new_log_trade)


# For update_signal_tracker
start_upd = -1
end_upd = -1
for i, line in enumerate(lines):
    if line.startswith("def update_signal_tracker("):
        start_upd = i
    if start_upd != -1 and line.startswith("def play_alert("):
        end_upd = i - 1
        break

new_update_tracker = '''def update_signal_tracker(ticks, scrip_map):
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
'''

if start_upd != -1 and end_upd != -1:
    lines = replace_block(lines, start_upd, end_upd, new_update_tracker)


# Write lines to file to save intermediate, then we do replace for rest.
with open(file_path, "w", encoding="utf-8") as f:
    f.writelines(lines)

with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

old_telegram = """def send_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=5)
    except: pass"""

new_telegram = """def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for _ in range(3):
        try:
            r = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=5)
            if r.status_code == 200: break
        except:
            import time
            time.sleep(1)"""

content = content.replace(old_telegram, new_telegram)

old_send_alert = """def send_signal_alert(direction, score, signals, strike, ltp, opt_type):
    emoji = "🟢" if "BULL" in direction else "🔴"
    sl   = round(ltp * 0.40, 1)
    tgt1 = round(ltp * 1.30, 1)
    tgt2 = round(ltp * 1.60, 1)
    msg = f\"\"\"{emoji} NIFTY SIGNAL — {direction}
━━━━━━━━━━━━━━━━━━━
Trade : BUY {opt_type} {strike}
Entry : {ltp:.1f}
SL    : {sl:.1f} (-40%)
Tgt 1 : {tgt1:.1f} (+30%)
Tgt 2 : {tgt2:.1f} (+60%)
Time  : {datetime.now().strftime('%H:%M:%S')}
Score : {score:+d}
━━━━━━━━━━━━━━━━━━━
\"\"\" + "\\n".join(f"• {s}" for s in signals[:3])"""

new_send_alert = """def send_signal_alert(direction, score, signals, strike, ltp, opt_type, sl, tgt1, tgt2):
    emoji = "🟢" if "BULL" in direction else "🔴"
    msg = f\"\"\"{emoji} NIFTY SIGNAL — {direction}
━━━━━━━━━━━━━━━━━━━
Trade : BUY {opt_type} {strike}
Entry : {ltp:.1f}
SL    : {sl:.1f}
Tgt 1 : {tgt1:.1f}
Tgt 2 : {tgt2:.1f}
Time  : {datetime.now().strftime('%H:%M:%S')}
Score : {score:+d}
━━━━━━━━━━━━━━━━━━━
\"\"\" + "\\n".join(f"• {s}" for s in signals[:3])"""

content = content.replace(old_send_alert, new_send_alert)

old_score_strike = """def score_strike(chain, strike, opt_type, atm_strike, futures_ltp, selected_expiry):
    \"\"\"
    SCALPER SCORING:
    Prioritizes Momentum, Institutional Spikes, and Delta > 0.45
    \"\"\"
    tick = chain.get(strike, {}).get(opt_type, {})
    if not tick: return 0, {}

    ltp    = float(tick.get("ltp", 0))
    vol    = float(tick.get("qty", 0))
    bid    = float(tick.get("bidPrice", 0))
    ask    = float(tick.get("offPrice", ltp))
    if ltp < 15: return 0, {} # Too deep OTM for scalping

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
        
    ratio, imb_str, imb_score = options_math.get_order_book_imbalance(tick)
    score += imb_score
    
    greeks = {"delta": delta, "gamma": gamma, "iv": iv, "imbalance": imb_str, "vwap": vwap, "is_spike": is_spike}
    return round(min(100, max(0, score))), greeks"""

new_score_strike = """def score_strike(chain, strike, opt_type, atm_strike, futures_ltp, selected_expiry):
    \"\"\"
    SCALPER SCORING:
    Prioritizes Momentum, Institutional Spikes, Delta > 0.45, and High Gamma.
    \"\"\"
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
    return round(min(100, max(0, score))), greeks"""

content = content.replace(old_score_strike, new_score_strike)


old_ui_targets = """            sl   = round(best_ltp - 15, 1)
            tgt1 = round(best_ltp + 10, 1) # Quick scalp target
            tgt2 = round(best_ltp + 20, 1)"""

new_ui_targets = """            iv_est_val = best_greeks.get("iv", 0.15) if best_greeks.get("iv", 0) > 0 else 0.15
            vix_val = st.session_state.get("vix_history", [15])[-1] if st.session_state.get("vix_history") else 15
            sl, tgt1, tgt2 = options_math.calculate_dynamic_targets(best_ltp, iv_est_val, vix_val)"""

content = content.replace(old_ui_targets, new_ui_targets)

old_alert_call = """                sl   = round(best_ltp - 15, 1)
                tgt1 = round(best_ltp + 15, 1)
                tgt2 = round(best_ltp + 30, 1)
                send_signal_alert(direction,score,signals,best_strike,best_ltp,best_type)"""

new_alert_call = """                iv_est_val = best_greeks.get("iv", 0.15) if 'best_greeks' in locals() and best_greeks.get("iv", 0) > 0 else 0.15
                vix_val = st.session_state.get("vix_history", [15])[-1] if st.session_state.get("vix_history") else 15
                sl, tgt1, tgt2 = options_math.calculate_dynamic_targets(best_ltp, iv_est_val, vix_val)
                send_signal_alert(direction,score,signals,best_strike,best_ltp,best_type,sl,tgt1,tgt2)"""

content = content.replace(old_alert_call, new_alert_call)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)
