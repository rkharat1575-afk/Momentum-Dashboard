import re

file_path = r"C:\sharekhan_terminal\NIFTY MOMENTUM DASHBOARD FROM AI\src\nifty_momentum_dashboard.jsx"

with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Update Composite Score UI to show 100 point scale and Seller Stress
content = re.sub(
    r'>COMPOSITE SCORE<',
    r' style={{ color: "#00ff88", textShadow: "0 0 5px #00ff88" }}>SELLER STRESS (CHAIN RADAR)<',
    content
)

# Fix the denominator /30 to /100 and the value from signals.composite to chainContext.seller_stress_score
content = re.sub(
    r'\{signals \? signals\.composite\.toFixed\(1\) : "0\.0"\}',
    r'{chainContext ? chainContext.seller_stress_score.toFixed(1) : "0.0"}',
    content
)
content = re.sub(r'/30</span>', r'/100</span>', content)

# 2. Fix Axis Breakdown panel
axis_new = """>INSTITUTIONAL RADAR</div>
            
            {chainContext && (
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
            )}
            
            <div style={{ display: "none" }}>"""

content = re.sub(r'>AXIS BREAKDOWN</div>', axis_new, content)
content = re.sub(r'>MICROSTRUCTURE</div>', r'>MICROSTRUCTURE</div></div>', content) # close the hidden div before microstructure

# 3. Add "Vibrant" styling
content = content.replace('background: "#050810"', 'background: "radial-gradient(circle at 50% 0%, #0d1b2a, #050810)"')
content = content.replace('background: "rgba(10,18,35,0.95)"', 'background: "linear-gradient(135deg, rgba(12,20,38,0.7), rgba(5,10,20,0.8))", backdropFilter: "blur(12px)", boxShadow: "0 8px 32px rgba(0,0,0,0.5)"')
content = content.replace('background: "rgba(8,15,30,0.8)"', 'background: "linear-gradient(135deg, rgba(15,25,45,0.7), rgba(8,15,25,0.8))", backdropFilter: "blur(12px)"')

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)

print("Dashboard UI Regex patched successfully.")
