import numpy as np
import pandas as pd
from datetime import datetime, timedelta

class ReversalEngine:
    def __init__(self):
        self.ticks = []
        self.session_vwap_num = 0.0
        self.session_vol = 0.0
        self.current_vwap = 0.0
        
        self.last_price = None
        self.cumulative_delta = 0.0
        
    def infer_aggressor(self, ltp, bid, ask):
        # Extremely basic aggressor inference based on price movement
        if self.last_price is None:
            return 0
        if ltp > self.last_price: return 1
        if ltp < self.last_price: return -1
        # Fallback to bid/ask skew if price didn't change
        if bid > ask: return 1
        if ask > bid: return -1
        return 0

    def process_tick(self, ltp, vol, bid=0, ask=0):
        now = datetime.now()
        
        # 1. Update CVD (Cumulative Volume Delta)
        aggressor = self.infer_aggressor(ltp, bid, ask)
        tick_delta = aggressor * vol
        self.cumulative_delta += tick_delta
        
        # 2. Update VWAP
        self.session_vwap_num += (ltp * vol)
        self.session_vol += vol
        if self.session_vol > 0:
            self.current_vwap = self.session_vwap_num / self.session_vol
            
        self.last_price = ltp
        
        # Save tick history (limit to last 500 to save memory)
        self.ticks.append({
            'time': now,
            'price': ltp,
            'vol': vol,
            'cvd': self.cumulative_delta,
            'vwap': self.current_vwap
        })
        if len(self.ticks) > 500:
            self.ticks.pop(0)
            
        # Return state
        return self.evaluate_market_state()

    def evaluate_market_state(self):
        if len(self.ticks) < 30:
            return "SIDEWAYS"
            
        df = pd.DataFrame(self.ticks)
        current_ltp = df['price'].iloc[-1]
        
        # Calculate VWAP Standard Deviation (approx 200 ticks or session)
        # Using the last 500 ticks for variance calculation
        variance = ((df['price'] - self.current_vwap)**2 * df['vol']).sum() / df['vol'].sum()
        std_dev = np.sqrt(variance)
        
        upper_band = self.current_vwap + (2.5 * std_dev)
        lower_band = self.current_vwap - (2.5 * std_dev)
        
        # Check condition 2: Outside 2.5 sigma
        outside_lower = current_ltp < lower_band
        outside_upper = current_ltp > upper_band
        
        # Check condition 1: CVD Divergence
        # For long reversal (downtrend exhaustion):
        # Price is making lower lows, but CVD is strictly positive sloping
        recent_15 = df.tail(15)
        cvd_slope = np.polyfit(np.arange(15), recent_15['cvd'], 1)[0]
        price_slope = np.polyfit(np.arange(15), recent_15['price'], 1)[0]
        
        cvd_bull_divergence = price_slope < 0 and cvd_slope > 0
        cvd_bear_divergence = price_slope > 0 and cvd_slope < 0
        
        # Check condition 3: Order Flow Exhaustion
        # Downward volume acceleration is negative (sellers running out)
        # We estimate this by looking at volume over the last 3 minutes
        three_mins_ago = df['time'].iloc[-1] - timedelta(minutes=3)
        recent_3m = df[df['time'] >= three_mins_ago]
        
        if len(recent_3m) < 10:
            return "SIDEWAYS"
            
        vol_slope = np.polyfit(np.arange(len(recent_3m)), recent_3m['vol'], 1)[0]
        vol_exhausted = vol_slope < 0
        
        # Determine Market State
        if outside_lower and cvd_bull_divergence and vol_exhausted:
            return "REVERSAL_LONG"
            
        if outside_upper and cvd_bear_divergence and vol_exhausted:
            return "REVERSAL_SHORT"
            
        # If not reversing, check if trending
        if current_ltp > self.current_vwap + (1.0 * std_dev) and price_slope > 0:
            return "TRENDING_UP"
            
        if current_ltp < self.current_vwap - (1.0 * std_dev) and price_slope < 0:
            return "TRENDING_DOWN"
            
        return "SIDEWAYS"
