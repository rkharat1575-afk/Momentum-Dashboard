import pandas as pd
import json
import os
import logging
from datetime import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------------
# PARAMETERS
# ----------------------------------------------------------------------------
# WFO-OPTIMIZED params (loaded from optimized_params.json, overwrite defaults below)
PARAMS = {
    "take_profit_mult": 1.30,
    "stop_loss_mult": 0.90,
    "trailing_activation_pct": 0.05,
    "trailing_stop_mult": 0.90,
}

# NOT YET WFO-VALIDATED — these were hardcoded magic numbers in the original
# file (0.5% spread, 40000 OFI, 15 ticks/sec). They are kept here as named,
# overridable constants so you can run them through the same WFO process as
# the exit params above instead of trusting them as-is. Until you've
# validated them, treat any signal that depends on THRESHOLDS as unproven.
THRESHOLDS = {
    "max_spread_pct": 0.005,          # 0.5% — UNVALIDATED, likely wrong for one of Nifty/BankNifty
    "ofi_sweep_contracts": 450,      # UNVALIDATED
    "velocity_tps_min": 8,            # UNVALIDATED, no time-of-day calibration
    "oi_lookback_candles": 5,          # rolling window for OI/Volume baseline
    "oi_rise_min_pct": 0.02,           # OI must beat rolling mean by >= 2%
    "volume_rise_min_pct": 0.10,       # Volume must beat rolling mean by >= 10%
    "oi_persistence_required": 2,      # OI must be rising in >=2 of last 3 candles
    "price_extension_lookback": 20,    # candles needed for price-extension SMA
    "price_extension_max_pct": 1.40,   # price must be < 1.40x its own SMA
}

VALID_REVERSAL_STATES = {"SIDEWAYS", "REVERSAL_LONG", "REVERSAL_SHORT"}

if os.path.exists("optimized_params.json"):
    try:
        with open("optimized_params.json", "r") as f:
            data = json.load(f)
            PARAMS.update(data)
            logger.info("Loaded optimized_params.json: %s", data)
    except Exception as e:
        # Previously this was a silent `except: pass`. In live trading,
        # silently running on stale/default params for days because the WFO
        # output file got corrupted is a real money-losing failure mode.
        # Now it's logged loudly so you actually see it.
        logger.warning(
            "Failed to load optimized_params.json (%s). "
            "Falling back to DEFAULT params: %s", e, PARAMS
        )


def _validate_reversal_state(reversal_state):
    if reversal_state not in VALID_REVERSAL_STATES:
        raise ValueError(
            f"Invalid reversal_state '{reversal_state}'. "
            f"Must be one of {VALID_REVERSAL_STATES}. "
            f"A typo here would previously fail silently and let bad trades through."
        )


def _spread_is_toxic(bid, ask, ltp):
    """Returns True if bid/ask spread is too wide to trade safely."""
    if ltp > 0 and ask > bid:
        spread_pct = (ask - bid) / ltp
        if spread_pct > THRESHOLDS["max_spread_pct"]:
            return True
    return False


def _check_oi_buildup(df):
    """
    OI buildup check using a ROLLING BASELINE instead of single-candle
    comparison.

    Original logic was `current['OI'] > prev['OI']`, which fires on a
    1-contract increase — that's noise, not institutional positioning.

    Fixed logic:
      1. Current OI must exceed the rolling mean of the last N candles by
         at least `oi_rise_min_pct`.
      2. OI must have been rising in at least `oi_persistence_required` of
         the last 3 candle-over-candle comparisons (persistence, not a
         single blip).
    """
    lookback = THRESHOLDS["oi_lookback_candles"]
    if len(df) < lookback + 1:
        return False

    recent = df['OI'].iloc[-(lookback + 1):]
    rolling_mean = recent.iloc[:-1].mean()  # mean excluding current candle
    current_oi = recent.iloc[-1]

    if rolling_mean <= 0:
        return False

    pct_above_baseline = (current_oi - rolling_mean) / rolling_mean
    baseline_check = pct_above_baseline >= THRESHOLDS["oi_rise_min_pct"]

    # Persistence: of the last 3 candle-over-candle deltas, how many rose?
    last_4 = df['OI'].iloc[-4:].values if len(df) >= 4 else df['OI'].values
    rises = sum(1 for i in range(1, len(last_4)) if last_4[i] > last_4[i - 1])
    persistence_check = rises >= min(THRESHOLDS["oi_persistence_required"], len(last_4) - 1)

    return bool(baseline_check and persistence_check)


def _check_volume_rising(df):
    """
    Volume check using a rolling baseline instead of single-candle
    comparison. Current volume must exceed the rolling mean of the last
    N candles by at least `volume_rise_min_pct`, not just beat the
    immediately preceding candle by any amount.
    """
    lookback = THRESHOLDS["oi_lookback_candles"]
    if len(df) < lookback + 1:
        return False

    recent = df['VOLUME'].iloc[-(lookback + 1):]
    rolling_mean = recent.iloc[:-1].mean()
    current_vol = recent.iloc[-1]

    if rolling_mean <= 0:
        return False

    pct_above_baseline = (current_vol - rolling_mean) / rolling_mean
    return pct_above_baseline >= THRESHOLDS["volume_rise_min_pct"]


def check_price_extension(df):
    """
    Renamed from the original "IV / Premium Bloat Protection". The original
    function never touched implied volatility at all — it compared the
    option's own CLOSE price to its own 20-period SMA. That's a measure of
    PRICE EXTENSION relative to recent price action, not IV expansion. It's
    being renamed and documented honestly rather than left mislabeled.

    What a REAL IV bloat check would need:
      - The option's current IV (back-solved from price via Black-Scholes,
        or pulled directly if your chain feed provides it), OR
      - India VIX as a proxy for broad volatility regime, compared against
        its own recent rolling distribution (e.g. current VIX vs 20-period
        VIX mean/percentile).
      - If you have access to either, pass it in as `current_iv` /
        `iv_history` and replace this proxy's logic with a percentile-rank
        comparison (e.g. "is current IV above the 90th percentile of the
        last N sessions' IV").

    Returns one of: True (extended/bloated), False (not extended),
    None (insufficient data — caller must decide how to treat this; the
    original code silently treated insufficient data as "not bloated",
    which quietly disabled the check during the first ~20 minutes of the
    session — exactly when momentum bursts are common).
    """
    lookback = THRESHOLDS["price_extension_lookback"]
    if len(df) < lookback:
        return None  # unknown — caller decides, no silent false-negative

    sma = df['CLOSE'].rolling(window=lookback).mean().iloc[-1]
    current_close = df['CLOSE'].iloc[-1]
    if sma <= 0:
        return None

    return current_close >= (sma * THRESHOLDS["price_extension_max_pct"])


def check_ai_buy_signal(df, nifty_ofi, opt_type, reversal_state="SIDEWAYS", bid=0, ask=0, ltp=0):
    """
    Evaluates a pandas DataFrame of 1-minute historical candles for a specific Option.
    Institutional edge logic: OI Buildup (rolling baseline) + Underlying OFI
    Confirmation + Price Extension Check + Volume Confirmation (rolling baseline).
    """
    _validate_reversal_state(reversal_state)

    # 0. SPREAD TOXICITY SHIELD (SLIPPAGE PREVENTION)
    if _spread_is_toxic(bid, ask, ltp):
        return False

    # 1. QUANTITATIVE TRAP FILTER (Cross-Engine Validation)
    if opt_type == 'PE' and reversal_state == 'REVERSAL_LONG':
        return False
    if opt_type == 'CE' and reversal_state == 'REVERSAL_SHORT':
        return False

    if len(df) < 5:
        return False

    df = df.copy()

    # 2. TIME OF DAY FILTER
    current_time = df['DATETIME'].iloc[-1]
    if isinstance(current_time, str):
        current_time = pd.to_datetime(current_time)
    time_only = current_time.time()
    if time_only < time(9, 30) or time_only > time(15, 15):
        return False  # Avoid opening chop and expiry unwinding

    # 3. OPEN INTEREST BUILDUP (rolling baseline + persistence, see _check_oi_buildup)
    oi_building = _check_oi_buildup(df)

    # 4. UNDERLYING DIRECTION CONFIRMATION (NIFTY OFI)
    direction_confirmed = False
    if opt_type == 'CE' and nifty_ofi > 0:
        direction_confirmed = True
    elif opt_type == 'PE' and nifty_ofi < 0:
        direction_confirmed = True

    # 5. PRICE EXTENSION CHECK (renamed/fixed — see check_price_extension docstring)
    extension_state = check_price_extension(df)
    # If unknown (insufficient history), fail safe rather than silently pass.
    # This is a deliberate behavior change from the original: previously
    # "not enough data" meant "assume not bloated" (risk left open). Here it
    # blocks the trade until there's enough history to actually judge it.
    not_extended = (extension_state is False)

    # 6. VOLUME CONFIRMATION (rolling baseline, see _check_volume_rising)
    volume_rising = _check_volume_rising(df)

    return bool(oi_building and direction_confirmed and not_extended and volume_rising)


def check_velocity_sweep_signal(df, nifty_ofi, velocity_tps, opt_type, reversal_state="SIDEWAYS", bid=0, ask=0, ltp=0):
    """
    Sub-second Tape Speed Execution. Triggers on Tick Velocity + Massive OFI
    acceleration, bypassing the 1-minute OI/Volume lag.

    CHANGED: now takes `df` and applies the same time-of-day filter as
    check_ai_buy_signal. The original had no time gate here at all, meaning
    it would happily fire during the 9:15-9:30 opening chop that the other
    signal explicitly avoids — an inconsistent risk posture between your two
    entry paths. If you call this without a df available in your live loop,
    pass the same 1-min candle buffer you already maintain elsewhere.
    """
    _validate_reversal_state(reversal_state)

    # 0. SPREAD TOXICITY SHIELD
    if _spread_is_toxic(bid, ask, ltp):
        return False

    # 1. QUANTITATIVE TRAP FILTER
    if opt_type == 'PE' and reversal_state == 'REVERSAL_LONG':
        return False
    if opt_type == 'CE' and reversal_state == 'REVERSAL_SHORT':
        return False

    # 2. TIME OF DAY FILTER (now consistent with check_ai_buy_signal)
    if df is not None and len(df) > 0:
        current_time = df['DATETIME'].iloc[-1]
        if isinstance(current_time, str):
            current_time = pd.to_datetime(current_time)
        time_only = current_time.time()
        if time_only < time(9, 30) or time_only > time(15, 15):
            return False

    # 3. VELOCITY THRESHOLD
    if velocity_tps < THRESHOLDS["velocity_tps_min"]:
        return False

    # 4. ACCELERATION THRESHOLD (institutional size of the sweep)
    if opt_type == 'CE' and nifty_ofi > THRESHOLDS["ofi_sweep_contracts"]:
        return True
    elif opt_type == 'PE' and nifty_ofi < -THRESHOLDS["ofi_sweep_contracts"]:
        return True

    return False


def get_exit_levels(entry_price):
    """Returns the initial Take Profit and Stop Loss levels based on WFO params."""
    take_profit = entry_price * PARAMS["take_profit_mult"]
    stop_loss = entry_price * PARAMS["stop_loss_mult"]
    return take_profit, stop_loss


def open_trade(entry_price):
    """
    Helper to construct a new trade dict with all fields manage_trade expects,
    including the high_watermark needed for correct trailing-stop behavior.
    Use this (or replicate its fields) wherever you currently create trade
    dicts, so manage_trade always has what it needs.
    """
    target, stop = get_exit_levels(entry_price)
    return {
        "entry": entry_price,
        "target": target,
        "stop": stop,
        "high_watermark": entry_price,  # NEW — tracks peak LTP since entry
    }


def manage_trade(trade, current_ltp):
    """
    Evaluates if a trade should be stopped out or if its stop loss should be
    trailed up.

    BUG FIX: the original trailed the stop off `current_ltp` directly:
        new_trailing_stop = current_ltp * trailing_stop_mult
    This means if price ticks 100 -> 110 -> 105, the stop gets calculated
    from 105 (the latest tick), not 110 (the actual peak) — so you give back
    more profit than intended on any pullback after a spike. A trailing stop
    must trail off the HIGH WATERMARK, not the latest price.

    This version persists `high_watermark` on the trade dict, updates it
    every call, and trails off that watermark instead.

    Returns:
        status (str): "ACTIVE", "TARGET HIT", "STOPPED OUT"
        trade (dict): updated trade object (high_watermark and/or stop may change)
    """
    if "high_watermark" not in trade:
        # Defensive fallback if an old-style trade dict (pre-fix) is passed in.
        trade["high_watermark"] = max(trade["entry"], current_ltp)

    # Update high watermark BEFORE evaluating exits, so a peak tick that
    # also happens to hit target is still recorded correctly.
    if current_ltp > trade["high_watermark"]:
        trade["high_watermark"] = current_ltp

    # Check fixed exits
    if current_ltp >= trade['target']:
        return "TARGET HIT", trade

    if current_ltp <= trade['stop']:
        return "STOPPED OUT", trade

    # Trailing stop logic, now based on the high watermark, not current_ltp
    profit_pct = (trade["high_watermark"] - trade['entry']) / trade['entry']

    if profit_pct > PARAMS["trailing_activation_pct"]:
        new_trailing_stop = trade["high_watermark"] * PARAMS["trailing_stop_mult"]
        # Only move stop UP, never down
        if new_trailing_stop > trade['stop']:
            trade['stop'] = new_trailing_stop

    return "ACTIVE", trade
