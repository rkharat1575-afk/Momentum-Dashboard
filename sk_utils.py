import pandas as pd
from datetime import datetime
import os

def get_nifty_futures_token():
    """
    Dynamically finds the nearest active Nifty Futures token.
    Ignores expired contracts using today's date.
    """
    try:
        master_file = "nf_scrip_master_expanded.csv"
        if not os.path.exists(master_file):
            return "NF62329" # fallback
            
        df = pd.read_csv(master_file)
        futures = df[
            (df['tradingSymbol'].str.upper().str.startswith('NIFTY')) &
            (~df['tradingSymbol'].str.upper().str.startswith('BANKNIFTY')) &
            (df['instType'] == 'FI')
        ].copy()
        
        futures['expiry_dt'] = pd.to_datetime(futures['expiry'], dayfirst=True, errors='coerce')
        # Only keep tokens that haven't expired yet
        futures = futures[futures['expiry_dt'].dt.date >= datetime.now().date()]
        futures = futures.sort_values('expiry_dt')
        
        if not futures.empty:
            return f"NF{int(futures.iloc[0]['scripCode'])}"
    except Exception as e:
        print("Error finding futures token in sk_utils:", e)
        
    return "NF62329" # Fallback if something goes wrong
