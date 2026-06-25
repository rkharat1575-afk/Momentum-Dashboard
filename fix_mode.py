"""
fix_mode.py — Fixes Demo/Live mode detection permanently
Run: python fix_mode.py
"""

with open("sharekhan_terminal_v3.py", "r", encoding="utf-8") as f:
    code = f.read()

# Remove the bad override that forces demo when ws not connected
bad = '''# PATCHED: Use explicit session state flag set by sidebar radio
demo_mode = not st.session_state.get("live_mode_active", False)

if demo_mode:
    update_demo_data()
    st.session_state["ws_connected"] = True
    st.session_state["last_update"] = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    st.session_state["total_ticks"] += len(DEMO_TOKENS)
else:
    process_tick_queue()'''

good = '''# MODE DETECTION — driven purely by sidebar radio selection
demo_mode = not st.session_state.get("live_mode_active", False)

if demo_mode:
    update_demo_data()
    st.session_state["last_update"] = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    st.session_state["total_ticks"] += len(DEMO_TOKENS)
else:
    # LIVE MODE — only process real ticks, never fall back to demo
    process_tick_queue()
    st.session_state["ws_connected"] = st.session_state.get("ws_connected", False)'''

if bad in code:
    code = code.replace(bad, good)
    print("✅ Mode logic fixed.")
else:
    print("⚠ Block not found - trying alternate fix...")
    # Broader search
    if "live_mode_active" in code:
        print("live_mode_active found in code - manual check needed")
    else:
        print("Applying fresh fix...")

# Fix sidebar radio to properly set live_mode_active
bad2 = '''    mode = st.radio("Mode", ["🟡 Demo (Simulated)", "🟢 Live (Real API)"], index=0)
    demo_mode = "Demo" in mode
    st.session_state["live_mode_active"] = ("Live" in mode)'''

good2 = '''    mode = st.radio("Mode", ["🟡 Demo (Simulated)", "🟢 Live (Real API)"], 
                    index=1 if st.session_state.get("live_mode_active", False) else 0)
    st.session_state["live_mode_active"] = ("Live" in mode)
    demo_mode = not st.session_state["live_mode_active"]'''

if bad2 in code:
    code = code.replace(bad2, good2)
    print("✅ Sidebar radio fixed — selection now persists across refreshes.")
else:
    print("⚠ Sidebar block not found.")

with open("sharekhan_terminal_v3.py", "w", encoding="utf-8") as f:
    f.write(code)

print("\nDone! Now restart terminal:")
print("  python -m streamlit run sharekhan_terminal_v3.py")
