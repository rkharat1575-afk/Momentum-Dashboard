"""
chain_analyzer.py — Momentum Engine v2 (corrected)

BUGS FIXED vs original:
  1. _compute_seller_stress wall-proximity double-stack bug:
     The original iterated over call_walls in one loop, then immediately
     iterated over put_walls in a second loop — both contributing to the
     SAME running `score` variable. A single tick where price sat between a
     call wall and a put wall would add 15-25 pts from the call loop AND
     another 15-25 pts from the put loop, capping at the wrong point and
     making seller_stress_score artificially high on almost every tick near
     any strike with OI.

     FIX: each side (call and put) now computes its own sub-score (max 25),
     and the final wall contribution is max(call_sub, put_sub) — i.e. we
     take the more significant side, not the sum of both.

  2. compute_decayed_ofi is still exported here so chain_analyzer callers
     (e.g. the radar loop) can use it. signal_engine now has its own inline
     copy so there is zero runtime cross-import in the hot path.
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Optional
import logging

logger = logging.getLogger(__name__)

CHAIN_THRESHOLDS = {
    "pcr_bullish_below":         0.8,
    "pcr_bearish_above":         1.2,
    "pcr_shift_min":             0.10,
    "coi_velocity_strong":       5000,
    "coi_velocity_extreme":      15000,
    "gamma_wall_pct_of_chain":   0.08,
    "gamma_wall_proximity_pts":  50,
    "skew_neutral_band":         0.02,
    "skew_extreme":              0.06,
    "ofi_halflife_minutes":      3.0,
}


# ---------------------------------------------------------------------------
# DATA CLASSES
# ---------------------------------------------------------------------------

@dataclass
class GammaWall:
    strike:          float
    opt_type:        str
    gamma_exposure:  float
    pct_of_chain:    float
    coi_velocity:    float
    is_being_written: bool


@dataclass
class ChainContext:
    current_pcr:   float = 0.0
    prev_pcr:      float = 0.0
    pcr_shift:     float = 0.0
    pcr_bias:      str   = "NEUTRAL"

    call_walls:        list  = field(default_factory=list)
    put_walls:         list  = field(default_factory=list)
    nearest_call_wall: Optional[float] = None
    nearest_put_wall:  Optional[float] = None
    spot_price:        float = 0.0

    call_coi_velocity:     float = 0.0
    put_coi_velocity:      float = 0.0
    dominant_writing_side: str   = "NONE"

    skew_value:     float = 0.0
    skew_direction: str   = "NEUTRAL"
    skew_intensity: str   = "NORMAL"

    seller_stress_score: float = 0.0

    total_call_oi: float         = 0.0
    total_put_oi:  float         = 0.0
    chain_snapshot_time: Optional[str] = None


# ---------------------------------------------------------------------------
# PRIVATE HELPERS
# ---------------------------------------------------------------------------

def _estimate_gamma(row, spot: float) -> float:
    if spot <= 0 or row["IV"] <= 0:
        return 0.0
    moneyness   = abs(row["STRIKE"] - spot) / spot
    gamma_proxy = np.exp(-0.5 * (moneyness / 0.30) ** 2)
    return gamma_proxy * row["OI"]


def _classify_pcr(pcr: float, prev_pcr: float):
    shift = pcr - prev_pcr
    thresholds = CHAIN_THRESHOLDS

    if pcr < thresholds["pcr_bullish_below"]:
        bias = "BEARISH_SELLER"
    elif pcr > thresholds["pcr_bearish_above"]:
        bias = "BULLISH_SELLER"
    else:
        bias = "NEUTRAL"

    return bias, shift


def _find_gamma_walls(chain_df: pd.DataFrame, spot: float, has_gamma_col: bool):
    threshold_pct = CHAIN_THRESHOLDS["gamma_wall_pct_of_chain"]

    df = chain_df.copy()
    if has_gamma_col:
        df["GEX"] = df["OI"] * df["GAMMA"] * 50
    else:
        df["GEX"] = df.apply(lambda r: _estimate_gamma(r, spot), axis=1)

    total_gex = df["GEX"].sum()
    if total_gex <= 0:
        return [], []

    call_walls: list = []
    put_walls:  list = []

    for _, row in df.iterrows():
        pct = row["GEX"] / total_gex
        if pct < threshold_pct:
            continue

        coi_vel    = row["OI"] - row["PREV_OI"]
        is_writing = coi_vel > CHAIN_THRESHOLDS["coi_velocity_strong"]

        wall = GammaWall(
            strike=row["STRIKE"],
            opt_type=row["OPT_TYPE"],
            gamma_exposure=row["GEX"],
            pct_of_chain=pct,
            coi_velocity=coi_vel,
            is_being_written=is_writing,
        )
        if row["OPT_TYPE"] == "CE":
            call_walls.append(wall)
        else:
            put_walls.append(wall)

    call_walls.sort(key=lambda w: w.strike)
    put_walls.sort(key=lambda w: w.strike, reverse=True)
    return call_walls, put_walls


def _compute_iv_skew(chain_df: pd.DataFrame, spot: float) -> float:
    otm_calls = chain_df[
        (chain_df["OPT_TYPE"] == "CE") & (chain_df["STRIKE"] > spot)
    ].copy()
    otm_puts = chain_df[
        (chain_df["OPT_TYPE"] == "PE") & (chain_df["STRIKE"] < spot)
    ].copy()

    if otm_calls.empty or otm_puts.empty:
        return 0.0

    otm_calls["dist"] = otm_calls["STRIKE"] - spot
    otm_puts["dist"]  = spot - otm_puts["STRIKE"]

    nearest_call_dist = otm_calls["dist"].min()
    strike_interval   = chain_df["STRIKE"].diff().abs().median()
    matching_puts     = otm_puts[
        abs(otm_puts["dist"] - nearest_call_dist) <= strike_interval
    ]

    if matching_puts.empty:
        return 0.0

    call_iv = otm_calls.loc[otm_calls["dist"].idxmin(), "IV"]
    put_iv  = matching_puts.loc[matching_puts["dist"].idxmin(), "IV"]

    if call_iv <= 0 or put_iv <= 0:
        return 0.0

    return float(call_iv - put_iv)


def _classify_skew(skew_value: float):
    neutral = CHAIN_THRESHOLDS["skew_neutral_band"]
    extreme = CHAIN_THRESHOLDS["skew_extreme"]

    if abs(skew_value) <= neutral:
        direction = "NEUTRAL"
    elif skew_value > 0:
        direction = "CALL_BID"
    else:
        direction = "PUT_BID"

    if abs(skew_value) >= extreme:
        intensity = "EXTREME"
    elif abs(skew_value) >= neutral:
        intensity = "ELEVATED"
    else:
        intensity = "NORMAL"

    return direction, intensity


def _compute_coi_velocity(chain_df: pd.DataFrame):
    df = chain_df.copy()
    df["COI"] = df["OI"] - df["PREV_OI"]

    call_vel = df[df["OPT_TYPE"] == "CE"]["COI"].sum()
    put_vel  = df[df["OPT_TYPE"] == "PE"]["COI"].sum()

    strong = CHAIN_THRESHOLDS["coi_velocity_strong"]
    if abs(call_vel) > strong and abs(call_vel) > abs(put_vel) * 1.5:
        dominant = "CALL"
    elif abs(put_vel) > strong and abs(put_vel) > abs(call_vel) * 1.5:
        dominant = "PUT"
    else:
        dominant = "NONE"

    return float(call_vel), float(put_vel), dominant


def _compute_seller_stress(
    pcr_bias: str,
    pcr_shift: float,
    dominant_writing_side: str,
    call_walls: list,
    put_walls:  list,
    spot:       float,
    skew_intensity: str,
    skew_direction: str,
) -> float:
    """
    Composite seller stress score 0-100 from four independent components.

    BUG FIX:
    The original accumulated wall proximity points from call_walls and
    put_walls into the same running total, then applied min(score, 25) AFTER
    both loops — meaning both sides could contribute simultaneously, routinely
    producing wall-proximity sub-scores of 30-50 that drowned out the signal.

    Corrected logic: each side scores independently (max 25), final wall
    contribution = max(call_wall_sub, put_wall_sub). This mirrors the real
    market dynamic — you can only be squeezed by ONE dominant wall side per
    tick; the other side's wall is irrelevant to the directional stress.
    """
    score = 0.0
    prox  = CHAIN_THRESHOLDS["gamma_wall_proximity_pts"]

    # ── Component 1: PCR shift magnitude (max 25) ──────────────────────────
    shift_magnitude = abs(pcr_shift)
    score += min(25.0, shift_magnitude / CHAIN_THRESHOLDS["pcr_shift_min"] * 5)

    # ── Component 2: Gamma wall proximity (max 25) ─────────────────────────
    # FIX: score each side separately, take the dominant (max), not the sum.
    call_wall_sub = 0.0
    put_wall_sub  = 0.0

    if spot > 0:
        # Call-side walls
        for wall in call_walls:
            dist = wall.strike - spot
            if dist < 0:
                # Price has broken through call wall = sellers being squeezed
                call_wall_sub = 25.0
            elif dist <= prox:
                # Price approaching call wall = sellers defending
                call_wall_sub = 15.0
                if wall.is_being_written:
                    call_wall_sub = 20.0  # Fresh writing = higher stress
            if call_wall_sub > 0:
                break  # nearest wall dominates

        # Put-side walls
        for wall in put_walls:
            dist = spot - wall.strike
            if dist < 0:
                put_wall_sub = 25.0
            elif dist <= prox:
                put_wall_sub = 15.0
                if wall.is_being_written:
                    put_wall_sub = 20.0
            if put_wall_sub > 0:
                break

    score += max(call_wall_sub, put_wall_sub)  # Only dominant wall matters

    # ── Component 3: Writing side alignment (max 15) ───────────────────────
    if dominant_writing_side == "CALL" and pcr_bias == "BULLISH_SELLER":
        score += 15.0
    elif dominant_writing_side == "PUT" and pcr_bias == "BEARISH_SELLER":
        score += 15.0
    elif dominant_writing_side != "NONE":
        score += 8.0

    # ── Component 4: IV skew intensity (max 25) ────────────────────────────
    if skew_intensity == "EXTREME":
        score += 25.0
    elif skew_intensity == "ELEVATED":
        score += 12.0

    return min(100.0, score)


# ---------------------------------------------------------------------------
# PUBLIC API
# ---------------------------------------------------------------------------

def analyze_chain(
    chain_snapshot: pd.DataFrame,
    spot: float,
    prev_pcr: float = 1.0,
    snapshot_time: Optional[str] = None,
) -> ChainContext:
    """
    Build a ChainContext from a live options chain snapshot.

    Required columns: STRIKE, OPT_TYPE, OI, PREV_OI, IV, BID, ASK, LTP
    Optional:         GAMMA (if present, used directly; otherwise estimated)
    """
    required_cols = {"STRIKE", "OPT_TYPE", "OI", "PREV_OI", "IV", "BID", "ASK", "LTP"}
    missing = required_cols - set(chain_snapshot.columns)
    if missing:
        raise ValueError(f"chain_snapshot missing required columns: {missing}")

    df             = chain_snapshot.copy()
    has_gamma_col  = "GAMMA" in df.columns

    ctx = ChainContext(spot_price=spot, chain_snapshot_time=snapshot_time)

    call_oi = df[df["OPT_TYPE"] == "CE"]["OI"].sum()
    put_oi  = df[df["OPT_TYPE"] == "PE"]["OI"].sum()

    ctx.total_call_oi = float(call_oi)
    ctx.total_put_oi  = float(put_oi)
    ctx.current_pcr   = float(put_oi / call_oi) if call_oi > 0 else 1.0
    ctx.prev_pcr      = float(prev_pcr)
    ctx.pcr_bias, ctx.pcr_shift = _classify_pcr(ctx.current_pcr, prev_pcr)

    ctx.call_walls, ctx.put_walls = _find_gamma_walls(df, spot, has_gamma_col)

    call_walls_above = [w for w in ctx.call_walls if w.strike > spot]
    put_walls_below  = [w for w in ctx.put_walls  if w.strike < spot]
    ctx.nearest_call_wall = call_walls_above[0].strike if call_walls_above else None
    ctx.nearest_put_wall  = put_walls_below[0].strike  if put_walls_below  else None

    ctx.call_coi_velocity, ctx.put_coi_velocity, ctx.dominant_writing_side = \
        _compute_coi_velocity(df)

    ctx.skew_value = _compute_iv_skew(df, spot)
    ctx.skew_direction, ctx.skew_intensity = _classify_skew(ctx.skew_value)

    ctx.seller_stress_score = _compute_seller_stress(
        ctx.pcr_bias,
        ctx.pcr_shift,
        ctx.dominant_writing_side,
        ctx.call_walls,
        ctx.put_walls,
        spot,
        ctx.skew_intensity,
        ctx.skew_direction,
    )

    logger.info(
        "ChainContext @ %s | spot=%.0f | PCR=%.2f (shift=%.2f, bias=%s) | "
        "SellerStress=%.1f | Skew=%.3f (%s %s) | Dominant=%s",
        snapshot_time, spot, ctx.current_pcr, ctx.pcr_shift, ctx.pcr_bias,
        ctx.seller_stress_score, ctx.skew_value,
        ctx.skew_direction, ctx.skew_intensity, ctx.dominant_writing_side,
    )

    return ctx


def compute_decayed_ofi(
    ofi_history: list,
    halflife_minutes: Optional[float] = None,
) -> float:
    """
    Exponentially decayed OFI. Exported so radar_loop and other callers
    can use it without importing signal_engine (avoids circular imports).

    ofi_history: [(minutes_ago, ofi_value), ...]
    """
    if not ofi_history:
        return 0.0

    hl             = halflife_minutes or CHAIN_THRESHOLDS["ofi_halflife_minutes"]
    decay_constant = np.log(2) / hl

    weighted_sum = 0.0
    weight_total = 0.0
    for minutes_ago, ofi_value in ofi_history:
        w             = np.exp(-decay_constant * minutes_ago)
        weighted_sum += ofi_value * w
        weight_total += w

    return float(weighted_sum / weight_total) if weight_total > 0 else 0.0
