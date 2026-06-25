import os
import pandas as pd
import numpy as np
from tqdm import tqdm

# --- Configuration ---
DATA_DIR = r"C:\sharekhan_terminal\Offline_AI_Lab\data"
INPUT_FILE = os.path.join(DATA_DIR, "nifty_clean_data.parquet")
OUTPUT_FILE = os.path.join(DATA_DIR, "nifty_ai_features.parquet")

def calculate_rsi(series, period=14):
    """Calculates the Relative Strength Index (RSI)."""
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).fillna(0)
    loss = (-delta.where(delta < 0, 0)).fillna(0)
    avg_gain = gain.rolling(window=period, min_periods=1).mean()
    avg_loss = loss.rolling(window=period, min_periods=1).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def engineer_features():
    if not os.path.exists(INPUT_FILE):
        print(f"Error: Could not find {INPUT_FILE}. Did Step 1 finish successfully?")
        return

    print("Loading cleaned data into memory...")
    df = pd.read_parquet(INPUT_FILE)
    
    # Identify the Ticker column dynamically
    ticker_col = next((c for c in df.columns if 'TICKER' in c or 'SYMBOL' in c), None)
    if not ticker_col:
        print("Error: Could not find Ticker/Symbol column.")
        return

    print("Separating Spot (NIFTY Index) from Options data...")
    # Exact match for NIFTY spot index (it usually doesn't have expiry dates in the name)
    # Sometimes it's just 'NIFTY' or 'NIFTY 50'
    spot_df = df[df[ticker_col] == 'NIFTY'].copy()
    
    # If the exact string 'NIFTY' isn't found, try 'NIFTY 50' or 'NIFTY_F1' (futures)
    if spot_df.empty:
        spot_df = df[df[ticker_col].str.contains('NIFTY 50|NIFTY_F1')].copy()
    
    options_df = df[~df[ticker_col].isin(spot_df[ticker_col].unique())].copy()
    
    print(f"Found {len(spot_df)} Spot rows and {len(options_df)} Option rows.")

    if spot_df.empty:
        print("Warning: Could not isolate NIFTY Spot data. Proceeding with Options-only features.")
    else:
        print("Calculating Spot Indicators (Hilega Milega logic)...")
        spot_df.sort_values(by='DATETIME', inplace=True)
        # Spot Moving Averages
        spot_df['SPOT_EMA_9'] = spot_df['CLOSE'].ewm(span=9, adjust=False).mean()
        spot_df['SPOT_EMA_20'] = spot_df['CLOSE'].ewm(span=20, adjust=False).mean()
        # Spot RSI
        spot_df['SPOT_RSI_14'] = calculate_rsi(spot_df['CLOSE'], period=14)
        
        # Keep only the features we need to merge back to options
        spot_features = spot_df[['DATETIME', 'CLOSE', 'SPOT_EMA_9', 'SPOT_EMA_20', 'SPOT_RSI_14']]
        spot_features = spot_features.rename(columns={'CLOSE': 'SPOT_CLOSE'})

    print("Calculating Option-specific Indicators...")
    # We must calculate indicators PER OPTION STRIKE independently.
    # Group by Ticker and calculate
    
    def calculate_option_features(group):
        group = group.sort_values(by='DATETIME')
        group['OPT_EMA_9'] = group['CLOSE'].ewm(span=9, adjust=False).mean()
        group['OPT_RSI_14'] = calculate_rsi(group['CLOSE'], period=14)
        group['VOL_SMA_20'] = group['VOLUME'].rolling(window=20, min_periods=1).mean()
        # Detect volume spikes (Volume > 2x its moving average)
        group['VOL_SPIKE'] = (group['VOLUME'] > (group['VOL_SMA_20'] * 2)).astype(int)
        return group

    # Apply calculations per ticker. tqdm helps us see progress.
    tqdm.pandas(desc="Engineering Option Features")
    options_df = options_df.groupby(ticker_col, group_keys=False).progress_apply(calculate_option_features)

    if not spot_df.empty:
        print("\nMerging Spot Features into Option Data...")
        # Now every minute of option data knows exactly what the underlying NIFTY index was doing!
        final_ai_df = pd.merge(options_df, spot_features, on='DATETIME', how='left')
    else:
        final_ai_df = options_df

    print(f"\nSaving AI-ready feature dataset to: {OUTPUT_FILE}")
    final_ai_df.to_parquet(OUTPUT_FILE, engine='pyarrow', compression='snappy')
    
    print("\n--- FEATURE ENGINEERING COMPLETE ---")
    print("The data is now mathematically enriched and ready for the Machine Learning model!")

if __name__ == "__main__":
    engineer_features()
