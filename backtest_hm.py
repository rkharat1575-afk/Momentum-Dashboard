import yfinance as yf
import pandas as pd
import numpy as np
from datetime import time

def calculate_rsi(series, period=9):
    delta = series.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calculate_wma(series, period=21):
    weights = np.arange(1, period + 1)
    return series.rolling(period).apply(lambda prices: np.dot(prices, weights) / weights.sum(), raw=True)

def run_backtest():
    print("Fetching 60 days of 5-minute data for Nifty 50...")
    df = yf.download("^NSEI", period="60d", interval="5m", progress=False)
    
    if df.empty:
        print("Failed to download data.")
        return
        
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
        
    df = df[['Open', 'High', 'Low', 'Close']].copy()
    df.columns = ['open', 'high', 'low', 'close']
    df.index = df.index.tz_convert('Asia/Kolkata').tz_localize(None)
    
    # Calculate Indicators
    print("Calculating Hilega Milega mathematical indicators...")
    df['RSI_9'] = calculate_rsi(df['close'], period=9)
    df['WMA_21'] = calculate_wma(df['RSI_9'], period=21)
    df['EMA_3'] = df['RSI_9'].ewm(span=3, adjust=False).mean()
    df['SMA_5'] = df['close'].rolling(window=5).mean()
    
    # Drop rows without enough data for WMA
    df = df.dropna()
    
    in_trade = False
    trade_type = None
    entry_price = 0
    trades = []
    
    STOP_LOSS_PTS = 30 # Catastrophic Safety Stop
    
    print("Simulating trades over 4,200+ candles...\n")
    
    for i in range(1, len(df)):
        current_time = df.index[i].time()
        
        row = df.iloc[i]
        prev = df.iloc[i-1]
        
        close = row['close']
        rsi = row['RSI_9']
        wma = row['WMA_21']
        ema = row['EMA_3']
        sma = row['SMA_5']
        
        if not in_trade:
            # Entry logic (No new trades after 15:00)
            if current_time < time(15, 0):
                # Bullish Entry
                if (rsi > wma) and (ema > rsi) and (close > sma):
                    in_trade = True
                    trade_type = "BUY CALL"
                    atm_strike = round(close / 50) * 50
                    strike_price = f"{atm_strike - 50} CE"
                    entry_price = close
                    entry_time = df.index[i]
                    
                # Bearish Entry
                elif (rsi < wma) and (ema < rsi) and (close < sma):
                    in_trade = True
                    trade_type = "BUY PUT"
                    atm_strike = round(close / 50) * 50
                    strike_price = f"{atm_strike + 50} PE"
                    entry_price = close
                    entry_time = df.index[i]
                    
        else:
            # Exit logic
            exit_triggered = False
            exit_reason = ""
            pnl = 0
            
            # Intraday Auto-Square Off
            if current_time >= time(15, 15):
                exit_triggered = True
                exit_reason = "15:15 Auto-Square Off"
            
            elif trade_type == "BUY CALL":
                pnl = close - entry_price
                if pnl <= -STOP_LOSS_PTS:
                    exit_triggered = True
                    exit_reason = "Hard Stop Loss Hit"
                elif (ema < rsi) or (close < sma):
                    exit_triggered = True
                    exit_reason = "Indicator Exit"
                    
            elif trade_type == "BUY PUT":
                pnl = entry_price - close
                if pnl <= -STOP_LOSS_PTS:
                    exit_triggered = True
                    exit_reason = "Hard Stop Loss Hit"
                elif (ema > rsi) or (close > sma):
                    exit_triggered = True
                    exit_reason = "Indicator Exit"
            
            if exit_triggered:
                # Record trade
                actual_pnl = close - entry_price if trade_type == "BUY CALL" else entry_price - close
                trades.append({
                    "Entry Time": entry_time,
                    "Exit Time": df.index[i],
                    "Type": trade_type,
                    "Option Strike": strike_price,
                    "Entry Price (Spot)": entry_price,
                    "Exit Price (Spot)": close,
                    "Nifty Points Captured": round(actual_pnl, 2),
                    "Exit Reason": exit_reason
                })
                in_trade = False
                trade_type = None
                entry_price = 0
                entry_time = None

    # Analytics
    total_trades = len(trades)
    winning_trades = len([t for t in trades if t["Nifty Points Captured"] > 0])
    losing_trades = len([t for t in trades if t["Nifty Points Captured"] <= 0])
    win_rate = (winning_trades / total_trades) * 100 if total_trades > 0 else 0
    total_points = sum([t["Nifty Points Captured"] for t in trades])
    
    # Calculate Max Drawdown (points)
    cumulative_points = 0
    peak = 0
    max_dd = 0
    for t in trades:
        cumulative_points += t["Nifty Points Captured"]
        if cumulative_points > peak:
            peak = cumulative_points
        dd = peak - cumulative_points
        if dd > max_dd:
            max_dd = dd

    print("="*40)
    print(" [HM] HILEGA MILEGA BACKTEST RESULTS")
    print("="*40)
    print(f"Total Trades Taken  : {total_trades}")
    print(f"Winning Trades      : {winning_trades}")
    print(f"Losing Trades       : {losing_trades}")
    print(f"Win Rate            : {win_rate:.2f}%")
    print(f"Total Nifty Points  : {total_points:.1f} pts")
    print(f"Max Drawdown        : {max_dd:.1f} pts")
    print("="*40)
    
    # If the user wants 15-20 pts per trade on average:
    avg_win = sum([t["Nifty Points Captured"] for t in trades if t["Nifty Points Captured"] > 0]) / winning_trades if winning_trades else 0
    avg_loss = sum([t["Nifty Points Captured"] for t in trades if t["Nifty Points Captured"] <= 0]) / losing_trades if losing_trades else 0
    
    print(f"Average Win Size    : {avg_win:.1f} pts")
    print(f"Average Loss Size   : {avg_loss:.1f} pts")
    print("="*40)
    
    # Save to Excel
    print("\nSaving detailed trade log to backtest_trades_v3.xlsx...")
    try:
        trades_df = pd.DataFrame(trades)
        trades_df['Entry Time'] = trades_df['Entry Time'].dt.tz_localize(None)
        trades_df['Exit Time'] = trades_df['Exit Time'].dt.tz_localize(None)
        trades_df.to_excel("backtest_trades_v3.xlsx", index=False)
        print("Successfully saved to C:\\sharekhan_terminal\\backtest_trades_v3.xlsx")
    except Exception as e:
        print(f"Failed to save Excel file: {e}\n(Please run: pip install openpyxl)")

if __name__ == "__main__":
    run_backtest()
