"""
find_nifty_futures.py - Find Nifty Futures scrip codes
Run: python find_nifty_futures.py
"""
import pandas as pd

df = pd.read_csv("nf_scrip_master_expanded.csv")

# Find Nifty Futures - instType FI = Future Index
futures = df[
    (df['tradingSymbol'].str.upper().str.startswith('NIFTY')) &
    (~df['tradingSymbol'].str.upper().str.startswith('BANKNIFTY')) &
    (df['instType'] == 'FI')
].copy()

futures = futures.sort_values('expiry')
print(f"Found {len(futures)} Nifty Futures contracts:")
print()
print(f"{'ScripCode':<12} {'WS Token':<12} {'Expiry':<15} {'Symbol'}")
print("-"*55)
for _, row in futures.head(6).iterrows():
    ws = f"NF{int(row['scripCode'])}"
    print(f"{int(row['scripCode']):<12} {ws:<12} {row['expiry']:<15} {row['tradingSymbol']}")
