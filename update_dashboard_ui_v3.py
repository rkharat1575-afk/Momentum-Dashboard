import re

file_path = r"C:\sharekhan_terminal\NIFTY MOMENTUM DASHBOARD FROM AI\src\nifty_momentum_dashboard.jsx"

with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# Fix the 100 point score: use the maximum score from strikeScores instead of non-existent chainContext.seller_stress_score
# Since strikeScores is an object, we can get values. If empty, return 0.
score_logic_new = """{Object.keys(strikeScores).length > 0 ? Math.max(...Object.values(strikeScores)).toFixed(1) : "0.0"}"""
content = re.sub(
    r'\{chainContext \? chainContext\.seller_stress_score\.toFixed\(1\) : "0\.0"\}',
    score_logic_new,
    content
)

# Fix Institutional Radar fields to match the actual ChainContext dataclass
radar_old = """{chainContext && (
              <div style={{ marginBottom: 15, padding: "10px", background: "rgba(0,255,136,0.05)", borderRadius: "8px", border: "1px solid rgba(0,255,136,0.2)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                  <span style={{ fontSize: 9, color: "#7ab8f5" }}>IV Skew Status</span>
                  <span style={{ fontSize: 10, fontWeight: 700, color: chainContext.iv_skew_bullish ? "#00ff88" : "#ff4466" }}>
                    {chainContext.iv_skew_bullish ? "BULLISH (FEAR)" : "BEARISH"}
                  </span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                  <span style={{ fontSize: 9, color: "#7ab8f5" }}>Chain PCR</span>
                  <span style={{ fontSize: 10, fontWeight: 700, color: "#aa88ff" }}>
                    {chainContext.current_pcr.toFixed(2)}
                  </span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ fontSize: 9, color: "#7ab8f5" }}>Gamma Walls</span>
                  <span style={{ fontSize: 9, color: "#ffaa44", textAlign: "right" }}>
                    Call: {chainContext.call_gamma_wall} <br/> Put: {chainContext.put_gamma_wall}
                  </span>
                </div>
              </div>
            )}"""

radar_new = """{chainContext && (
              <div style={{ marginBottom: 15, padding: "10px", background: "rgba(0,255,136,0.05)", borderRadius: "8px", border: "1px solid rgba(0,255,136,0.2)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                  <span style={{ fontSize: 9, color: "#7ab8f5" }}>IV Skew Status</span>
                  <span style={{ fontSize: 10, fontWeight: 700, color: chainContext.skew_direction === "CALL_BID" ? "#00ff88" : chainContext.skew_direction === "PUT_BID" ? "#ff4466" : "#aa88ff" }}>
                    {chainContext.skew_direction === "CALL_BID" ? "BULLISH (FEAR)" : chainContext.skew_direction === "PUT_BID" ? "BEARISH" : "NEUTRAL"}
                  </span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                  <span style={{ fontSize: 9, color: "#7ab8f5" }}>Chain PCR</span>
                  <span style={{ fontSize: 10, fontWeight: 700, color: chainContext.current_pcr > 1.2 ? "#00ff88" : chainContext.current_pcr < 0.8 ? "#ff4466" : "#aa88ff" }}>
                    {chainContext.current_pcr.toFixed(2)}
                  </span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ fontSize: 9, color: "#7ab8f5" }}>Gamma Walls</span>
                  <span style={{ fontSize: 9, color: "#ffaa44", textAlign: "right", fontFamily: "Orbitron" }}>
                    Call: {chainContext.nearest_call_wall || "None"} <br/> Put: {chainContext.nearest_put_wall || "None"}
                  </span>
                </div>
              </div>
            )}"""

content = content.replace(radar_old, radar_new)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)

print("Dashboard UI V3 mapped data fields correctly.")
