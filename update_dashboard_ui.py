import re

file_path = r"C:\sharekhan_terminal\NIFTY MOMENTUM DASHBOARD FROM AI\src\nifty_momentum_dashboard.jsx"

with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# Fix recommendStrikes signature
content = content.replace(
    'function recommendStrikes(signals, instrument, vix, capital, liveOptions) {',
    'function recommendStrikes(signals, instrument, vix, capital, liveOptions, strikeScores) {'
)

# Fix strikeScore assignment
content = content.replace(
    'let strikeScore = strikeScoresRef.current[K] || composite || 0;',
    'let strikeScore = (strikeScores && strikeScores[K]) || composite || 0;'
)

# Fix recommendStrikes call
content = content.replace(
    'const recs = recommendStrikes(sigs, instRef.current, vixRef.current, capRef.current, liveOptionsRef.current);',
    'const recs = recommendStrikes(sigs, instRef.current, vixRef.current, capRef.current, liveOptionsRef.current, strikeScoresRef.current);'
)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)

print("Dashboard UI React error patched successfully.")
