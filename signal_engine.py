"""
signal_engine.py — Momentum Engine v3 (Professional Grade)

NIFTY WEEKLY EXPIRY: Tuesday expiry cycle.

WHAT IS NEW vs v2:
  1. DTE-aware dynamic thresholds — every threshold scales by day of week
     relative to Tuesday expiry. Friday = DTE4 (relaxed), Monday = DTE1,
     Tuesday = DTE0 (ultra-strict). Thresholds calculated once per signal call,
     not hardcoded.

  2. Time-of-Day (ToD) session engine — six named sessions with individual
     OFI multipliers and score bonuses/penalties. The 13:00-13:30 dead zone
     is a hard block like spread toxicity. Late-day gamma premium window
     (14:00-15:15) lowers the firing threshold by 5 points.

  3. Time-in-Trade kill switch — open_trade() now stamps entry_time and
     DTE. manage_trade() enforces a time-based exit: if the trade has not
     reached 50% of Target 1 within the DTE-scaled patience window, the
     stop is moved to entry (breakeven kill). On DTE0 this is 3 minutes.

  4. DTE-based strike tier recommendation — get_recommended_strike_tier()
     returns "ATM" or "OTM-1" so the dashboard can highlight the
     correct strike. Wednesday/Thursday/Friday = OTM-1. Monday/Tuesday = ATM.

  5. Friday/Wednesday/Thursday calendar mapping corrected — Nifty weekly expiry
     is TUESDAY. DTE map: Tuesday=0, Monday=1, Sunday=2, Saturday=3,
     Friday=4, Thursday=5, Wednesday=6.

  6. Absolute threshold override bug fixed — Parameters stop_loss_mult,
     take_profit_mult, and trailing_stop_mult in _DTE_SCALE are applied as
     absolute levels instead of being multiplied by base values.
"""

import pandas as pd
import numpy as np
import json
import os
import logging
from datetime import datetime, time, date
from dataclasses import dataclass, field
from typing import Optional, List, Tuple, Dict

logger = logging.getLogger(__name__)

LOT_SIZE = 65  # Nifty lot size as of Jun-2026

# ---------------------------------------------------------------------------
# DTE CALCULATOR  (Tuesday expiry cycle)
# ---------------------------------------------------------------------------

def get_dte(reference_date: Optional[date] = None) -> int:
    """
    Returns Days To Expiry relative to next/current Tuesday.
    Tuesday   -> 0 (expiry day)
    Monday    -> 1 (one calendar/trading day before expiry)
    Sunday    -> 2 (weekend)
    Saturday  -> 3 (weekend)
    Friday    -> 4 (four calendar days before expiry)
    Thursday  -> 5 (five calendar days before expiry)
    Wednesday -> 6 (six calendar days before expiry, start of new cycle)
    """
    today = reference_date or date.today()
    weekday = today.weekday()  # Mon=0, Tue=1, Wed=2, Thu=3, Fri=4, Sat=5, Sun=6

    # Days until next Tuesday (weekday=1)
    days_to_tuesday = (1 - weekday) % 7
    return days_to_tuesday


def get_dte_label(dte: int) -> str:
    labels = {
        0: "EXPIRY (TUE)",
        1: "PRE-EXPIRY (MON)",
        2: "WEEKEND (SUN)",
        3: "WEEKEND (SAT)",
        4: "EARLY-WEEK (FRI)",
        5: "MID-WEEK (THU)",
        6: "NEW-CYCLE (WED)"
    }
    return labels.get(dte, "EARLY-WEEK")


# ---------------------------------------------------------------------------
# TIME OF DAY SESSIONS
# ---------------------------------------------------------------------------

@dataclass
class ToD_Session:
    name:            str
    start:           time
    end:             time
    ofi_multiplier:  float   # applied to ofi_sweep_contracts threshold
    score_modifier:  float   # added to composite score (can be negative)
    hard_block:      bool    # True = no trades allowed in this window
    description:     str


TOD_SESSIONS: List[ToD_Session] = [
    ToD_Session("OPENING_NOISE",  time(9,15),  time(9,44),  2.0,  -10.0, False,
                "IV crush, algo positioning, retail noise"),
    ToD_Session("PRIME_MORNING",  time(9,45),  time(11,29), 1.0,   +5.0, False,
                "Cleanest institutional flow window"),
    ToD_Session("MIDDAY_GRIND",   time(11,30), time(12,59), 1.4,  -8.0,  False,
                "Reduced volume, premium sellers dominate"),
    ToD_Session("DEAD_ZONE",      time(13,0),  time(13,29), 99.0, -99.0, True,
                "FII lunch hour — absolute chop, no trades"),
    ToD_Session("PRE_CLOSE_PREP", time(13,30), time(13,59), 1.2,  -3.0,  False,
                "Institutional positioning begins"),
    ToD_Session("GAMMA_WINDOW",   time(14,0),  time(15,15), 0.85, +8.0,  False,
                "Zero-to-Hero window, lower entry bar, gamma explosive"),
]

def get_tod_session(t: Optional[time] = None) -> ToD_Session:
    """Return the active ToD session for a given time."""
    now = t or datetime.now().time()
    for session in TOD_SESSIONS:
        if session.start <= now <= session.end:
            return session
    # Outside all sessions = after 15:15 or before 09:15
    return ToD_Session("CLOSED", time(15,16), time(23,59), 99.0, -99.0, True,
                       "Market closed")


# ---------------------------------------------------------------------------
# DTE-SCALED THRESHOLDS
# ---------------------------------------------------------------------------

# Base thresholds at DTE=4 (Friday, most relaxed)
_BASE_THRESHOLDS = {
    "ofi_sweep_contracts":     300,   # 300 = ~4-5 lots of 65
    "velocity_tps_min":        6,
    "score_threshold":         55.0,
    "stop_loss_mult":          0.88,  # 12% SL below entry (wider stop early week)
    "take_profit_mult":        1.35,  # 35% TP above entry
    "trailing_activation_pct": 0.08,
    "trailing_stop_mult":      0.92,  # 8% trailing stop
    "patience_minutes":        15,    # time-in-trade kill window
    "max_spread_pct":          0.006,
    "oi_lookback_candles":     5,
    "oi_rise_min_pct":         0.015,
    "volume_rise_min_pct":     0.08,
    "oi_persistence_required": 2,
    "price_extension_lookback":20,
    "price_extension_max_pct": 1.45,
    "seller_stress_strong":    50.0,
    "seller_stress_mild":      25.0,
    "gamma_wall_proximity_pts":60,
    "ofi_halflife_minutes":    3.0,
}

# Scaling multipliers per DTE (applied on top of base or absolute overrides)
# Format: { DTE: { param: multiplier_or_absolute_value } }
_DTE_SCALE: Dict[int, Dict[str, float]] = {
    0: {  # EXPIRY (Tuesday) — ultra strict, capture quick gamma moves
        "ofi_sweep_contracts":     2.8,   # 300 * 2.8 = 840 contracts
        "velocity_tps_min":        2.2,   # 6 * 2.2 = ~13
        "score_threshold":         1.2727,# 55 * 1.2727 = 70
        "stop_loss_mult":          0.95,  # Absolute: 5% SL (tighter stop, zero time)
        "take_profit_mult":        1.20,  # Absolute: 20% target (take money fast)
        "trailing_activation_pct": 0.50,  # Multiplier: 0.08 * 0.50 = 4% activation
        "trailing_stop_mult":      0.97,  # Absolute: 3% trailing stop (tight trail)
        "patience_minutes":        0.20,  # Multiplier: 15 * 0.2 = 3 minutes patience
        "max_spread_pct":          0.80,  # Multiplier: 0.006 * 0.80 = 0.0048 (tighter spread)
        "oi_rise_min_pct":         1.80,  # Multiplier: 0.015 * 1.80 = 0.027
        "gamma_wall_proximity_pts":0.67,  # Multiplier: 60 * 0.67 = 40pts
    },
    1: {  # PRE-EXPIRY (Monday) — strict
        "ofi_sweep_contracts":     2.0,   # 600
        "velocity_tps_min":        1.8,   # ~11
        "score_threshold":         1.1818,# 55 * 1.1818 = 65
        "stop_loss_mult":          0.93,  # Absolute: 7% SL
        "take_profit_mult":        1.25,  # Absolute: 25% target
        "trailing_activation_pct": 0.60,  # Multiplier: 4.8% activation
        "trailing_stop_mult":      0.96,  # Absolute: 4% trailing stop
        "patience_minutes":        0.40,  # Multiplier: 6 minutes
        "oi_rise_min_pct":         1.40,
        "gamma_wall_proximity_pts":0.83,
    },
    2: {  # Sunday (not traded, maps to Friday base values)
        "ofi_sweep_contracts":     1.0,
        "velocity_tps_min":        1.0,
        "score_threshold":         1.0,
        "patience_minutes":        1.0,
    },
    3: {  # Saturday (not traded, maps to Friday base values)
        "ofi_sweep_contracts":     1.0,
        "velocity_tps_min":        1.0,
        "score_threshold":         1.0,
        "patience_minutes":        1.0,
    },
    4: {  # Friday (Base values) — relaxed
        "ofi_sweep_contracts":     1.0,   # 300
        "velocity_tps_min":        1.0,   # 6
        "score_threshold":         1.0,   # 55
        "stop_loss_mult":          0.88,  # Absolute: 12% SL
        "take_profit_mult":        1.35,  # Absolute: 35% target
        "trailing_stop_mult":      0.92,  # Absolute: 8% trailing stop
        "patience_minutes":        1.0,   # Multiplier: 15 minutes
    },
    5: {  # Thursday — slightly stricter than Friday
        "ofi_sweep_contracts":     1.3,   # 300 * 1.3 = 390
        "velocity_tps_min":        1.3,   # ~8
        "score_threshold":         1.0545,# 55 * 1.0545 = 58
        "stop_loss_mult":          0.90,  # Absolute: 10% SL
        "take_profit_mult":        1.30,  # Absolute: 30% target
        "patience_minutes":        0.80,  # Multiplier: 12 minutes
    },
    6: {  # Wednesday (New weekly cycle start) — strict positioning
        "ofi_sweep_contracts":     1.6,   # 300 * 1.6 = 480
        "velocity_tps_min":        1.5,   # 9
        "score_threshold":         1.0909,# 55 * 1.0909 = 60
        "stop_loss_mult":          0.91,  # Absolute: 9% SL
        "take_profit_mult":        1.28,  # Absolute: 28% target
        "patience_minutes":        0.60,  # Multiplier: 9 minutes
        "oi_rise_min_pct":         1.20,
    }
}


def get_active_thresholds(dte: Optional[int] = None) -> dict:
    """
    Returns a fully computed threshold dict for the current DTE.
    All values are ready to use — no further multiplication needed.
    """
    if dte is None:
        dte = get_dte()
    dte = min(dte, 6)

    scale = _DTE_SCALE.get(dte, _DTE_SCALE[4])
    result = {}
    
    # These parameters in _DTE_SCALE are absolute numbers, NOT multipliers
    absolute_params = {"stop_loss_mult", "take_profit_mult", "trailing_stop_mult"}
    
    for k, base_val in _BASE_THRESHOLDS.items():
        if k in scale:
            val = scale[k]
            if k in absolute_params:
                result[k] = val
            else:
                result[k] = base_val * val
        else:
            result[k] = base_val

    # Round integer-natured params
    result["ofi_sweep_contracts"]     = round(result["ofi_sweep_contracts"])
    result["score_threshold"]         = round(result["score_threshold"], 1)
    result["velocity_tps_min"]        = round(result["velocity_tps_min"], 1)
    result["oi_lookback_candles"]      = int(_BASE_THRESHOLDS["oi_lookback_candles"])
    result["oi_persistence_required"]  = int(_BASE_THRESHOLDS["oi_persistence_required"])
    result["price_extension_lookback"] = int(_BASE_THRESHOLDS["price_extension_lookback"])

    return result


# ---------------------------------------------------------------------------
# SIGNAL WEIGHTS  (must sum to 1.0)
# ---------------------------------------------------------------------------

SIGNAL_WEIGHTS = {
    "oi_buildup":      0.18,
    "direction_ofi":   0.27,  # slightly heavier — OFI is king on retail feed
    "volume_rising":   0.10,
    "price_extension": 0.08,
    "seller_stress":   0.22,  # chain context is the institutional edge
    "gamma_alignment": 0.15,
}
assert abs(sum(SIGNAL_WEIGHTS.values()) - 1.0) < 1e-9, "SIGNAL_WEIGHTS must sum to 1.0"

VALID_REVERSAL_STATES = {"SIDEWAYS", "REVERSAL_LONG", "REVERSAL_SHORT"}


# ---------------------------------------------------------------------------
# SIGNAL RESULT
# ---------------------------------------------------------------------------

@dataclass
class SignalResult:
    """
    Full signal output. Truthy if fired.

    .fired        — bool
    .score        — float 0-100
    .scores       — dict: per-component (0-100 scale for display)
    .reason       — str: human-readable
    .blocked      — str | None: hard-block reason
    .dte          — int: DTE at signal time
    .tod_session  — str: session name at signal time
    .thresholds   — dict: active thresholds used (for debug/audit)
    """
    fired:       bool  = False
    score:       float = 0.0
    scores:      dict  = field(default_factory=dict)
    reason:      str   = ""
    blocked:     Optional[str] = None
    dte:         int   = -1
    tod_session: str   = ""
    thresholds:  dict  = field(default_factory=dict)

    def __bool__(self):
        return bool(self.fired)

    def __str__(self):
        if self.blocked:
            return f"BLOCKED({self.tod_session} DTE{self.dte}): {self.blocked}"
        status = "SIGNAL" if self.fired else "NO SIGNAL"
        bd = " | ".join(f"{k}={v:.1f}" for k, v in self.scores.items())
        return (f"{status} score={self.score:.1f} DTE={self.dte} "
                f"session={self.tod_session} [{bd}] | {self.reason}")


# ---------------------------------------------------------------------------
# INLINED DECAYED OFI  (no runtime import of chain_analyzer in hot path)
# ---------------------------------------------------------------------------

def _compute_decayed_ofi(
    ofi_history: List[Tuple[float, float]],
    halflife_minutes: float = 3.0,
) -> float:
    if not ofi_history:
        return 0.0
    decay_constant = np.log(2) / halflife_minutes
    weighted_sum = weight_total = 0.0
    for minutes_ago, ofi_value in ofi_history:
        w = np.exp(-decay_constant * minutes_ago)
        weighted_sum += ofi_value * w
        weight_total += w
    return float(weighted_sum / weight_total) if weight_total > 0 else 0.0


# ---------------------------------------------------------------------------
# PRIVATE SCORING HELPERS
# ---------------------------------------------------------------------------

def _spread_is_toxic(bid: float, ask: float, ltp: float, threshold: float) -> bool:
    if ltp > 0 and ask > bid:
        return (ask - bid) / ltp > threshold
    return False


def _score_oi_buildup(df: pd.DataFrame, thresholds: dict) -> float:
    lookback = thresholds["oi_lookback_candles"]
    if len(df) < lookback + 1:
        return 0.0
    recent       = df["OI"].iloc[-(lookback + 1):]
    rolling_mean = recent.iloc[:-1].mean()
    current_oi   = recent.iloc[-1]
    if rolling_mean <= 0:
        return 0.0
    pct_above = (current_oi - rolling_mean) / rolling_mean
    last_4    = df["OI"].iloc[-4:].values if len(df) >= 4 else df["OI"].values
    rises     = sum(1 for i in range(1, len(last_4)) if last_4[i] > last_4[i-1])
    if pct_above < thresholds["oi_rise_min_pct"]:
        return 0.0
    if rises < thresholds["oi_persistence_required"]:
        return 0.5
    return min(1.0, 0.5 + min(1.0, pct_above / 0.05) * 0.5)


def _score_volume_rising(df: pd.DataFrame, thresholds: dict) -> float:
    lookback = thresholds["oi_lookback_candles"]
    if len(df) < lookback + 1:
        return 0.0
    recent       = df["VOLUME"].iloc[-(lookback + 1):]
    rolling_mean = recent.iloc[:-1].mean()
    current_vol  = recent.iloc[-1]
    if rolling_mean <= 0:
        return 0.0
    pct_above = (current_vol - rolling_mean) / rolling_mean
    min_pct   = thresholds["volume_rise_min_pct"]
    if pct_above < min_pct:
        return 0.0
    return min(1.0, 0.5 + (pct_above - min_pct) / (min_pct * 4) * 0.5)


def _score_price_extension(df: pd.DataFrame, thresholds: dict) -> float:
    lookback = thresholds["price_extension_lookback"]
    if len(df) < lookback:
        return 0.5
    sma           = df["CLOSE"].rolling(window=lookback).mean().iloc[-1]
    current_close = df["CLOSE"].iloc[-1]
    if sma <= 0:
        return 0.5
    ratio         = current_close / sma
    max_ratio     = thresholds["price_extension_max_pct"]
    if ratio >= max_ratio:
        return 0.0
    penalty_start = max_ratio * 0.90
    if ratio >= penalty_start:
        return 0.5 * (max_ratio - ratio) / (max_ratio - penalty_start)
    return 1.0


def _score_direction_ofi(nifty_ofi: float, opt_type: str, thresholds: dict) -> float:
    raw = nifty_ofi if opt_type == "CE" else (-nifty_ofi if opt_type == "PE" else None)
    if raw is None or raw <= 0:
        return 0.0
    return min(1.0, raw / thresholds["ofi_sweep_contracts"])


def _score_seller_stress(chain_context, opt_type: str, thresholds: dict) -> float:
    """v2 bug-fixed version: wall proximity scored per-side, not summed."""
    if chain_context is None:
        return 0.0
    stress = chain_context.seller_stress_score
    if opt_type == "CE" and chain_context.pcr_bias == "BEARISH_SELLER":
        alignment_bonus = 1.2
    elif opt_type == "PE" and chain_context.pcr_bias == "BULLISH_SELLER":
        alignment_bonus = 1.2
    else:
        alignment_bonus = 1.0
    strong = thresholds["seller_stress_strong"]
    mild   = thresholds["seller_stress_mild"]
    if stress >= strong:
        raw_score = 1.0
    elif stress >= mild:
        raw_score = 0.5 + 0.5 * (stress - mild) / (strong - mild)
    else:
        raw_score = stress / mild * 0.5
    return min(1.0, raw_score * alignment_bonus)


def _score_gamma_alignment(chain_context, opt_type: str, ltp: float,
                            thresholds: dict) -> float:
    if chain_context is None:
        return 0.0
    spot = chain_context.spot_price
    prox = thresholds["gamma_wall_proximity_pts"]
    if opt_type == "CE":
        nearest_wall = chain_context.nearest_call_wall
        if nearest_wall is None:
            return 0.5
        dist = nearest_wall - spot
        if dist < 0:    return 1.0
        elif dist <= prox: return 0.2 + 0.4 * (dist / prox)
        else:           return 0.7
    elif opt_type == "PE":
        nearest_wall = chain_context.nearest_put_wall
        if nearest_wall is None:
            return 0.5
        dist = spot - nearest_wall
        if dist < 0:    return 1.0
        elif dist <= prox: return 0.2 + 0.4 * (dist / prox)
        else:           return 0.7
    return 0.5


def _get_candle_time(df: pd.DataFrame) -> time:
    current_time = df["DATETIME"].iloc[-1]
    if isinstance(current_time, str):
        current_time = pd.to_datetime(current_time)
    return current_time.time()


# ---------------------------------------------------------------------------
# STRIKE TIER RECOMMENDATION
# ---------------------------------------------------------------------------

def get_recommended_strike_tier(dte: int, spot: float, strike_interval: float = 50.0) -> dict:
    """
    Returns recommended strike offset from ATM based on DTE.

    DTE 0 (Expiry):    ATM — certainty over leverage
    DTE 1 (Monday):    ATM — balanced
    DTE 4, 5, 6:       OTM-1 preferred — time buffer allows delta leverage

    Returns dict with CE and PE recommended strikes.
    """
    atm = round(spot / strike_interval) * strike_interval
    if dte in [0, 1]:
        ce_rec = atm
        pe_rec = atm
        tier   = f"ATM ({'expiry' if dte == 0 else 'pre-expiry'} — certainty over leverage)"
    elif dte in [4, 5, 6]:
        ce_rec = atm + strike_interval      # OTM1
        pe_rec = atm - strike_interval
        tier   = "OTM-1 (early/mid-week — time buffer for leverage)"
    else:
        ce_rec = atm
        pe_rec = atm
        tier   = "ATM (defensive)"

    return {
        "dte":         dte,
        "tier_label":  tier,
        "atm":         atm,
        "ce_strike":   ce_rec,
        "pe_strike":   pe_rec,
        "interval":    strike_interval,
    }


# ---------------------------------------------------------------------------
# PUBLIC API — MAIN SIGNAL CHECK
# ---------------------------------------------------------------------------

def check_ai_buy_signal(
    df: pd.DataFrame,
    nifty_ofi: float,
    opt_type: str,
    reversal_state: str = "SIDEWAYS",
    bid: float = 0.0,
    ask: float = 0.0,
    ltp: float = 0.0,
    chain_context=None,
    ofi_history: Optional[List[Tuple[float, float]]] = None,
    dte: Optional[int] = None,
    current_time: Optional[time] = None,
) -> SignalResult:
    """
    Evaluate a 1-min candle DataFrame for a high-conviction options BUY signal.

    New parameters vs v2:
      dte          : int  — days to expiry (auto-computed if None)
      current_time : time — for ToD session lookup (auto-computed if None)
    """
    if reversal_state not in VALID_REVERSAL_STATES:
        raise ValueError(f"Invalid reversal_state '{reversal_state}'")

    # Resolve DTE and session
    dte     = get_dte() if dte is None else dte
    now_t   = current_time or datetime.now().time()
    session = get_tod_session(now_t)
    thresholds = get_active_thresholds(dte)

    # ── HARD BLOCKS ──────────────────────────────────────────────────────────
    if session.hard_block:
        return SignalResult(blocked=f"SESSION_BLOCK:{session.name}",
                            dte=dte, tod_session=session.name,
                            thresholds=thresholds)

    if _spread_is_toxic(bid, ask, ltp, thresholds["max_spread_pct"]):
        return SignalResult(blocked="SPREAD_TOXIC", dte=dte,
                            tod_session=session.name, thresholds=thresholds)

    if opt_type == "PE" and reversal_state == "REVERSAL_LONG":
        return SignalResult(blocked="REVERSAL_TRAP_PE_IN_LONG", dte=dte,
                            tod_session=session.name, thresholds=thresholds)
    if opt_type == "CE" and reversal_state == "REVERSAL_SHORT":
        return SignalResult(blocked="REVERSAL_TRAP_CE_IN_SHORT", dte=dte,
                            tod_session=session.name, thresholds=thresholds)

    if len(df) < 5:
        return SignalResult(blocked="INSUFFICIENT_DATA", dte=dte,
                            tod_session=session.name, thresholds=thresholds)

    df = df.copy()
    candle_t = _get_candle_time(df)
    if candle_t < time(9, 15) or candle_t > time(15, 15):
        return SignalResult(blocked=f"TIME_FILTER({candle_t})", dte=dte,
                            tod_session=session.name, thresholds=thresholds)

    # ── DECAYED OFI ───────────────────────────────────────────────────────────
    effective_ofi = (
        _compute_decayed_ofi(ofi_history, thresholds["ofi_halflife_minutes"])
        if ofi_history else nifty_ofi
    )

    # ── COMPONENT SCORES ─────────────────────────────────────────────────────
    s_oi     = _score_oi_buildup(df, thresholds)
    s_ofi    = _score_direction_ofi(effective_ofi, opt_type, thresholds)
    s_vol    = _score_volume_rising(df, thresholds)
    s_price  = _score_price_extension(df, thresholds)
    s_stress = _score_seller_stress(chain_context, opt_type, thresholds)
    s_gamma  = _score_gamma_alignment(chain_context, opt_type, ltp, thresholds)

    components = {
        "oi_buildup":      s_oi,
        "direction_ofi":   s_ofi,
        "volume_rising":   s_vol,
        "price_extension": s_price,
        "seller_stress":   s_stress,
        "gamma_alignment": s_gamma,
    }

    w = SIGNAL_WEIGHTS
    composite = (
        s_oi     * w["oi_buildup"]      +
        s_ofi    * w["direction_ofi"]   +
        s_vol    * w["volume_rising"]   +
        s_price  * w["price_extension"] +
        s_stress * w["seller_stress"]   +
        s_gamma  * w["gamma_alignment"]
    ) * 100

    # ── ToD SESSION MODIFIER ──────────────────────────────────────────────────
    composite += session.score_modifier

    display_scores = {k: round(v * 100, 1) for k, v in components.items()}

    # ── DYNAMIC SCORE THRESHOLD ───────────────────────────────────────────────
    score_threshold = thresholds["score_threshold"]
    # Gamma window gets a -5pt threshold bonus (lower bar = easier to fire)
    if session.name == "GAMMA_WINDOW":
        score_threshold -= 5.0

    composite = max(0.0, min(100.0, composite))
    fired     = composite >= score_threshold

    top_contributors = sorted(
        ((k, v * SIGNAL_WEIGHTS[k]) for k, v in components.items()),
        key=lambda x: x[1], reverse=True
    )
    top_str = ", ".join(f"{k}={v*100:.0f}%" for k, v in top_contributors[:3])
    reason  = (
        f"{'FIRE' if fired else 'HOLD'} | "
        f"threshold={score_threshold:.0f} | "
        f"DTE={dte} {get_dte_label(dte)} | "
        f"session={session.name} | "
        f"top=[{top_str}] | "
        f"chain={'YES' if chain_context else 'NO'}"
    )

    return SignalResult(
        fired=fired,
        score=round(composite, 2),
        scores=display_scores,
        reason=reason,
        dte=dte,
        tod_session=session.name,
        thresholds=thresholds,
    )


def check_velocity_sweep_signal(
    df,
    nifty_ofi: float,
    velocity_tps: float,
    opt_type: str,
    reversal_state: str = "SIDEWAYS",
    bid: float = 0.0,
    ask: float = 0.0,
    ltp: float = 0.0,
    chain_context=None,
    dte: Optional[int] = None,
    current_time: Optional[time] = None,
) -> SignalResult:
    """Sub-second tape sweep with DTE and ToD awareness."""
    if reversal_state not in VALID_REVERSAL_STATES:
        raise ValueError(f"Invalid reversal_state '{reversal_state}'")

    dte        = get_dte() if dte is None else dte
    now_t      = current_time or datetime.now().time()
    session    = get_tod_session(now_t)
    thresholds = get_active_thresholds(dte)

    if session.hard_block:
        return SignalResult(blocked=f"SESSION_BLOCK:{session.name}",
                            dte=dte, tod_session=session.name)

    if _spread_is_toxic(bid, ask, ltp, thresholds["max_spread_pct"]):
        return SignalResult(blocked="SPREAD_TOXIC", dte=dte,
                            tod_session=session.name)

    if opt_type == "PE" and reversal_state == "REVERSAL_LONG":
        return SignalResult(blocked="REVERSAL_TRAP_PE_IN_LONG", dte=dte,
                            tod_session=session.name)
    if opt_type == "CE" and reversal_state == "REVERSAL_SHORT":
        return SignalResult(blocked="REVERSAL_TRAP_CE_IN_SHORT", dte=dte,
                            tod_session=session.name)

    if df is not None and len(df) > 0:
        candle_t = _get_candle_time(df)
        if candle_t < time(9, 15) or candle_t > time(15, 15):
            return SignalResult(blocked=f"TIME_FILTER({candle_t})", dte=dte,
                                tod_session=session.name)

    # Apply ToD OFI multiplier to threshold
    effective_ofi_threshold = (
        thresholds["ofi_sweep_contracts"] * session.ofi_multiplier
    )
    effective_vel_min = thresholds["velocity_tps_min"]

    if velocity_tps < effective_vel_min:
        return SignalResult(
            fired=False, score=0.0, dte=dte, tod_session=session.name,
            reason=f"vel {velocity_tps:.1f} < min {effective_vel_min:.1f} (DTE{dte})"
        )

    ofi_ok = (
        (opt_type == "CE" and nifty_ofi >  effective_ofi_threshold) or
        (opt_type == "PE" and nifty_ofi < -effective_ofi_threshold)
    )
    if not ofi_ok:
        return SignalResult(
            fired=False, score=0.0, dte=dte, tod_session=session.name,
            reason=(f"OFI {nifty_ofi:.0f} < threshold "
                    f"{effective_ofi_threshold:.0f} (DTE{dte} {session.name})")
        )

    velocity_score = min(1.0, velocity_tps / (effective_vel_min * 2))
    ofi_score      = min(1.0, abs(nifty_ofi) / (effective_ofi_threshold * 2))
    base           = (velocity_score * 0.4 + ofi_score * 0.6) * 100
    base          += session.score_modifier  # ToD modifier

    gamma_score = _score_gamma_alignment(chain_context, opt_type, ltp, thresholds)
    if gamma_score >= 0.9:
        gamma_modifier = 1.25; gamma_note = "WALL_BROKEN"
    elif gamma_score <= 0.45:
        gamma_modifier = 0.75; gamma_note = "WALL_DEFENDED"
    else:
        gamma_modifier = 1.0;  gamma_note = "WALL_CLEAR"

    score_threshold = thresholds["score_threshold"]
    if session.name == "GAMMA_WINDOW":
        score_threshold -= 5.0

    final_score = min(100.0, max(0.0, base * gamma_modifier))
    fired       = final_score >= score_threshold

    return SignalResult(
        fired=fired,
        score=round(final_score, 2),
        scores={
            "velocity": round(velocity_score * 100, 1),
            "ofi":      round(ofi_score * 100, 1),
            "gamma":    round(gamma_score * 100, 1),
        },
        reason=(
            f"sweep vel={velocity_tps:.1f}tps "
            f"ofi={nifty_ofi:.0f} threshold={effective_ofi_threshold:.0f} "
            f"gamma={gamma_note} mod={gamma_modifier:.2f} "
            f"DTE={dte} {session.name}"
        ),
        dte=dte,
        tod_session=session.name,
        thresholds=thresholds,
    )


# ---------------------------------------------------------------------------
# TRADE LIFECYCLE — with time-in-trade kill switch
# ---------------------------------------------------------------------------

def open_trade(entry_price: float, opt_type: str = "CE",
               dte: Optional[int] = None) -> dict:
    """
    Construct a new trade dict with DTE-scaled exits and entry timestamp.
    Always use this — never build trade dicts manually.
    """
    if dte is None:
        dte = get_dte()
    thresholds = get_active_thresholds(dte)

    target = entry_price * thresholds["take_profit_mult"]
    stop   = entry_price * thresholds["stop_loss_mult"]

    return {
        "entry":              entry_price,
        "target":             round(target, 2),
        "stop":               round(stop,   2),
        "high_watermark":     entry_price,
        "entry_time":         datetime.now(),
        "dte_at_entry":       dte,
        "opt_type":           opt_type,
        "patience_minutes":   thresholds["patience_minutes"],
        "trailing_activation":thresholds["trailing_activation_pct"],
        "trailing_mult":      thresholds["trailing_stop_mult"],
        "halfmove_hit":       False,   # True once 50% of T1 range achieved
    }


def manage_trade(trade: dict, current_ltp: float) -> Tuple[str, dict]:
    """
    Trail stop off high watermark with time-in-trade kill switch.

    Returns: (status_str, updated_trade_dict)
    status_str: "ACTIVE" | "TARGET HIT" | "STOPPED OUT" | "TIME_KILL"

    TIME_KILL fires when:
      - patience_minutes have elapsed AND
      - price has not reached 50% of the entry→target range
    On TIME_KILL the stop is moved to entry (breakeven). This prevents
    holding a theta-bleeding position waiting for a miracle.
    """
    if "high_watermark" not in trade:
        trade["high_watermark"] = max(trade["entry"], current_ltp)
    if "entry_time" not in trade:
        trade["entry_time"] = datetime.now()
    if "halfmove_hit" not in trade:
        trade["halfmove_hit"] = False

    if current_ltp > trade["high_watermark"]:
        trade["high_watermark"] = current_ltp

    # Target / stop check
    if current_ltp >= trade["target"]:
        return "TARGET HIT", trade
    if current_ltp <= trade["stop"]:
        if trade.get("time_kill_active", False) and trade["stop"] == trade["entry"]:
            return "TIME_KILL", trade
        return "STOPPED OUT", trade

    # ── TIME-IN-TRADE KILL SWITCH ─────────────────────────────────────────
    elapsed_minutes = (datetime.now() - trade["entry_time"]).total_seconds() / 60.0
    halfmove_level  = trade["entry"] + (trade["target"] - trade["entry"]) * 0.50

    if current_ltp >= halfmove_level:
        trade["halfmove_hit"] = True

    patience = trade.get("patience_minutes", 10.0)
    if elapsed_minutes >= patience and not trade["halfmove_hit"]:
        trade["time_kill_active"] = True
        # Move stop to entry — breakeven kill
        if trade["stop"] < trade["entry"]:
            trade["stop"] = trade["entry"]
            logger.info(
                "TIME_KILL: %.1f min elapsed, no halfmove — stop moved to entry %.2f",
                elapsed_minutes, trade["entry"]
            )
        # If we're now at or below the new breakeven stop, exit
        if current_ltp <= trade["stop"]:
            return "TIME_KILL", trade

    # ── TRAILING STOP ────────────────────────────────────────────────────────
    profit_pct = (trade["high_watermark"] - trade["entry"]) / trade["entry"]
    if profit_pct > trade.get("trailing_activation", 0.08):
        new_stop = trade["high_watermark"] * trade.get("trailing_mult", 0.92)
        if new_stop > trade["stop"]:
            trade["stop"] = round(new_stop, 2)

    return "ACTIVE", trade


def get_exit_levels(entry_price: float, dte: Optional[int] = None) -> Tuple[float, float]:
    """Convenience function returning (target, stop) for a given entry."""
    if dte is None:
        dte = get_dte()
    thresholds = get_active_thresholds(dte)
    return (
        round(entry_price * thresholds["take_profit_mult"], 2),
        round(entry_price * thresholds["stop_loss_mult"],   2),
    )


# ---------------------------------------------------------------------------
# DIAGNOSTIC HELPER  (call this at startup to log active config)
# ---------------------------------------------------------------------------

def log_active_config() -> dict:
    dte        = get_dte()
    thresholds = get_active_thresholds(dte)
    session    = get_tod_session()
    config = {
        "dte":               dte,
        "dte_label":         get_dte_label(dte),
        "tod_session":       session.name,
        "session_hardblock": session.hard_block,
        "ofi_threshold":     thresholds["ofi_sweep_contracts"],
        "velocity_min":      thresholds["velocity_tps_min"],
        "score_threshold":   thresholds["score_threshold"],
        "patience_minutes":  thresholds["patience_minutes"],
        "stop_loss_mult":    thresholds["stop_loss_mult"],
        "take_profit_mult":  thresholds["take_profit_mult"],
    }
    logger.info("SIGNAL ENGINE CONFIG: %s", config)
    print("=" * 60)
    print(f"  SIGNAL ENGINE v3 — DTE={dte} ({get_dte_label(dte)})")
    print(f"  Session : {session.name} — {session.description}")
    print(f"  OFI Thr : {thresholds['ofi_sweep_contracts']} contracts")
    print(f"  Vel Min : {thresholds['velocity_tps_min']:.1f} tps")
    print(f"  Score   : {thresholds['score_threshold']:.0f}/100 to fire")
    print(f"  Patience: {thresholds['patience_minutes']:.0f} min time-kill")
    print(f"  SL/TP   : {thresholds['stop_loss_mult']:.0%} / {thresholds['take_profit_mult']:.0%}")
    print("=" * 60)
    return config


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    log_active_config()
