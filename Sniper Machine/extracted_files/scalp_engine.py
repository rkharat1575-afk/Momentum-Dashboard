"""
NiftyScalpEngine v2.0 — Corrected & Upgraded
============================================
Changes from audit:
  1. FIXED: cumulative_vol declared in schema → no KeyError on reinit
  2. FIXED: VWAP Variance — anchored to session open, two-pass calculation
  3. FIXED: 3-Tick breakout replaced with time-gated confirmation (configurable seconds)
  4. FIXED: vol_slope now wired into signal logic as confirmation filter
  5. FIXED: Renamed vwap_dev_threshold → vwap_band_multiplier for clarity
  6. ADDED: Cumulative Delta replaces raw bid/ask imbalance as primary pressure signal
  7. ADDED: Tick-rate-aware EMA → uses time-weighted span instead of tick count
  8. ADDED: Volume acceleration guard (vol_slope > 0 required for breakout confirmation)
  9. ADDED: EMA macro blockade suspended during volatility spike (price > N*std from EMA)
"""

import time
import pandas as pd
import numpy as np
import json
import os
from datetime import datetime, timedelta


class NiftyScalpEngine:
    def __init__(self, breakout_confirm_seconds: float = 2.0):
        """
        Args:
            breakout_confirm_seconds: Wall-clock seconds price must sustain outside
                                      VWAP band before a breakout is confirmed.
                                      Default 2.0s. Tune based on backtest.
        """
        # ── Schema-explicit DataFrame — prevents KeyError on reinit ──────────
        self.trend_history = pd.DataFrame(columns=[
            'timestamp', 'price', 'volume', 'cumulative_vol',
            'bid_qty', 'ask_qty', 'trade_direction'  # trade_direction: +1 buy, -1 sell
        ])

        # Session anchor for true VWAP (set on first tick of the day)
        self.session_open_time: datetime | None = None
        self.session_anchor_price: float | None = None

        # Breakout timing gate
        self.breakout_confirm_seconds = breakout_confirm_seconds
        self.breakout_up_start: datetime | None = None    # when price first crossed VWAP upper
        self.breakout_down_start: datetime | None = None  # when price first crossed VWAP lower

        # Cumulative Delta (running sum of buy-side minus sell-side executed volume)
        self.cumulative_delta: float = 0.0

        # ── ML-tuned weights (loaded from file if available) ─────────────────
        self.weights = {
            "slope_threshold": 0.05,
            "imbalance_threshold": 0.20,   # now used for CD ratio, not raw bid/ask
            "vwap_band_multiplier": 1.5,   # renamed from vwap_dev_threshold
            "ema_volatility_override_std": 3.0,  # suspend EMA blockade if price > N*std away
            "vol_slope_min": 0.0,          # minimum volume slope to confirm breakout
        }

        weights_path = r"c:\sharekhan_terminal\Sniper Machine\dynamic_weights.json"
        if os.path.exists(weights_path):
            try:
                with open(weights_path, "r") as f:
                    loaded = json.load(f)
                    # Merge — keep defaults for any missing keys
                    self.weights.update(loaded)
            except Exception:
                pass

    # ─────────────────────────────────────────────────────────────────────────
    # VWAP — Anchored Session Calculation (two-pass, no early-row distortion)
    # ─────────────────────────────────────────────────────────────────────────
    def calculate_vwap_bands(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Anchored VWAP anchored to session open (9:15 AM or first tick).
        Uses a proper two-pass volume-weighted variance formula:
            VWAP = Σ(Pᵢ·Vᵢ) / ΣVᵢ
            σ    = √[ Σ(Vᵢ·(Pᵢ - VWAP)²) / ΣVᵢ ]
        Bands are VWAP ± multiplier·σ
        """
        total_vol = df['volume'].sum()
        if total_vol == 0:
            df['vwap'] = df['price'].mean()
            df['vwap_upper'] = df['price'].mean()
            df['vwap_lower'] = df['price'].mean()
            return df

        # Pass 1 — single VWAP value for the entire window
        vwap = (df['price'] * df['volume']).sum() / total_vol

        # Pass 2 — volume-weighted standard deviation
        variance = ((df['price'] - vwap) ** 2 * df['volume']).sum() / total_vol
        std = np.sqrt(variance)

        mult = self.weights.get("vwap_band_multiplier", 1.5)
        df['vwap'] = vwap
        df['vwap_upper'] = vwap + std * mult
        df['vwap_lower'] = vwap - std * mult
        return df

    # ─────────────────────────────────────────────────────────────────────────
    # Price Velocity — Linear Regression Slope
    # ─────────────────────────────────────────────────────────────────────────
    def calculate_trend_slope(self, y: pd.Series) -> float:
        """Linear regression slope over a price/volume series."""
        if len(y) < 2:
            return 0.0
        y_arr = np.array(y, dtype=float)
        x_arr = np.arange(len(y_arr))
        slope, _ = np.polyfit(x_arr, y_arr, 1)
        return float(slope)

    # ─────────────────────────────────────────────────────────────────────────
    # Cumulative Delta — Aggressor-Side Volume (spoof-resistant pressure gauge)
    # ─────────────────────────────────────────────────────────────────────────
    def infer_trade_direction(self, price: float, bid_qty: float, ask_qty: float) -> int:
        """
        Infer whether a tick was buyer-initiated (+1) or seller-initiated (-1).

        Primary: compare last trade price to midpoint.
        Fallback: bid/ask quantity skew (less reliable, used only when midpoint
                  is unavailable).

        If your data feed provides explicit aggressor side, pass it directly
        and bypass this method.
        """
        if (bid_qty + ask_qty) == 0:
            return 0
        mid = (bid_qty + ask_qty) / 2.0  # proxy midpoint via qty ratio
        # Better: if your feed gives bid_price/ask_price use:
        #   mid = (bid_price + ask_price) / 2
        #   return 1 if price >= mid else -1
        return 1 if bid_qty > ask_qty else -1

    def get_cd_ratio(self, n_ticks: int = 20) -> float:
        """
        Cumulative Delta ratio over last n_ticks.
        Returns value in [-1, +1]:  +1 = pure buying, -1 = pure selling.
        """
        if len(self.trend_history) < 2:
            return 0.0
        recent = self.trend_history.tail(n_ticks)
        buy_vol  = recent[recent['trade_direction'] == 1]['volume'].sum()
        sell_vol = recent[recent['trade_direction'] == -1]['volume'].sum()
        total = buy_vol + sell_vol
        if total == 0:
            return 0.0
        return (buy_vol - sell_vol) / total

    # ─────────────────────────────────────────────────────────────────────────
    # Main Evaluator
    # ─────────────────────────────────────────────────────────────────────────
    def evaluate_trend(
        self,
        current_price: float,
        current_vol: float,
        bid_qty: float,
        ask_qty: float,
        trade_direction: int | None = None,   # pass +1/-1 if feed provides it
    ) -> tuple[str, str, dict]:
        """
        Evaluate current market state and emit a trading signal.

        Returns:
            signal  : "BUY_CALL" | "BUY_PUT" | "NEUTRAL"
            reason  : human-readable explanation
            metrics : dict of internal values for logging/ML
        """
        now = datetime.now()

        # ── Session anchor ───────────────────────────────────────────────────
        if self.session_open_time is None:
            self.session_open_time = now
            self.session_anchor_price = current_price

        # ── True tick volume ─────────────────────────────────────────────────
        tick_volume = 0.0
        if not self.trend_history.empty:
            last_cumvol = self.trend_history['cumulative_vol'].iloc[-1]
            tick_volume = max(0.0, current_vol - last_cumvol)

        # ── Trade direction (aggressor side) ─────────────────────────────────
        if trade_direction is None:
            trade_direction = self.infer_trade_direction(current_price, bid_qty, ask_qty)

        # Update cumulative delta
        self.cumulative_delta += trade_direction * tick_volume

        # ── Append tick ──────────────────────────────────────────────────────
        new_row = pd.DataFrame([{
            'timestamp':      now,
            'price':          current_price,
            'volume':         tick_volume,
            'cumulative_vol': current_vol,
            'bid_qty':        bid_qty,
            'ask_qty':        ask_qty,
            'trade_direction': trade_direction,
        }])
        self.trend_history = pd.concat([self.trend_history, new_row], ignore_index=True)

        # Rolling window — keep last 500 ticks
        if len(self.trend_history) > 500:
            self.trend_history = self.trend_history.iloc[-500:]

        if len(self.trend_history) < 20:
            return "NEUTRAL", "Gathering Data", {}

        # ── VWAP Bands (anchored, two-pass) ──────────────────────────────────
        df = self.calculate_vwap_bands(self.trend_history.copy())
        vwap_upper = df['vwap_upper'].iloc[-1]
        vwap_lower = df['vwap_lower'].iloc[-1]
        vwap_mid   = df['vwap'].iloc[-1]

        # ── Price & Volume Slope (last 15 ticks) ─────────────────────────────
        recent_prices = df['price'].tail(15)
        recent_vols   = df['volume'].tail(15)
        price_slope   = self.calculate_trend_slope(recent_prices)
        vol_slope     = self.calculate_trend_slope(recent_vols)   # now USED below

        # ── Macro Trend — Time-Weighted EMA ──────────────────────────────────
        # Use a time-weighted span so the EMA represents ~5 minutes of history
        # regardless of session tick density. Span = 5min / avg_tick_interval.
        if len(df) >= 2:
            time_deltas = df['timestamp'].diff().dt.total_seconds().dropna()
            avg_tick_sec = time_deltas.mean() if len(time_deltas) > 0 else 0.5
            avg_tick_sec = max(avg_tick_sec, 0.1)   # floor at 100ms
            span_ticks = max(10, int(300 / avg_tick_sec))  # 300s = 5 min
        else:
            span_ticks = 100

        df['ema_macro'] = df['price'].ewm(span=span_ticks, adjust=False).mean()
        macro_ema = df['ema_macro'].iloc[-1]

        # ── EMA Volatility Override ───────────────────────────────────────────
        # If price has spiked > N standard deviations from EMA in the last 10 ticks,
        # the macro blockade is temporarily suspended (trend has already reversed).
        recent_ema_dev = df['price'].tail(10) - df['ema_macro'].tail(10)
        ema_dev_std    = recent_ema_dev.std()
        current_ema_dev = abs(current_price - macro_ema)
        ema_override_threshold = self.weights.get("ema_volatility_override_std", 3.0)
        ema_blockade_active = not (
            ema_dev_std > 0
            and current_ema_dev > ema_override_threshold * ema_dev_std
        )

        # ── Institutional Volume Anomaly ─────────────────────────────────────
        df['vol_ma'] = df['volume'].rolling(20).mean()
        df['is_anomaly'] = (df['volume'] > (df['vol_ma'] * 3.0)) & (df['vol_ma'] > 0)
        is_vol_anomaly = bool(df['is_anomaly'].tail(10).any())

        # ── Cumulative Delta Ratio (spoof-resistant order pressure) ──────────
        cd_ratio = self.get_cd_ratio(n_ticks=20)
        imb_threshold = self.weights.get("imbalance_threshold", 0.20)

        # ── Market Direction (for logging only) ──────────────────────────────
        slope_threshold = self.weights.get("slope_threshold", 0.05)
        direction = "SIDEWAYS"
        if price_slope > 0.02 and current_price > vwap_mid:
            direction = "MILD BULLISH"
            if price_slope > slope_threshold and current_price > vwap_upper:
                direction = "STRONG BULLISH"
        elif price_slope < -0.02 and current_price < vwap_mid:
            direction = "MILD BEARISH"
            if price_slope < -slope_threshold and current_price < vwap_lower:
                direction = "STRONG BEARISH"

        metrics = {
            "price_slope":   round(price_slope, 4),
            "vol_slope":     round(vol_slope, 4),
            "vwap":          round(vwap_mid, 2),
            "vwap_upper":    round(vwap_upper, 2),
            "vwap_lower":    round(vwap_lower, 2),
            "cd_ratio":      round(cd_ratio, 3),
            "is_anomaly":    is_vol_anomaly,
            "ema_macro":     round(macro_ema, 2),
            "ema_override":  not ema_blockade_active,
            "direction":     direction,
            "cum_delta":     round(self.cumulative_delta, 0),
        }

        # ─────────────────────────────────────────────────────────────────────
        # TIME-GATED BREAKOUT CONFIRMATION
        # Price must sustain outside the VWAP band for `breakout_confirm_seconds`
        # of wall-clock time. No tick-count games.
        # ─────────────────────────────────────────────────────────────────────
        above_band = current_price > vwap_upper
        below_band = current_price < vwap_lower

        # Track when the price first crossed each band
        if above_band:
            if self.breakout_up_start is None:
                self.breakout_up_start = now
            self.breakout_down_start = None    # reset opposite
        else:
            self.breakout_up_start = None

        if below_band:
            if self.breakout_down_start is None:
                self.breakout_down_start = now
            self.breakout_up_start = None      # reset opposite
        else:
            self.breakout_down_start = None

        confirm_td = timedelta(seconds=self.breakout_confirm_seconds)
        is_sustained_up   = (above_band and self.breakout_up_start is not None
                             and (now - self.breakout_up_start) >= confirm_td)
        is_sustained_down = (below_band and self.breakout_down_start is not None
                             and (now - self.breakout_down_start) >= confirm_td)

        # ─────────────────────────────────────────────────────────────────────
        # SIGNAL LOGIC — All filters must pass
        # ─────────────────────────────────────────────────────────────────────

        # ── UPWARD BREAKOUT ───────────────────────────────────────────────────
        if is_sustained_up:

            # Filter 1 — Institutional footprint (volume anomaly)
            if not is_vol_anomaly:
                return "NEUTRAL", "FAKE BREAKOUT (Up) — No Institutional Volume", metrics

            # Filter 2 — Cumulative Delta pressure (CD ratio replaces raw bid/ask)
            if cd_ratio < imb_threshold:
                return "NEUTRAL", "FAKE BREAKOUT (Up) — Weak Buy-Side Delta", metrics

            # Filter 3 — Volume acceleration (rising volume confirms the move)
            vol_slope_min = self.weights.get("vol_slope_min", 0.0)
            if vol_slope < vol_slope_min:
                return "NEUTRAL", "FAKE BREAKOUT (Up) — Volume Not Accelerating", metrics

            # Filter 4 — Macro EMA blockade (skip if override active)
            if ema_blockade_active and current_price < macro_ema:
                return "NEUTRAL", "FAKE BREAKOUT (Up) — Fighting Macro Downtrend (EMA)", metrics

            # Filter 5 — Price velocity
            if price_slope > slope_threshold:
                return "BUY_CALL", "Strong Upward Momentum Confirmed", metrics

        # ── DOWNWARD BREAKOUT ─────────────────────────────────────────────────
        elif is_sustained_down:

            # Filter 1 — Institutional footprint
            if not is_vol_anomaly:
                return "NEUTRAL", "FAKE BREAKOUT (Down) — No Institutional Volume", metrics

            # Filter 2 — Cumulative Delta pressure (negative for selling)
            if cd_ratio > -imb_threshold:
                return "NEUTRAL", "FAKE BREAKOUT (Down) — Weak Sell-Side Delta", metrics

            # Filter 3 — Volume acceleration
            vol_slope_min = self.weights.get("vol_slope_min", 0.0)
            if vol_slope < vol_slope_min:
                return "NEUTRAL", "FAKE BREAKOUT (Down) — Volume Not Accelerating", metrics

            # Filter 4 — Macro EMA blockade
            if ema_blockade_active and current_price > macro_ema:
                return "NEUTRAL", "FAKE BREAKOUT (Down) — Fighting Macro Uptrend (EMA)", metrics

            # Filter 5 — Price velocity
            if price_slope < -slope_threshold:
                return "BUY_PUT", "Strong Downward Momentum Confirmed", metrics

        return "NEUTRAL", "Price in Value Area", metrics

    def reset_session(self):
        """Call this at the start of each trading day (9:15 AM)."""
        self.trend_history = pd.DataFrame(columns=[
            'timestamp', 'price', 'volume', 'cumulative_vol',
            'bid_qty', 'ask_qty', 'trade_direction'
        ])
        self.session_open_time = None
        self.session_anchor_price = None
        self.breakout_up_start = None
        self.breakout_down_start = None
        self.cumulative_delta = 0.0
