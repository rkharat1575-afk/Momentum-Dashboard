import pandas as pd
import numpy as np
import math
import yfinance as yf

def get_warmup_candles(is_bank_nifty=False):
    """
    Fetches intraday 5-min candles from Yahoo Finance to pre-warm the HM Engine indicators.
    This avoids the 105-minute waiting period when starting the dashboard late.
    """
    ticker = "^NSEBANK" if is_bank_nifty else "^NSEI"
    try:
        # Fetch last 5 days to ensure we have Friday's afternoon candles for a Monday 9:15 AM start
        df = yf.download(ticker, period="5d", interval="5m", progress=False)
        if df.empty: return pd.DataFrame()
        
        # Keep only the last 100 candles to keep memory incredibly light
        df = df.tail(100)
        
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
            
        df = df[['Open', 'High', 'Low', 'Close']].copy()
        df.columns = ['open', 'high', 'low', 'close']
        df.index = df.index.tz_localize(None)
        return df
    except Exception as e:
        print(f"yfinance fetch failed: {e}")
        return pd.DataFrame()

def calculate_rsi(series, period=9):
    delta = series.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    
    # Wilder's Smoothing for RSI
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calculate_wma(series, period=21):
    weights = np.arange(1, period + 1)
    return series.rolling(period).apply(lambda prices: np.dot(prices, weights) / weights.sum(), raw=True)

def resample_ticks_to_candles(tick_history, timeframe='5min'):
    """
    Converts a list of (datetime, price) ticks into an OHLC pandas DataFrame.
    """
    if not tick_history or len(tick_history) < 20:
        return pd.DataFrame()
        
    df = pd.DataFrame(tick_history, columns=['timestamp', 'price'])
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df.set_index('timestamp', inplace=True)
    
    # Resample to OHLC
    ohlc = df['price'].resample(timeframe).ohlc()
    ohlc = ohlc.dropna()
    return ohlc

def get_optimal_strike(spot_price, is_bank_nifty, direction):
    """
    Calculates the 1-strike ITM optimal strike for Delta ~0.60.
    Nifty interval = 50, Bank Nifty interval = 100.
    """
    interval = 100 if is_bank_nifty else 50
    
    # Find nearest ATM
    atm_strike = round(spot_price / interval) * interval
    
    if direction == "BULLISH":
        # Call ITM
        return atm_strike - interval, "CE"
    elif direction == "BEARISH":
        # Put ITM
        return atm_strike + interval, "PE"
    
    return 0, ""

def process_hm_logic(df_live, spot_price, is_bank_nifty=False, warmup_df=None):
    """
    Runs NK Sir's Hilega Milega logic on a 5-min OHLC dataframe.
    Returns (signal_type, strike, opt_type, rsi, wma, ema, sma)
    signal_type: 'BULLISH', 'BEARISH', or 'NEUTRAL'
    """
    if warmup_df is not None and not warmup_df.empty:
        if not df_live.empty:
            df = pd.concat([warmup_df, df_live])
            df = df[~df.index.duplicated(keep='last')].sort_index()
        else:
            df = warmup_df.copy()
    else:
        df = df_live.copy()
        
    if len(df) < 22: # Need enough candles for WMA(21)
        return "NEUTRAL", 0, "", 0, 0, 0, 0
        
    try:
        # Hilega Milega Math (Manual to avoid dependency issues on python 3.14)
        
        # 1. Base RSI(9)
        df['RSI_9'] = calculate_rsi(df['close'], period=9)
        
        # 2. Trend WMA(21) applied to RSI(9)
        df['WMA_21'] = calculate_wma(df['RSI_9'], period=21)
        
        # 3. Trigger EMA(3) applied to RSI(9)
        df['EMA_3'] = df['RSI_9'].ewm(span=3, adjust=False).mean()
        
        # 4. Chart Anchor SMA(5) on Price Close
        df['SMA_5'] = df['close'].rolling(window=5).mean()
        
        # Get latest closed candle values
        latest = df.iloc[-1]
        
        rsi_val = round(latest['RSI_9'], 2) if not pd.isna(latest['RSI_9']) else 0
        wma_val = round(latest['WMA_21'], 2) if not pd.isna(latest['WMA_21']) else 0
        ema_val = round(latest['EMA_3'], 2) if not pd.isna(latest['EMA_3']) else 0
        sma_val = round(latest['SMA_5'], 2) if not pd.isna(latest['SMA_5']) else 0
        close_price = latest['close']
        
        signal = "NEUTRAL"
        
        # Bullish (Call) Signal
        if (rsi_val > wma_val) and (ema_val > rsi_val) and (close_price > sma_val):
            signal = "BULLISH"
            
        # Bearish (Put) Signal - Exact Inverse
        elif (rsi_val < wma_val) and (ema_val < rsi_val) and (close_price < sma_val):
            signal = "BEARISH"
            
        strike, opt_type = get_optimal_strike(spot_price, is_bank_nifty, signal)
        
        return signal, strike, opt_type, rsi_val, wma_val, ema_val, sma_val
        
    except Exception as e:
        print(f"HM Engine Math Error: {e}")
        return "NEUTRAL", 0, "", 0, 0, 0, 0

def format_telegram_alert(signal, index_name, strike, opt_type, spot):
    emoji = "🟢" if signal == "BULLISH" else "🔴"
    return f"""{emoji} HM MOMENTUM ALERT — {index_name}
━━━━━━━━━━━━━━━━━━━
Direction : {signal}
Trade     : BUY {opt_type} {strike}
Spot Price: {spot:.1f}
━━━━━━━━━━━━━━━━━━━
(1 Strike ITM - Delta ~0.60)"""
