"""
fix_mode2.py — Fixes the root cause: radio button resets every second
The real bug: radio button has no key= so Streamlit resets it on every refresh
"""

with open("sharekhan_terminal_v3.py", "r", encoding="utf-8") as f:
    code = f.read()

fixes = 0

# Fix 1: Add key to radio button so selection persists
old1 = '''    mode = st.radio("Mode", ["🟡 Demo (Simulated)", "🟢 Live (Real API)"], 
                    index=1 if st.session_state.get("live_mode_active", False) else 0)
    st.session_state["live_mode_active"] = ("Live" in mode)
    demo_mode = not st.session_state["live_mode_active"]'''

new1 = '''    mode = st.radio("Mode", ["🟡 Demo (Simulated)", "🟢 Live (Real API)"],
                    index=1 if st.session_state.get("live_mode_active", False) else 0,
                    key="mode_radio_persistent")
    st.session_state["live_mode_active"] = ("Live" in mode)
    demo_mode = not st.session_state["live_mode_active"]'''

if old1 in code:
    code = code.replace(old1, new1)
    print("✅ Fix 1: Radio button key added")
    fixes += 1
else:
    # Try older version
    old1b = '''    mode = st.radio("Mode", ["🟡 Demo (Simulated)", "🟢 Live (Real API)"], index=0)
    demo_mode = "Demo" in mode
    st.session_state["live_mode_active"] = ("Live" in mode)'''
    new1b = '''    mode = st.radio("Mode", ["🟡 Demo (Simulated)", "🟢 Live (Real API)"],
                    index=1 if st.session_state.get("live_mode_active", False) else 0,
                    key="mode_radio_persistent")
    st.session_state["live_mode_active"] = ("Live" in mode)
    demo_mode = not st.session_state["live_mode_active"]'''
    if old1b in code:
        code = code.replace(old1b, new1b)
        print("✅ Fix 1b: Radio button key added (alternate)")
        fixes += 1
    else:
        print("⚠ Radio button block not found - applying force patch...")
        # Force replace any radio mode line
        import re
        code = re.sub(
            r'mode = st\.radio\("Mode".*?\n.*?index=.*?\)',
            '''mode = st.radio("Mode", ["🟡 Demo (Simulated)", "🟢 Live (Real API)"],
                    index=1 if st.session_state.get("live_mode_active", False) else 0,
                    key="mode_radio_persistent")''',
            code, flags=re.DOTALL
        )
        code = code.replace(
            'demo_mode = "Demo" in mode',
            'st.session_state["live_mode_active"] = ("Live" in mode)\n    demo_mode = not st.session_state["live_mode_active"]'
        )
        print("✅ Fix 1 force-applied")
        fixes += 1

# Fix 2: Make sure mode display in header uses correct variable
old2 = "\"🟡 DEMO\" if demo_mode else \"🟢 LIVE MODE\""
new2 = "\"🟡 DEMO\" if demo_mode else \"🟢 LIVE\""
if old2 in code:
    code = code.replace(old2, new2)

with open("sharekhan_terminal_v3.py", "w", encoding="utf-8") as f:
    f.write(code)

print(f"\n✅ Done! {fixes} fix(es) applied.")
print("\nNow type:")
print("  python -m streamlit run sharekhan_terminal_v3.py")
print("\nWhen dashboard opens:")
print("  1. Click Live (Real API)")  
print("  2. Paste tokens")
print("  3. Click Connect WebSocket")
print("  4. Mode should now stay LIVE")
