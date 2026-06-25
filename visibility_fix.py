import os

jsx_path = r"C:\sharekhan_terminal\NIFTY MOMENTUM DASHBOARD FROM AI\src\nifty_momentum_dashboard.jsx"

with open(jsx_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Stop the center panel from stretching vertically by adding align-self: start
# The center panel starts with: {/* ── CENTER PANEL: STRIKE RECOMMENDATIONS ── */}
content = content.replace(
    '        {/* ── CENTER PANEL: STRIKE RECOMMENDATIONS ── */}\n        <div style={{ display: "flex", flexDirection: "column" }}>',
    '        {/* ── CENTER PANEL: STRIKE RECOMMENDATIONS ── */}\n        <div style={{ display: "flex", flexDirection: "column", alignSelf: "start" }}>'
)

# 2. Fix the Strike Card CSS: remove justify-content: space-between so they look compact
target_css = """        .strike-card { 
          border: 1px solid rgba(203,213,225,1); 
          border-radius: 6px; 
          padding: 8px; 
          cursor: pointer;
          transition: all 0.2s ease;
          background: rgba(255,255,255,0.8);
          display: flex;
          flex-direction: column;
          justify-content: space-between;
        }"""
replacement_css = """        .strike-card { 
          border: 1px solid rgba(203,213,225,1); 
          border-radius: 6px; 
          padding: 8px; 
          cursor: pointer;
          transition: all 0.2s ease;
          background: rgba(255,255,255,0.8);
          display: flex;
          flex-direction: column;
          gap: 6px;
        }"""
content = content.replace(target_css, replacement_css)

# 3. Add borders to the Premium boxes so they stand out from the card background
old_prem_box = 'background: "linear-gradient(135deg, rgba(255,255,255,1), rgba(241,245,249,0.9))", backdropFilter: "blur(12px)", borderRadius: 4, padding: "6px 8px"'
new_prem_box = 'background: "linear-gradient(135deg, rgba(255,255,255,1), rgba(241,245,249,0.9))", backdropFilter: "blur(12px)", borderRadius: 4, padding: "6px 8px", border: "1px solid rgba(203,213,225,1)", boxShadow: "0 2px 4px rgba(0,0,0,0.02)"'
content = content.replace(old_prem_box, new_prem_box)

# 4. Add borders to the Targets & Stop boxes
old_target_box = 'background: "rgba(241,245,249,1)", borderRadius: 3, padding: "4px 6px", borderLeft: `2px solid ${color}44`'
new_target_box = 'background: "rgba(241,245,249,1)", borderRadius: 3, padding: "4px 6px", borderLeft: `2px solid ${color}44`, borderTop: "1px solid rgba(203,213,225,0.5)", borderRight: "1px solid rgba(203,213,225,0.5)", borderBottom: "1px solid rgba(203,213,225,0.5)"'
content = content.replace(old_target_box, new_target_box)

# 5. Darken the labels in the cards to improve readability (from Slate 400/500 to Slate 600/700)
content = content.replace('color: "#64748b"', 'color: "#475569"')

# 6. Squeeze Right & Left Panels slightly more to fit everything
content = content.replace('marginBottom: 4', 'marginBottom: 2') # Super aggressive squeeze on inner items
content = content.replace('marginBottom: 6', 'marginBottom: 4')
content = content.replace('marginBottom: 8', 'marginBottom: 6')
content = content.replace('padding: "4px 8px"', 'padding: "2px 6px"')

with open(jsx_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Visibility and squeeze fix applied!")
