import os
import pandas as pd
import numpy as np
from tqdm import tqdm
from itertools import product

# --- Configuration ---
DATA_DIR = r"C:\sharekhan_terminal\Offline_AI_Lab\data"
INPUT_FILE = os.path.join(DATA_DIR, "nifty_ai_features.parquet")

def load_data():
    print("Loading enriched AI dataset...")
    df = pd.read_parquet(INPUT_FILE)
    # Ensure it's sorted chronologically for backtesting
    ticker_col = next((c for c in df.columns if 'TICKER' in c or 'SYMBOL' in c), None)
    df.sort_values(by=[ticker_col, 'DATETIME'], inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df, ticker_col

def run_simulation(df, ticker_col, rsi_thresh, req_vol_spike, take_profit_pct, stop_loss_pct):
    """
    Simulates trading based on a specific set of rules.
    Returns: Total Profit (Points), Win Rate, Total Trades
    """
    # 1. Define Entry Signals (Vectorized for speed)
    # Signal: RSI crosses above Threshold AND (optionally) Volume is spiking
    prev_rsi = df.groupby(ticker_col)['OPT_RSI_14'].shift(1)
    
    entry_condition = (df['OPT_RSI_14'] > rsi_thresh) & (prev_rsi <= rsi_thresh)
    if req_vol_spike:
        entry_condition = entry_condition & (df['VOL_SPIKE'] == 1)
        
    # To enforce intraday, only take trades between 09:30 and 14:45
    df['TIME_ONLY'] = df['DATETIME'].dt.time
    time_condition = (df['TIME_ONLY'] >= pd.to_datetime('09:30').time()) & \
                     (df['TIME_ONLY'] <= pd.to_datetime('14:45').time())
                     
    entry_signals = df[entry_condition & time_condition].copy()
    
    if entry_signals.empty:
        return 0, 0.0, 0

    # For speed in Python, we will do a simplified forward-look.
    # In a real tick-engine we step minute by minute. Here we will look at the max/min over the next 30 minutes.
    # To be extremely fast across 1.8M rows, we group by ticker and date
    
    # We will simulate the trades:
    wins = 0
    losses = 0
    total_points = 0.0

    # Since there can be thousands of signals, iterating them row by row is slow but accurate enough for a prototype.
    # We optimize by only looking at the specific Ticker and Date
    df['DATE_ONLY'] = df['DATETIME'].dt.date
    entry_signals['DATE_ONLY'] = entry_signals['DATETIME'].dt.date
    
    # Pre-index data by Ticker and Date for fast lookup
    indexed_df = df.set_index([ticker_col, 'DATE_ONLY'])
    
    # To keep the search fast (under a minute), we will randomly sample max 500 signals if there are too many
    if len(entry_signals) > 500:
        entry_signals = entry_signals.sample(n=500, random_state=42)
        
    for idx, row in entry_signals.iterrows():
        t = row[ticker_col]
        d = row['DATE_ONLY']
        entry_time = row['DATETIME']
        entry_price = row['CLOSE']
        
        tp_price = entry_price * (1 + (take_profit_pct / 100.0))
        sl_price = entry_price * (1 - (stop_loss_pct / 100.0))
        
        try:
            # Get the rest of the day for this ticker
            day_data = indexed_df.loc[(t, d)]
            # Filter for times AFTER entry
            future_data = day_data[day_data['DATETIME'] > entry_time]
            
            outcome = "TIME_EXIT"
            exit_price = entry_price
            
            for f_idx, f_row in future_data.iterrows():
                high = f_row['HIGH']
                low = f_row['LOW']
                
                # Check Stop Loss first (conservative)
                if low <= sl_price:
                    outcome = "LOSS"
                    exit_price = sl_price
                    break
                # Check Take Profit
                elif high >= tp_price:
                    outcome = "WIN"
                    exit_price = tp_price
                    break
                    
                # Intraday Auto-Square off at 15:15
                if f_row['TIME_ONLY'] >= pd.to_datetime('15:15').time():
                    outcome = "TIME"
                    exit_price = f_row['CLOSE']
                    break
            
            points_gained = exit_price - entry_price
            total_points += points_gained
            
            if points_gained > 0:
                wins += 1
            else:
                losses += 1
                
        except Exception:
            pass # Skip if data is missing

    total_trades = wins + losses
    win_rate = (wins / total_trades) * 100 if total_trades > 0 else 0
    
    # Extrapolate total points if we sampled
    if len(entry_signals) == 500:
        multiplier = len(df[entry_condition & time_condition]) / 500.0
        total_points *= multiplier
        total_trades = int(total_trades * multiplier)

    return total_points, win_rate, total_trades

def run_ai_search():
    df, ticker_col = load_data()
    
    # Define Parameter Grid for the AI to search
    rsi_thresholds = [50, 55, 60]
    req_vol_spikes = [True, False]
    take_profits = [15, 30] # 15% or 30% jump in option premium
    stop_losses = [10, 20]  # 10% or 20% loss limit
    
    # Generate all combinations
    combinations = list(product(rsi_thresholds, req_vol_spikes, take_profits, stop_losses))
    print(f"\nAI Search Engine Initialized. Testing {len(combinations)} different strategy variations...\n")
    
    results = []
    
    for params in tqdm(combinations, desc="Simulating Strategies"):
        rsi, vol, tp, sl = params
        pts, wr, trades = run_simulation(df, ticker_col, rsi, vol, tp, sl)
        
        if trades > 10: # Ignore statistically insignificant strategies
            results.append({
                'RSI_Entry': rsi,
                'Require_Vol_Spike': vol,
                'Take_Profit_%': tp,
                'Stop_Loss_%': sl,
                'Win_Rate_%': round(wr, 2),
                'Total_Trades': trades,
                'Net_Points': round(pts, 2)
            })

    print("\n--- SEARCH COMPLETE ---")
    if not results:
        print("No profitable strategies found with enough trades.")
        return

    results_df = pd.DataFrame(results)
    # Sort by Most Net Points
    results_df = results_df.sort_values(by='Net_Points', ascending=False).head(5)
    
    print("\n--- TOP 5 MOST PROFITABLE STRATEGIES FOUND ---")
    print(results_df.to_string(index=False))
    
    # Save the results
    results_df.to_csv(os.path.join(DATA_DIR, "ai_search_results.csv"), index=False)
    print("\nBased on these results, we can formulate the absolute best Python logic for your live trading!")

if __name__ == "__main__":
    run_ai_search()
