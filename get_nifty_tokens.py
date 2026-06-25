"""
get_nifty_tokens.py — Extracts Nifty CE/PE token codes for WebSocket
"""
import pandas as pd

df = pd.read_csv("nf_scrip_master_expanded.csv")

# Filter NIFTY options only (not BANKNIFTY)
nifty = df[
    (df['tradingSymbol'].str.upper().str.startswith('NIFTY')) &
    (~df['tradingSymbol'].str.upper().str.startswith('NIFTYBEE')) &
    (~df['tradingSymbol'].str.upper().str.startswith('BANKNIFTY')) &
    (df['instType'] == 'OI') &
    (df['optionType'].isin(['CE', 'PE']))
].copy()

# Sort by expiry and strike
nifty = nifty.sort_values(['expiry', 'strike'])

# Show all available expiries
print("Available NIFTY expiries:")
print(nifty['expiry'].unique())
print()

# Show weekly (nearest) expiry options
nearest_expiry = nifty['expiry'].min()
print(f"Nearest expiry: {nearest_expiry}")
weekly = nifty[nifty['expiry'] == nearest_expiry]

print(f"\nNIFTY {nearest_expiry} options ({len(weekly)} strikes):")
print(f"{'Strike':<10} {'Type':<5} {'ScripCode':<12} {'WS Token':<15} {'Symbol'}")
print("-" * 65)
for _, row in weekly.iterrows():
    ws_token = f"NF{int(row['scripCode'])}"
    print(f"{row['strike']:<10.0f} {row['optionType']:<5} {int(row['scripCode']):<12} {ws_token:<15} {row['tradingSymbol']}")

# Save to file
weekly.to_csv("nifty_weekly_tokens.csv", index=False)
print(f"\nSaved to nifty_weekly_tokens.csv")
print(f"\nUse these WS Token values in the terminal sidebar WebSocket Tokens box.")
