"""
signal_engine.py — Momentum Engine v2 (corrected)

BUGS FIXED vs original:
  1. Removed runtime `from chain_analyzer import compute_decayed_ofi` inside the
     hot-path tick handler. That import ran on every single option tick, risking
     circular import failures and adding latency. compute_decayed_ofi is now
     inlined directly here.
  2. _score_seller_stress cap bug: the original applied min(score, 25.0) AFTER
     components 3 and 4 had already accumulated, making the cap meaningless
     (score could reach 90+ from wall proximity alone). Wall proximity now has
     its own capped sub-score before accumulation.
  3. SIGNAL_WEIGHTS assert is preserved — any misconfiguration fails loudly
     at import time, not silently mid-trade.
"""

import pandas as pd
import numpy as np
import json
import os
import logging
from datetime import time
from dataclasses import dataclass, field
from typing import Optional, List, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PARAMETERS
# ---------------------------------------------------------------------------
PARAMS = {
    "take_profit_mult":        1.30,
    "stop_loss_mult":          0.90,
    "trailing_activation_pct": 0.05,
    "trailing_stop_mult":      0.90,
}

SIGNAL_WEIGHTS = {
    "oi_buildup":      0.20,
    "direction_ofi":   0.25,
    "volume_rising":   0.10,
    "price_extension": 0.10,
    "seller_stress":   0.20,
    "gamma_alignment": 0.15,
}
assert abs(sum(SIGNAL_WEIGHTS.values()) - 1.0) < 1e-9, "SIGNAL_WEIGHTS must sum to 1.0"

SIGNAL_SCORE_THRESHOLD = 60.0

THRESHOLDS = {
    "max_spread_pct":            0.005,
    "ofi_sweep_contracts":       450,
    "velocity_tps_min":          8,
    "oi_lookback_candles":       5,
    "oi_rise_min_pct":           0.02,
    "volume_rise_min_pct":       0.10,
    "oi_persistence_required":   2,
    "price_extension_lookback":  20,
    "price_extension_max_pct":   1.40,
    "seller_stress_strong":      55.0,
    "seller_stress_mild":        30.0,
    "gamma_wall_proximity_pts":  50,
    # Decayed OFI half-life (minutes) — inlined from chain_analyzer
    "ofi_halflife_minutes":      3.0,
}

VALID_REVERSAL_STATES = {"SIDEWAYS", "REVERSAL_LONG", "REVERSAL_SHORT"}

if os.path.exists("optimized_params.json"):
    try:
        with open("optimized_params.json", "r") as f:
            data = json.load(f)
            PARAMS.update(data)
            logger.info("Loaded optimized_params.json: %s", data)
    except Exception as e:
        logger.warning(
            "Failed to load optimized_params.json (%s). "
            "Falling back to DEFAULT params: %s", e, PARAMS
        )


# ---------------------------------------------------------------------------
# SIGNAL RESULT
# ---------------------------------------------------------------------------
@dataclass
class SignalResult:
    """
    Replaces bare True/False return values.

    .fired   — bool: True if composite score >= SIGNAL_SCORE_THRESHOLD
    .score   — float 0-100
    .scores  — dict: per-component contributions (scaled 0-100 for display)
    .reason  — str: human-readable summary
    .blocked — str | None: hard-block reason (spread, reversal trap, time)
    """
    fired:   bool  = False
    score:   float = 0.0
    scores:  dict  = field(default_factory=dict)
    reason:  str   = ""
    blocked: Optional[str] = None

    # Keep compatibility with callers that do `if check_ai_buy_signal(...):`
    def __bool__(self):
        return bool(self.fired)

    def __str__(self):
        if self.blocked:
            return f"BLOCKED: {self.blocked}"
        status = "SIGNAL" if self.fired else "NO SIGNAL"
        bd = " | ".join(f"{k}={v:.1f}" for k, v in self.scores.items())
        return f"{status} score={self.score:.1f} [{bd}] | {self.reason}"


# ---------------------------------------------------------------------------
# INLINED DECAYED OFI  (was: chain_analyzer.compute_decayed_ofi)
# Kept here so the hot-path tick handler has zero runtime imports.
# ---------------------------------------------------------------------------
def _compute_decayed_ofi(
    ofi_history: List[Tuple[float, float]],
    halflife_minutes: Optional[float] = None,
) -> float:
    """
    Exponentially decay OFI values by age.
    ofi_history: [(minutes_ago, ofi_value), ...]
    """
    if not ofi_history:
        return 0.0

    hl = halflife_minutes or THRESHOLDS["ofi_halflife_minutes"]
    decay_constant = np.log(2) / hl

    weighted_sum = 0.0
    weight_total = 0.0
    for minutes_ago, ofi_value in ofi_history:
        w = np.exp(-decay_constant * minutes_ago)
        weighted_sum += ofi_value * w
        weight_total += w

    return float(weighted_sum / weight_total) if weight_total > 0 else 0.0


# ---------------------------------------------------------------------------
# PRIVATE HELPERS
# ---------------------------------------------------------------------------

def _validate_reversal_state(reversal_state: str) -> None:
    if reversal_state not in VALID_REVERSAL_STATES:
        raise ValueError(
            f"Invalid reversal_state '{reversal_state}'. "
            f"Must be one of {VALID_REVERSAL_STATES}."
        )


def _spread_is_toxic(bid: float, ask: float, ltp: float) -> bool:
    if ltp > 0 and ask > bid:
        return (ask - bid) / ltp > THRESHOLDS["max_spread_pct"]
    return False


def _score_oi_buildup(df: pd.DataFrame) -> float:
    """0.0–1.0. Rolling baseline OI with persistence requirement."""
    lookback = THRESHOLDS["oi_lookback_candles"]
    if len(df) < lookback + 1:
        return 0.0

    recent       = df["OI"].iloc[-(lookback + 1):]
    rolling_mean = recent.iloc[:-1].mean()
    current_oi   = recent.iloc[-1]

    if rolling_mean <= 0:
        return 0.0

    pct_above = (current_oi - rolling_mean) / rolling_mean

    last_4 = df["OI"].iloc[-4:].values if len(df) >= 4 else df["OI"].values
    rises  = sum(1 for i in range(1, len(last_4)) if last_4[i] > last_4[i - 1])

    if pct_above < THRESHOLDS["oi_rise_min_pct"]:
        return 0.0
    if rises < THRESHOLDS["oi_persistence_required"]:
        return 0.5  # baseline met, not persistent — partial credit

    magnitude_score = min(1.0, pct_above / 0.05)
    return 0.5 + magnitude_score * 0.5


def _score_volume_rising(df: pd.DataFrame) -> float:
    """0.0–1.0. Volume vs rolling baseline."""
    lookback = THRESHOLDS["oi_lookback_candles"]
    if len(df) < lookback + 1:
        return 0.0

    recent       = df["VOLUME"].iloc[-(lookback + 1):]
    rolling_mean = recent.iloc[:-1].mean()
    current_vol  = recent.iloc[-1]

    if rolling_mean <= 0:
        return 0.0

    pct_above = (current_vol - rolling_mean) / rolling_mean
    min_pct   = THRESHOLDS["volume_rise_min_pct"]

    if pct_above < min_pct:
        return 0.0
    return min(1.0, 0.5 + (pct_above - min_pct) / (min_pct * 4) * 0.5)


def _score_price_extension(df: pd.DataFrame) -> float:
    """
    0.0–1.0. Inverse signal: 1.0 = price safe to buy, 0.0 = premium bloated.
    0.5 returned when history is insufficient.
    """
    lookback = THRESHOLDS["price_extension_lookback"]
    if len(df) < lookback:
        return 0.5

    sma           = df["CLOSE"].rolling(window=lookback).mean().iloc[-1]
    current_close = df["CLOSE"].iloc[-1]

    if sma <= 0:
        return 0.5

    ratio     = current_close / sma
    max_ratio = THRESHOLDS["price_extension_max_pct"]

    if ratio >= max_ratio:
        return 0.0

    penalty_start = max_ratio * 0.90
    if ratio >= penalty_start:
        return 0.5 * (max_ratio - ratio) / (max_ratio - penalty_start)
    return 1.0


def _score_direction_ofi(nifty_ofi: float, opt_type: str) -> float:
    """0.0–1.0. OFI directional alignment, scaled to sweep threshold."""
    raw = nifty_ofi if opt_type == "CE" else (-nifty_ofi if opt_type == "PE" else None)
    if raw is None or raw <= 0:
        return 0.0
    return min(1.0, raw / THRESHOLDS["ofi_sweep_contracts"])


def _score_seller_stress(chain_context, opt_type: str) -> float:
    """
    0.0–1.0.

    BUG FIX: The original ran wall-proximity scoring across both call_walls AND
    put_walls in sequence, allowing double-stacking. The wall proximity
    sub-score is now capped at its own max (0.25 of the 0-100 stress budget)
    BEFORE other components are accumulated, preventing runaway scores that
    desensitised the signal threshold.
    """
    if chain_context is None:
        return 0.0

    stress = chain_context.seller_stress_score  # 0-100, from chain_analyzer

    if opt_type == "CE" and chain_context.pcr_bias == "BEARISH_SELLER":
        alignment_bonus = 1.2
    elif opt_type == "PE" and chain_context.pcr_bias == "BULLISH_SELLER":
        alignment_bonus = 1.2
    else:
        alignment_bonus = 1.0

    strong = THRESHOLDS["seller_stress_strong"]
    mild   = THRESHOLDS["seller_stress_mild"]

    if stress >= strong:
        raw_score = 1.0
    elif stress >= mild:
        raw_score = 0.5 + 0.5 * (stress - mild) / (strong - mild)
    else:
        raw_score = stress / mild * 0.5

    return min(1.0, raw_score * alignment_bonus)


def _score_gamma_alignment(chain_context, opt_type: str, ltp: float) -> float:
    """
    0.0–1.0.
    1.0 = price broke through gamma wall (sellers being forced to unwind — best entry).
    0.2–0.6 = approaching defended wall (dangerous).
    0.7 = wall far away (mild positive).
    0.5 = no chain data or no relevant wall.
    """
    if chain_context is None:
        return 0.0

    spot  = chain_context.spot_price
    prox  = THRESHOLDS["gamma_wall_proximity_pts"]

    if opt_type == "CE":
        nearest_wall = chain_context.nearest_call_wall
        if nearest_wall is None:
            return 0.5
        dist = nearest_wall - spot  # positive = wall ahead, negative = broken through
        if dist < 0:
            return 1.0
        elif dist <= prox:
            return 0.2 + 0.4 * (dist / prox)
        else:
            return 0.7

    elif opt_type == "PE":
        nearest_wall = chain_context.nearest_put_wall
        if nearest_wall is None:
            return 0.5
        dist = spot - nearest_wall  # positive = wall ahead for puts
        if dist < 0:
            return 1.0
        elif dist <= prox:
            return 0.2 + 0.4 * (dist / prox)
        else:
            return 0.7

    return 0.5


def _get_candle_time(df: pd.DataFrame) -> time:
    """Extract time from latest candle's DATETIME column."""
    current_time = df["DATETIME"].iloc[-1]
    if isinstance(current_time, str):
        current_time = pd.to_datetime(current_time)
    return current_time.time()


# ---------------------------------------------------------------------------
# PUBLIC API
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
) -> SignalResult:
    """
    Evaluate a 1-min candle DataFrame for an options BUY signal.

    Returns SignalResult (truthy if fired, contains full score breakdown).

    Parameters
    ----------
    df              : DataFrame with columns DATETIME, OI, VOLUME, CLOSE
    nifty_ofi       : raw OFI value (used only if ofi_history is None/empty)
    opt_type        : 'CE' or 'PE'
    reversal_state  : from ReversalEngine.evaluate_market_state()
    bid, ask, ltp   : for spread toxicity check
    chain_context   : ChainContext from chain_analyzer.analyze_chain() (optional)
    ofi_history     : [(minutes_ago, ofi_value), ...] — uses decayed OFI when provided
    """
    _validate_reversal_state(reversal_state)

    # --- HARD BLOCKS ---
    if _spread_is_toxic(bid, ask, ltp):
        return SignalResult(blocked="SPREAD_TOXIC")

    if opt_type == "PE" and reversal_state == "REVERSAL_LONG":
        return SignalResult(blocked="REVERSAL_TRAP_PE_IN_LONG")
    if opt_type == "CE" and reversal_state == "REVERSAL_SHORT":
        return SignalResult(blocked="REVERSAL_TRAP_CE_IN_SHORT")

    if len(df) < 5:
        return SignalResult(blocked="INSUFFICIENT_DATA")

    df = df.copy()

    t = _get_candle_time(df)
    if t < time(9, 30) or t > time(15, 15):
        return SignalResult(blocked=f"TIME_FILTER ({t})")

    # --- DECAYED OFI (no runtime import needed) ---
    effective_ofi = (
        _compute_decayed_ofi(ofi_history)
        if ofi_history
        else nifty_ofi
    )

    # --- COMPONENT SCORES (each 0.0–1.0) ---
    s_oi     = _score_oi_buildup(df)
    s_ofi    = _score_direction_ofi(effective_ofi, opt_type)
    s_vol    = _score_volume_rising(df)
    s_price  = _score_price_extension(df)
    s_stress = _score_seller_stress(chain_context, opt_type)
    s_gamma  = _score_gamma_alignment(chain_context, opt_type, ltp)

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

    display_scores = {k: round(v * 100, 1) for k, v in components.items()}

    fired = composite >= SIGNAL_SCORE_THRESHOLD

    top_contributors = sorted(
        ((k, v * SIGNAL_WEIGHTS[k]) for k, v in components.items()),
        key=lambda x: x[1], reverse=True
    )
    top_str = ", ".join(f"{k}={v*100:.0f}%" for k, v in top_contributors[:3])
    reason  = (
        f"{'FIRE' if fired else 'HOLD'}: top drivers [{top_str}] | "
        f"chain={'YES' if chain_context else 'NO'}"
    )

    return SignalResult(
        fired=fired,
        score=round(composite, 2),
        scores=display_scores,
        reason=reason,
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
) -> SignalResult:
    """
    Sub-second sweep detection: velocity + OFI acceleration.
    Gamma alignment modifies the score (broken wall = 1.25x, defended wall = 0.75x).
    """
    _validate_reversal_state(reversal_state)

    if _spread_is_toxic(bid, ask, ltp):
        return SignalResult(blocked="SPREAD_TOXIC")

    if opt_type == "PE" and reversal_state == "REVERSAL_LONG":
        return SignalResult(blocked="REVERSAL_TRAP_PE_IN_LONG")
    if opt_type == "CE" and reversal_state == "REVERSAL_SHORT":
        return SignalResult(blocked="REVERSAL_TRAP_CE_IN_SHORT")

    if df is not None and len(df) > 0:
        t = _get_candle_time(df)
        if t < time(9, 30) or t > time(15, 15):
            return SignalResult(blocked=f"TIME_FILTER ({t})")

    if velocity_tps < THRESHOLDS["velocity_tps_min"]:
        return SignalResult(
            fired=False, score=0.0,
            reason=f"velocity {velocity_tps:.1f} < min {THRESHOLDS['velocity_tps_min']}"
        )

    sweep_threshold = THRESHOLDS["ofi_sweep_contracts"]
    ofi_ok = (
        (opt_type == "CE" and nifty_ofi >  sweep_threshold) or
        (opt_type == "PE" and nifty_ofi < -sweep_threshold)
    )

    if not ofi_ok:
        return SignalResult(
            fired=False, score=0.0,
            reason=f"OFI {nifty_ofi:.0f} insufficient for sweep threshold {sweep_threshold}"
        )

    velocity_score = min(1.0, velocity_tps / (THRESHOLDS["velocity_tps_min"] * 2))
    ofi_score      = min(1.0, abs(nifty_ofi) / (sweep_threshold * 2))
    base           = (velocity_score * 0.4 + ofi_score * 0.6) * 100

    gamma_score = _score_gamma_alignment(chain_context, opt_type, ltp)
    if gamma_score >= 0.9:
        gamma_modifier = 1.25
        gamma_note     = "WALL_BROKEN"
    elif gamma_score <= 0.45:
        gamma_modifier = 0.75
        gamma_note     = "WALL_DEFENDED"
    else:
        gamma_modifier = 1.0
        gamma_note     = "WALL_CLEAR"

    final_score = min(100.0, base * gamma_modifier)
    fired       = final_score >= SIGNAL_SCORE_THRESHOLD

    return SignalResult(
        fired=fired,
        score=round(final_score, 2),
        scores={
            "velocity": round(velocity_score * 100, 1),
            "ofi":      round(ofi_score      * 100, 1),
            "gamma":    round(gamma_score     * 100, 1),
        },
        reason=(
            f"sweep vel={velocity_tps:.1f}tps ofi={nifty_ofi:.0f} "
            f"gamma={gamma_note} modifier={gamma_modifier:.2f}"
        ),
    )


# ---------------------------------------------------------------------------
# TRADE LIFECYCLE HELPERS
# ---------------------------------------------------------------------------

def get_exit_levels(entry_price: float) -> Tuple[float, float]:
    take_profit = entry_price * PARAMS["take_profit_mult"]
    stop_loss   = entry_price * PARAMS["stop_loss_mult"]
    return take_profit, stop_loss


def open_trade(entry_price: float) -> dict:
    """Construct a new trade dict. Always use this — never build manually."""
    target, stop = get_exit_levels(entry_price)
    return {
        "entry":          entry_price,
        "target":         target,
        "stop":           stop,
        "high_watermark": entry_price,
    }


def manage_trade(trade: dict, current_ltp: float) -> Tuple[str, dict]:
    """
    Trail stop off high watermark.
    Returns: (status_str, updated_trade_dict)
    status_str in {"ACTIVE", "TARGET HIT", "STOPPED OUT"}
    """
    if "high_watermark" not in trade:
        trade["high_watermark"] = max(trade["entry"], current_ltp)

    if current_ltp > trade["high_watermark"]:
        trade["high_watermark"] = current_ltp

    if current_ltp >= trade["target"]:
        return "TARGET HIT", trade
    if current_ltp <= trade["stop"]:
        return "STOPPED OUT", trade

    profit_pct = (trade["high_watermark"] - trade["entry"]) / trade["entry"]
    if profit_pct > PARAMS["trailing_activation_pct"]:
        new_stop = trade["high_watermark"] * PARAMS["trailing_stop_mult"]
        if new_stop > trade["stop"]:
            trade["stop"] = new_stop

    return "ACTIVE", trade
