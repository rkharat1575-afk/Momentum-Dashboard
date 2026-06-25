import os

jsx_path = r"C:\sharekhan_terminal\NIFTY MOMENTUM DASHBOARD FROM AI\src\nifty_momentum_dashboard.jsx"

with open(jsx_path, 'r', encoding='utf-8') as f:
    content = f.read()

target_css = """        .strike-card { 
          border: 1px solid rgba(203,213,225,1); 
          border-radius: 6px; 
          padding: 8px; 
          cursor: pointer;
          transition: all 0.2s ease;
          background: rgba(255,255,255,0.8);
        }
        .strike-card:hover { border-color: rgba(0,150,255,0.5); background: rgba(0,60,120,0.15); }
        .strike-card.best { border-color: rgba(0,255,136,0.5); background: rgba(0,60,30,0.2); }
        .strike-card.selected { border-color: rgba(0,200,255,0.8); background: rgba(0,60,100,0.25); }"""

replacement_css = """        .strike-card { 
          border: 1px solid rgba(203,213,225,1); 
          border-radius: 6px; 
          padding: 8px; 
          cursor: pointer;
          transition: all 0.2s ease;
          background: rgba(255,255,255,0.8);
          display: flex;
          flex-direction: column;
          justify-content: space-between;
        }
        .strike-card:hover { border-color: rgba(59,130,246,0.5); background: rgba(59,130,246,0.1); }
        .strike-card.best { border-color: rgba(16,185,129,0.5); background: rgba(16,185,129,0.15); }
        .strike-card.selected { border-color: rgba(59,130,246,0.8); background: rgba(59,130,246,0.2); }"""

content = content.replace(target_css, replacement_css)

with open(jsx_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Strike card CSS patched!")
