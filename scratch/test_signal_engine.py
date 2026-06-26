import unittest
from datetime import date, time, datetime, timedelta
import sys
import os
import pandas as pd

# Add parent directory to path so we can import signal_engine
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import signal_engine

class TestSignalEngine(unittest.TestCase):

    def test_dte_calculations(self):
        """Verify DTE relative to next/current Tuesday."""
        # 2026-06-23 is a Tuesday
        self.assertEqual(signal_engine.get_dte(date(2026, 6, 23)), 0, "Tuesday should be DTE 0")
        # 2026-06-22 is a Monday
        self.assertEqual(signal_engine.get_dte(date(2026, 6, 22)), 1, "Monday should be DTE 1")
        # 2026-06-21 is a Sunday
        self.assertEqual(signal_engine.get_dte(date(2026, 6, 21)), 2, "Sunday should be DTE 2")
        # 2026-06-20 is a Saturday
        self.assertEqual(signal_engine.get_dte(date(2026, 6, 20)), 3, "Saturday should be DTE 3")
        # 2026-06-19 is a Friday
        self.assertEqual(signal_engine.get_dte(date(2026, 6, 19)), 4, "Friday should be DTE 4")
        # 2026-06-18 is a Thursday
        self.assertEqual(signal_engine.get_dte(date(2026, 6, 18)), 5, "Thursday should be DTE 5")
        # 2026-06-17 is a Wednesday
        self.assertEqual(signal_engine.get_dte(date(2026, 6, 17)), 6, "Wednesday should be DTE 6")

    def test_active_thresholds_scaling(self):
        """Verify active thresholds are computed correctly for each DTE, including absolute overrides."""
        # Tuesday Expiry (DTE 0)
        t_tue = signal_engine.get_active_thresholds(0)
        self.assertEqual(t_tue["ofi_sweep_contracts"], 840)       # 300 * 2.8
        self.assertEqual(t_tue["score_threshold"], 70.0)          # 55 * 1.2727 = 70.0 (rounded)
        self.assertEqual(t_tue["patience_minutes"], 3.0)          # 15 * 0.20
        self.assertEqual(t_tue["stop_loss_mult"], 0.95)           # Absolute override (5% SL)
        self.assertEqual(t_tue["take_profit_mult"], 1.20)         # Absolute override (20% TP)
        self.assertEqual(t_tue["trailing_stop_mult"], 0.97)       # Absolute override (3% Trail)

        # Monday (DTE 1)
        t_mon = signal_engine.get_active_thresholds(1)
        self.assertEqual(t_mon["ofi_sweep_contracts"], 600)       # 300 * 2.0
        self.assertEqual(t_mon["score_threshold"], 65.0)          # 55 * 1.1818 = 65.0
        self.assertEqual(t_mon["patience_minutes"], 6.0)          # 15 * 0.40
        self.assertEqual(t_mon["stop_loss_mult"], 0.93)           # Absolute override (7% SL)
        self.assertEqual(t_mon["take_profit_mult"], 1.25)         # Absolute override (25% TP)

        # Friday (DTE 4)
        t_fri = signal_engine.get_active_thresholds(4)
        self.assertEqual(t_fri["ofi_sweep_contracts"], 300)       # Base
        self.assertEqual(t_fri["score_threshold"], 55.0)          # Base
        self.assertEqual(t_fri["patience_minutes"], 15.0)         # Base
        self.assertEqual(t_fri["stop_loss_mult"], 0.88)           # Base (12% SL)
        self.assertEqual(t_fri["take_profit_mult"], 1.35)         # Base (35% TP)

        # Thursday (DTE 5)
        t_thu = signal_engine.get_active_thresholds(5)
        self.assertEqual(t_thu["ofi_sweep_contracts"], 390)       # 300 * 1.3
        self.assertEqual(t_thu["score_threshold"], 58.0)          # 55 * 1.0545 = 58.0
        self.assertEqual(t_thu["patience_minutes"], 12.0)         # 15 * 0.80
        self.assertEqual(t_thu["stop_loss_mult"], 0.90)           # Absolute override (10% SL)
        self.assertEqual(t_thu["take_profit_mult"], 1.30)         # Absolute override (30% TP)

        # Wednesday (DTE 6)
        t_wed = signal_engine.get_active_thresholds(6)
        self.assertEqual(t_wed["ofi_sweep_contracts"], 480)       # 300 * 1.6
        self.assertEqual(t_wed["score_threshold"], 60.0)          # 55 * 1.0909 = 60.0
        self.assertEqual(t_wed["patience_minutes"], 9.0)          # 15 * 0.60
        self.assertEqual(t_wed["stop_loss_mult"], 0.91)           # Absolute override (9% SL)
        self.assertEqual(t_wed["take_profit_mult"], 1.28)         # Absolute override (28% TP)

    def test_strike_recommender(self):
        """Verify strike offsets for Wednesday, Thursday, Friday, Monday, and Tuesday."""
        # Spot = 24350, Strike Interval = 50
        r_tue = signal_engine.get_recommended_strike_tier(0, 24350)
        self.assertEqual(r_tue["ce_strike"], 24350)
        self.assertEqual(r_tue["pe_strike"], 24350)

        r_mon = signal_engine.get_recommended_strike_tier(1, 24350)
        self.assertEqual(r_mon["ce_strike"], 24350)
        self.assertEqual(r_mon["pe_strike"], 24350)

        r_fri = signal_engine.get_recommended_strike_tier(4, 24350)
        self.assertEqual(r_fri["ce_strike"], 24400) # OTM-1 (24350 + 50)
        self.assertEqual(r_fri["pe_strike"], 24300) # OTM-1 (24350 - 50)

        r_thu = signal_engine.get_recommended_strike_tier(5, 24350)
        self.assertEqual(r_thu["ce_strike"], 24400) # OTM-1
        self.assertEqual(r_thu["pe_strike"], 24300) # OTM-1

        r_wed = signal_engine.get_recommended_strike_tier(6, 24350)
        self.assertEqual(r_wed["ce_strike"], 24400) # OTM-1
        self.assertEqual(r_wed["pe_strike"], 24300) # OTM-1

    def test_time_in_trade_kill(self):
        """Verify that trade is closed out at breakeven if halfmove is not achieved within patience window."""
        # Open trade on Wednesday (DTE 6)
        # Entry price = 100.0, target = 128.0 (28% TP), stop = 91.0 (9% SL), patience = 9 minutes
        trade = signal_engine.open_trade(entry_price=100.0, opt_type="CE", dte=6)
        self.assertEqual(trade["target"], 128.0)
        self.assertEqual(trade["stop"], 91.0)
        self.assertEqual(trade["patience_minutes"], 9.0)
        self.assertFalse(trade["halfmove_hit"])

        # Simulate price tick before patience window expires (e.g. 5 minutes elapsed)
        # Halfmove target is 100.0 + (128.0 - 100.0) * 0.5 = 114.0
        # Price is at 105.0 (no halfmove achieved, but elapsed < patience)
        trade["entry_time"] = datetime.now() - timedelta(minutes=5)
        status, updated_trade = signal_engine.manage_trade(trade, current_ltp=105.0)
        self.assertEqual(status, "ACTIVE")
        self.assertEqual(updated_trade["stop"], 91.0) # Stop should remain unchanged

        # Price achieves halfmove at 6 minutes
        trade["entry_time"] = datetime.now() - timedelta(minutes=6)
        status, updated_trade = signal_engine.manage_trade(trade, current_ltp=115.0)
        self.assertEqual(status, "ACTIVE")
        self.assertTrue(updated_trade["halfmove_hit"])

        # Reset trade to test TIME_KILL activation
        trade = signal_engine.open_trade(entry_price=100.0, opt_type="CE", dte=6)
        # Simulate price tick after patience window expires (e.g. 10 minutes elapsed)
        # Price at 105.0 (halfmove of 114.0 never hit)
        trade["entry_time"] = datetime.now() - timedelta(minutes=10)
        status, updated_trade = signal_engine.manage_trade(trade, current_ltp=105.0)
        self.assertEqual(status, "ACTIVE")
        self.assertEqual(updated_trade["stop"], 100.0) # Stop should be moved to entry price (breakeven)

        # Simulate next tick where price goes below breakeven stop (e.g. 99.5)
        status, final_trade = signal_engine.manage_trade(updated_trade, current_ltp=99.5)
        self.assertEqual(status, "TIME_KILL")

    def test_tod_session_blocks(self):
        """Verify that Dead Zone blocks signals, while Gamma Window provides modifier bonuses."""
        # Fake dataframe with 10 rows
        df = pd.DataFrame({
            "DATETIME": [datetime.now() - timedelta(minutes=i) for i in range(10)],
            "CLOSE": [100.0] * 10,
            "VOLUME": [100.0] * 10,
            "OI": [1000.0] * 10
        })

        # Test Dead Zone block (13:00 to 13:29)
        res_blocked = signal_engine.check_ai_buy_signal(
            df=df, nifty_ofi=100, opt_type="CE", current_time=time(13, 15), dte=4
        )
        self.assertTrue(res_blocked.blocked.startswith("SESSION_BLOCK:DEAD_ZONE"))
        self.assertFalse(res_blocked.fired)

        # Test Gamma Window threshold adjustment (14:00 to 15:15)
        # Base score threshold is 55.0. In Gamma Window it should be reduced by 5.0 points to 50.0.
        res_gamma = signal_engine.check_ai_buy_signal(
            df=df, nifty_ofi=100, opt_type="CE", current_time=time(14, 15), dte=4
        )
        self.assertEqual(res_gamma.thresholds["score_threshold"] - 5.0, 50.0)

if __name__ == "__main__":
    unittest.main()
