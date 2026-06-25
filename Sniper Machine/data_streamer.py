import json
import threading
import time
import sys
import os
import numpy as np

from config import API_KEY, DELTA_TARGET_MIN, DELTA_TARGET_MAX, TARGET_POINTS, STOP_LOSS_POINTS
from scalp_engine import NiftyScalpEngine
from telegram_bot import send_telegram_alert

class DataStreamer:
    def __init__(self):
        self.engine = NiftyScalpEngine()
        self.is_connected = False
        self.active_signal = None
        self.last_signal_time = 0
        self.cooldown_seconds = 300 # Wait 5 mins between signals

    def process_tick(self, scrip_code, ltp, volume, bid_qty, ask_qty):
        """Called whenever a new tick arrives from Sharekhan WebSocket"""
        
        # In a real scenario, you filter for Nifty Spot or Future scrip code here.
        # Assuming scrip_code is the Nifty Future:
        signal, reason, metrics = self.engine.evaluate_trend(ltp, volume, bid_qty, ask_qty)
        
        # We only want to alert if there's a BUY signal and we aren't in cooldown
        current_time = time.time()
        
        if "BUY" in signal and (current_time - self.last_signal_time) > self.cooldown_seconds:
            self.last_signal_time = current_time
            self._dispatch_signal(signal, reason, ltp, metrics)
            
        return signal, reason, metrics

    def _dispatch_signal(self, signal, reason, current_price, metrics):
        """Constructs and sends the alert to Telegram and Dashboard"""
        action = "CALL" if signal == "BUY_CALL" else "PUT"
        
        # Math: Calculate exact strike (Mocking the exact selection here)
        # Usually ATM is closest 50 or 100 strike
        strike_base = round(current_price / 50) * 50
        strike_offset = -50 if action == "CALL" else 50 # ITM roughly Delta ~0.55
        target_strike = strike_base + strike_offset
        
        msg = f"🚨 *SNIPER SIGNAL: BUY {action}* 🚨\n"
        msg += f"========================\n"
        msg += f"Instrument: *NIFTY {target_strike} {action[0]}E*\n"
        msg += f"Reason: {reason}\n"
        msg += f"Nifty Future LTP: {current_price}\n\n"
        
        msg += f"🎯 Target: +{TARGET_POINTS} Points\n"
        msg += f"🛑 Stop Loss: -{STOP_LOSS_POINTS} Points\n\n"
        
        msg += f"📊 *Live Metrics:*\n"
        msg += f"• Price Slope: {metrics.get('price_slope')}\n"
        msg += f"• VWAP: {metrics.get('vwap')}\n"
        msg += f"• Cum Delta Ratio: {metrics.get('cd_ratio')}\n"
        
        send_telegram_alert(msg)
        self.active_signal = msg # Save for dashboard

        # Log the signal to a CSV file
        try:
            import csv
            from datetime import datetime
            log_file = r"c:\sharekhan_terminal\Sniper Machine\trade_log.csv"
            file_exists = os.path.exists(log_file)
            with open(log_file, mode='a', newline='') as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow(["Timestamp", "Signal", "Target Strike", "Reason", "Nifty LTP", "Price Slope", "VWAP", "Imbalance", "Vol Slope", "CD Ratio"])
                writer.writerow([
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    f"BUY {action}",
                    f"NIFTY {target_strike} {action[0]}E",
                    reason,
                    current_price,
                    metrics.get('price_slope'),
                    metrics.get('vwap'),
                    metrics.get('imbalance', 0),
                    metrics.get('vol_slope', 0),
                    metrics.get('cd_ratio', 0)
                ])
        except Exception as e:
            print(f"Failed to log to CSV: {e}")

    def get_nifty_futures_token(self):
        try:
            import pandas as pd
            df = pd.read_csv(r"c:\sharekhan_terminal\nf_scrip_master_expanded.csv")
            futures = df[
                (df['tradingSymbol'].str.upper().str.startswith('NIFTY')) &
                (~df['tradingSymbol'].str.upper().str.startswith('BANKNIFTY')) &
                (df['instType'] == 'FI')
            ].copy()
            futures['expiry_dt'] = pd.to_datetime(futures['expiry'], dayfirst=True, errors='coerce')
            from datetime import datetime
            futures = futures[futures['expiry_dt'].dt.date >= datetime.now().date()]
            futures = futures.sort_values('expiry_dt')
            if not futures.empty:
                return f"NF{int(futures.iloc[0]['scripCode'])}"
        except Exception as e:
            print("Error getting token:", e)
        return "NF62329"

    def start_live_stream(self):
        """Reads live data from parent live_ticks.json"""
        print("Starting LIVE Stream reading from C:\\sharekhan_terminal\\live_ticks.json...")
        futures_token = self.get_nifty_futures_token()
        print(f"Tracking Nifty Futures Token: {futures_token}")
        
        while True:
            try:
                if os.path.exists(r"c:\sharekhan_terminal\live_ticks.json"):
                    with open(r"c:\sharekhan_terminal\live_ticks.json", "r") as f:
                        ticks = json.load(f)
                    
                    if futures_token in ticks:
                        tick = ticks[futures_token]
                        price = float(tick.get("ltp", 0.0))
                        vol = int(tick.get("qty", 0))
                        bid = float(tick.get("bidQty", 0))
                        ask = float(tick.get("offQty", 0))
                        
                        if price > 0:
                            # Log every single tick for ML history
                            try:
                                import csv
                                from datetime import datetime
                                tick_log = r"c:\sharekhan_terminal\Sniper Machine\daily_tick_history.csv"
                                file_exists = os.path.exists(tick_log)
                                with open(tick_log, mode='a', newline='') as f:
                                    writer = csv.writer(f)
                                    if not file_exists:
                                        writer.writerow(["Timestamp", "Price", "Volume", "Bid_Qty", "Ask_Qty"])
                                    writer.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), price, vol, bid, ask])
                            except:
                                pass

                            signal, reason, metrics = self.process_tick(futures_token, price, vol, bid, ask)
            except Exception as e:
                pass
                
            time.sleep(1.0)

    def start_mock_stream(self):
        """Simulates incoming ticks to test the math engine"""
        print("Starting Mock Stream (Since real WS needs live token)...")
        price = 22500.0
        
        while True:
            # Random walk
            change = np.random.normal(0, 1.5)
            price += change
            vol = np.random.randint(50, 500)
            
            # Simulate market dynamics
            rand_event = np.random.random()
            if rand_event < 0.02:
                # Sudden Fakeout (Price spikes, but heavy sellers on Ask)
                price += 12.0 
                bid = 1000
                ask = 25000
            elif rand_event < 0.04:
                # Real Breakout Setup (Price spikes, heavy buyers on Bid)
                price += 15.0
                bid = 30000
                ask = 1000
            else:
                # Normal noise
                bid = np.random.randint(1000, 6000)
                ask = np.random.randint(1000, 6000)
                
            signal, reason, metrics = self.process_tick("NIFTY_FUT", price, vol, bid, ask)
            time.sleep(1.0) # Tick every 1 second so dashboard looks alive

if __name__ == "__main__":
    streamer = DataStreamer()
    streamer.start_live_stream()
