"""
fix_scrip_master.py — Run once to extract Nifty token codes
"""
import pandas as pd
import json

print("Reading scrip master...")
df = pd.read_csv("nf_scrip_master.csv")

# The actual data is nested inside the 'data' column as JSON string
# Parse it out
rows = []
for val in df['data']:
    try:
        parsed = json.loads(val)
        if isinstance(parsed, dict):
            rows.append(parsed)
        elif isinstance(parsed, list):
            rows.extend(parsed)
    except:
        pass

if not rows:
    print("Trying alternate parse...")
    for val in df['data']:
        try:
            rows.append(eval(val))
        except:
            pass

df2 = pd.DataFrame(rows)
print(f"Extracted {len(df2)} rows")
print(f"Columns: {list(df2.columns)}")

# Save full expanded master
df2.to_csv("nf_scrip_master_expanded.csv", index=False)
print("Saved nf_scrip_master_expanded.csv")

# Show first few rows
print("\nFirst 3 rows:")
print(df2.head(3).to_string())

# Find symbol column
sym_col = None
scrip_col = None
for col in df2.columns:
    sample = str(df2[col].iloc[0]) if len(df2) > 0 else ""
    if any(x in col.lower() for x in ['symbol', 'name', 'scrip', 'trading']):
        print(f"\nPossible symbol column: [{col}] = {sample}")
    if any(x in col.lower() for x in ['code', 'token', 'scripcode']):
        print(f"Possible code column:   [{col}] = {sample}")
