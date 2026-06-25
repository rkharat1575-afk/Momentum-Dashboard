import os

file_path = r"C:\sharekhan_terminal\sharekhan_terminal_v4.py"

with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Add import
if "import hm_engine" not in content:
    content = content.replace("import options_math", "import options_math\nimport hm_engine")

# 2. Add HM Engine UI at the end of sig_col (before with chain_col:)
hm_ui_code = """
        # --- Hilega Milega Engine (Isolated) ---
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown('<div class="section-hdr">🚀 HILEGA MILEGA ENGINE</div>', unsafe_allow_html=True)
        
        hist_ticks = list(st.session_state.get("futures_history", []))
        if len(hist_ticks) < 50:
            st.markdown('<div class="info-box">⏳ Accumulating tick data for HM...</div>', unsafe_allow_html=True)
        else:
            hm_df = hm_engine.resample_ticks_to_candles(hist_ticks, timeframe='5min')
            is_banknifty = False # Using Nifty currently
            hm_sig, hm_strike, hm_opt_type, hm_rsi, hm_wma, hm_ema = hm_engine.process_hm_logic(hm_df.copy(), futures_ltp, is_banknifty)
            
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
            
            # Telegram Alert for HM
            if hm_sig != "NEUTRAL":
                hm_sig_key = f"HM_{hm_sig}_{hm_strike}_{hm_opt_type}"
                hm_time_ok = (time.time() - st.session_state.get("last_hm_alert_time", 0)) > 300 # 5 min cooldown
                if hm_sig_key != st.session_state.get("last_hm_signal", "") and hm_time_ok:
                    msg = hm_engine.format_telegram_alert(hm_sig, "NIFTY", hm_strike, hm_opt_type, futures_ltp)
                    import threading
                    threading.Thread(target=send_telegram, args=(msg,), daemon=True).start()
                    st.session_state["last_hm_signal"] = hm_sig_key
                    st.session_state["last_hm_alert_time"] = time.time()
"""

# Find where to inject
target = """    else:
        st.markdown('<div class="info-box">Waiting for data...</div>',unsafe_allow_html=True)

with chain_col:"""

replacement = """    else:
        st.markdown('<div class="info-box">Waiting for data...</div>',unsafe_allow_html=True)
""" + hm_ui_code + "\nwith chain_col:"

if "HILEGA MILEGA ENGINE" not in content:
    content = content.replace(target, replacement)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)
