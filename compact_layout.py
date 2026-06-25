import re

jsx_path = r"C:\sharekhan_terminal\NIFTY MOMENTUM DASHBOARD FROM AI\src\nifty_momentum_dashboard.jsx"

with open(jsx_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Reduce padding in panels to save vertical space
content = re.sub(r'padding:\s*"14px"', 'padding: "8px"', content)
content = re.sub(r'padding:\s*"10px 14px"', 'padding: "6px 8px"', content)
content = re.sub(r'padding:\s*"12px"', 'padding: "8px"', content)
content = re.sub(r'padding:\s*"10px"', 'padding: "6px"', content)
content = re.sub(r'padding:\s*"14px 16px"', 'padding: "8px 10px"', content)
content = re.sub(r'padding:\s*"8px 10px"', 'padding: "4px 8px"', content)

# Reduce margins to save vertical space
content = re.sub(r'marginBottom:\s*10\b', 'marginBottom: 4', content)
content = re.sub(r'marginBottom:\s*12\b', 'marginBottom: 6', content)
content = re.sub(r'marginBottom:\s*15\b', 'marginBottom: 8', content)
content = re.sub(r'marginTop:\s*10\b', 'marginTop: 4', content)
content = re.sub(r'marginBottom:\s*8\b', 'marginBottom: 4', content)

# Reduce flex/grid gaps
content = re.sub(r'gap:\s*10\b', 'gap: 6', content)
content = re.sub(r'gap:\s*12\b', 'gap: 8', content)
content = re.sub(r'gap:\s*8\b', 'gap: 4', content)

# To ensure the Signal Log doesn't push the layout out of bounds when it fills up:
content = content.replace('className="panel panel-glow" style={{ padding: "8px", flex: 1 }}', 'className="panel panel-glow" style={{ padding: "8px", flex: 1, overflowY: "auto", minHeight: 0 }}')

with open(jsx_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Layout compacted successfully!")
