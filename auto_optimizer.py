import os
import json
import csv
from datetime import datetime, timedelta

def run_optimization():
    print("============================================================")
    print("  WALK-FORWARD OPTIMIZER (WFO) - REGIME ANALYSIS")
    print("============================================================")
    
    csv_file = "live_trade_journal.csv"
    params_file = "optimized_params.json"
    
    # Default parameters (Deterministic Baseline)
    params = {
        "take_profit_mult": 1.30,
        "stop_loss_mult": 0.90,
        "trailing_activation_pct": 0.05,
        "trailing_stop_mult": 0.90,
        "ofi_threshold": 0.08
    }
    
    regime = "NORMAL (Default)"
    win_rate = 0.0
    
    if os.path.exists(csv_file):
        try:
            trades = []
            with open(csv_file, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    trades.append(row)
                    
            if len(trades) >= 5:
                # Look at recent trades (up to 20)
                recent_trades = trades[-20:]
                wins = sum(1 for t in recent_trades if float(t.get('P/L %', 0)) > 0 or "TARGET" in t.get('Result', ''))
                win_rate = wins / len(recent_trades)
                
                if win_rate < 0.40:
                    regime = "CHOPPY (Low Win Rate)"
                    params["take_profit_mult"] = 1.20  # Quick profit taking
                    params["stop_loss_mult"] = 0.88    # Wider stop to avoid noise
                    params["ofi_threshold"] = 0.12     # Require stronger OFI confirmation
                elif win_rate >= 0.60:
                    regime = "TRENDING (High Win Rate)"
                    params["take_profit_mult"] = 1.40  # Let winners run
                    params["stop_loss_mult"] = 0.92    # Tighten stop to protect capital
                    params["trailing_activation_pct"] = 0.10 # Wait longer before trailing
        except Exception as e:
            print(f"[!] Error reading journal: {e}")
            print("Falling back to default parameters.")
            
    with open(params_file, 'w') as f:
        json.dump(params, f, indent=4)
        
    print(f"[*] Detected Market Regime: {regime}")
    if win_rate > 0:
        print(f"[*] Recent Win Rate: {win_rate*100:.1f}%")
    print(f"[*] Stop Loss Multiplier: {params['stop_loss_mult']}")
    print(f"[*] Take Profit Multiplier: {params['take_profit_mult']}")
    print(f"[*] OFI Confirmation Threshold: {params['ofi_threshold']}")
    print("============================================================")
    print("  OPTIMIZATION COMPLETE. PARAMETERS INJECTED.")
    print("============================================================\n")

if __name__ == "__main__":
    run_optimization()
