import os
import glob
import pandas as pd
from tqdm import tqdm

# --- Configuration ---
RAW_DATA_DIR = r"G:\NIFTY HISTORICAL DATA\extracted"
OUTPUT_DIR = r"C:\sharekhan_terminal\Offline_AI_Lab\data"
FINAL_OUTPUT_FILE = os.path.join(OUTPUT_DIR, "nifty_clean_data.parquet")

def process_data():
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    csv_files = glob.glob(os.path.join(RAW_DATA_DIR, "*.csv"))
    if not csv_files:
        print(f"No CSV files found in {RAW_DATA_DIR}")
        return

    print(f"Found {len(csv_files)} CSV files. Starting ingestion...")
    
    all_filtered_data = []
    
    for file in tqdm(csv_files, desc="Processing CSVs"):
        try:
            # Read the CSV. low_memory=False prevents mixed DType warnings on large files
            df = pd.read_csv(file, low_memory=False)
            
            # Standardize column names (strip spaces, uppercase)
            df.columns = df.columns.str.strip().str.upper()

            # Find the 'TICKER' or 'SYMBOL' column
            ticker_col = None
            for col in df.columns:
                if 'TICKER' in col or 'SYMBOL' in col:
                    ticker_col = col
                    break
            
            if not ticker_col:
                print(f"\nWarning: Could not find a Ticker/Symbol column in {os.path.basename(file)}. Skipping.")
                continue

            # Filter out junk stocks. Keep only rows where Ticker starts with 'NIFTY'
            # This captures 'NIFTY' (spot), 'NIFTY_F1' (futures), and 'NIFTY24OCT...' (options)
            nifty_data = df[df[ticker_col].astype(str).str.startswith('NIFTY')].copy()
            
            if not nifty_data.empty:
                all_filtered_data.append(nifty_data)
                
        except Exception as e:
            print(f"\nError processing {os.path.basename(file)}: {e}")

    if all_filtered_data:
        print("\nConcatenating filtered data...")
        final_df = pd.concat(all_filtered_data, ignore_index=True)
        
        print("Optimizing data types and converting timestamps...")
        
        # Determine Date and Time columns
        date_col = next((c for c in final_df.columns if 'DATE' in c), None)
        time_col = next((c for c in final_df.columns if 'TIME' in c), None)
        
        if date_col and time_col:
            try:
                # Combine into a single Datetime object for powerful time-series analysis
                final_df['DATETIME'] = pd.to_datetime(final_df[date_col].astype(str) + ' ' + final_df[time_col].astype(str))
                # Sort the entire dataset chronologically
                final_df.sort_values(by=['DATETIME', ticker_col], inplace=True)
                final_df.reset_index(drop=True, inplace=True)
            except Exception as e:
                print(f"Warning: Could not automatically parse DATETIME. Error: {e}")

        print(f"Saving to highly compressed Parquet format: {FINAL_OUTPUT_FILE}")
        # Parquet is 10x faster to read/write than CSV and uses significantly less RAM
        final_df.to_parquet(FINAL_OUTPUT_FILE, engine='pyarrow', compression='snappy')
        
        print("\n--- INGESTION COMPLETE ---")
        print(f"Total NIFTY Rows Saved: {len(final_df)}")
        print(f"Unique Options/Assets Extracted: {final_df[ticker_col].nunique()}")
        print("Ready for Step 2: Feature Engineering!")
    else:
        print("\nNo NIFTY data was extracted. Please check the CSV format.")

if __name__ == "__main__":
    process_data()
