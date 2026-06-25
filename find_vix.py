import pandas as pd
df = pd.read_csv("nf_scrip_master_expanded.csv")
vix = df[df['tradingSymbol'].str.upper().str.contains('VIX', na=False)]
print(vix[['scripCode','tradingSymbol','instType','expiry']].to_string())
