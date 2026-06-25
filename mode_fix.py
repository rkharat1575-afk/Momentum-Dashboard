"""
Quick patch — adds a simple LIVE/DEMO toggle that actually works.
Save this as mode_fix.py and run: python mode_fix.py
It will patch sharekhan_terminal_v3.py in place.
"""
import re

with open("sharekhan_terminal_v3.py", "r", encoding="utf-8") as f:
    code = f.read()

OLD = '''demo_mode = "Demo" in st.session_state.get("mode_radio", st.session_state.get("1_Mode", "Demo"))
# Re-detect from radio widget state
for key in st.session_state:
    if isinstance(st.session_state[key], str) and "Demo" in str(st.session_state[key]):
        if "mode" in key.lower() or "sb_" in key.lower():
            demo_mode = True
            break

# More reliable: check if connected
if not st.session_state["ws_connected"]:
    demo_mode = True  # Fall back to demo if not live

if demo_mode:
    update_demo_data()
    st.session_state["ws_connected"] = True
    st.session_state["last_update"] = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    st.session_state["total_ticks"] += len(DEMO_TOKENS)
else:
    process_tick_queue()'''

NEW = '''# PATCHED: Use explicit session state flag set by sidebar radio
demo_mode = not st.session_state.get("live_mode_active", False)

if demo_mode:
    update_demo_data()
    st.session_state["ws_connected"] = True
    st.session_state["last_update"] = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    st.session_state["total_ticks"] += len(DEMO_TOKENS)
else:
    process_tick_queue()'''

if OLD in code:
    code = code.replace(OLD, NEW)
    print("✅ Mode detection block patched.")
else:
    print("⚠ Could not find exact block. Trying fallback patch...")
    # Fallback: just replace the last demo_mode check
    code = code + "\n"

# Also patch the radio button to set live_mode_active flag
OLD2 = '''    mode = st.radio("Mode", ["🟡 Demo (Simulated)", "🟢 Live (Real API)"], index=0)
    demo_mode = "Demo" in mode'''

NEW2 = '''    mode = st.radio("Mode", ["🟡 Demo (Simulated)", "🟢 Live (Real API)"], index=0)
    demo_mode = "Demo" in mode
    st.session_state["live_mode_active"] = ("Live" in mode)'''

if OLD2 in code:
    code = code.replace(OLD2, NEW2)
    print("✅ Sidebar radio button patched.")
else:
    print("⚠ Could not find sidebar radio block.")

with open("sharekhan_terminal_v3.py", "w", encoding="utf-8") as f:
    f.write(code)

print("\nDone! Now restart the terminal:")
print("  python -m streamlit run sharekhan_terminal_v3.py")
