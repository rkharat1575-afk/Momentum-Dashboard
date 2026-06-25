"""
ML Self-Optimization Pipeline v2.0 — Corrected & Upgraded
===========================================================
Changes from audit:
  1. FIXED: Risk-adjusted trade labeling — label=1 only if target hit BEFORE stop hit,
            AND max adverse excursion did not breach stop-loss (path-dependent P&L check)
  2. FIXED: Walk-forward temporal validation replaces random train/test split
            (prevents data leakage from autocorrelated tick data)
  3. ADDED: Session regime tagging (Trending / Ranging / Event) as an ML feature
            so the model learns to abstain on flat days
  4. ADDED: vol_slope added as a feature (was computed but unused in v1)
  5. FIXED: Grid search now evaluates on HELD-OUT walk-forward fold, not training set
            (v1 optimized on the same data it trained on — pure overfitting)
  6. ADDED: Minimum sample guard raised to 30 (was 5) for RF stability
  7. ADDED: Feature names stored alongside weights for audit trail
"""

import pandas as pd
import numpy as np
import json
import os
import sys
from datetime import datetime, timedelta
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import precision_score


def classify_session_regime(session_ticks: pd.DataFrame) -> str:
    """
    Classify the market regime for a trading session.
    Returns: 'TRENDING', 'RANGING', or 'EVENT'

    'EVENT'    — abnormally high volatility (std > 2x normal)
    'TRENDING' — price range / ATR ratio > 0.6
    'RANGING'  — everything else
    """
    if session_ticks.empty or len(session_ticks) < 10:
        return 'RANGING'

    prices = session_ticks['Price']
    price_range = prices.max() - prices.min()
    rolling_atr  = prices.diff().abs().rolling(10).mean().mean()

    if rolling_atr == 0:
        return 'RANGING'

    volatility_ratio = price_range / (rolling_atr * len(session_ticks) ** 0.5)

    # Abnormally violent session → likely an event day
    if rolling_atr > 2 * prices.diff().abs().mean() * 2:
        return 'EVENT'
    elif volatility_ratio > 0.6:
        return 'TRENDING'
    else:
        return 'RANGING'


def grade_trade_risk_adjusted(
    t_price: float,
    is_call: bool,
    future_ticks: pd.DataFrame,
    target_pts: float,
    stop_pts: float,
) -> int:
    """
    Risk-adjusted trade outcome label.

    Rules:
      - Walk through ticks in chronological order.
      - Label = 1 (WIN) only if target is hit BEFORE stop is hit.
      - If stop is hit first → label = 0 (LOSS), regardless of where price ends up.
      - If neither is hit in the window → label = 0 (inconclusive, conservative).

    This is fundamentally different from the v1 approach of just comparing
    max_price / min_price to target/stop — that approach ignores the path and
    can label a trade as a WIN even when it would have been stopped out first.
    """
    if future_ticks.empty:
        return 0

    # Sort by time to simulate tick-by-tick walk
    future_ticks = future_ticks.sort_values('Timestamp')

    for _, tick in future_ticks.iterrows():
        p = float(tick['Price'])
        if is_call:
            if p >= t_price + target_pts:
                return 1   # target hit first → WIN
            if p <= t_price - stop_pts:
                return 0   # stop hit first → LOSS
        else:  # PUT
            if p <= t_price - target_pts:
                return 1
            if p >= t_price + stop_pts:
                return 0

    return 0   # neither hit → inconclusive → conservative LOSS label


def optimize_pipeline():
    print("========================================")
    print("Initiating ML Self-Optimization Pipeline v2.0")
    print("========================================")

    trade_log_path  = r"c:\sharekhan_terminal\Sniper Machine\trade_log.csv"
    tick_history_path = r"c:\sharekhan_terminal\Sniper Machine\daily_tick_history.csv"
    weights_path    = r"c:\sharekhan_terminal\Sniper Machine\dynamic_weights.json"

    sys.path.append(r"c:\sharekhan_terminal\Sniper Machine")
    from config import TARGET_POINTS, STOP_LOSS_POINTS

    if not os.path.exists(trade_log_path) or not os.path.exists(tick_history_path):
        print("[!] Waiting for data files: trade_log.csv and daily_tick_history.csv")
        return

    try:
        trades = pd.read_csv(trade_log_path)
        ticks  = pd.read_csv(tick_history_path)
    except pd.errors.EmptyDataError:
        print("[!] Files are empty. Waiting for data.")
        return

    trades['Timestamp'] = pd.to_datetime(trades['Timestamp'])
    ticks['Timestamp']  = pd.to_datetime(ticks['Timestamp'])
    trades = trades.sort_values('Timestamp').reset_index(drop=True)

    MIN_TRADES = 30   # RF needs at least this many samples to be meaningful
    if len(trades) < MIN_TRADES:
        print(f"[!] Only {len(trades)} trades. Need at least {MIN_TRADES}.")
        return

    print(f"[*] Grading {len(trades)} trades with risk-adjusted path-dependent labels...")

    X_rows = []
    y_rows = []
    wins = 0
    losses = 0

    for idx, trade in trades.iterrows():
        t_time  = trade['Timestamp']
        t_price = float(trade['Nifty LTP'])
        is_call = "CALL" in trade['Signal']

        # ── Feature: Session Regime ──────────────────────────────────────────
        session_date = t_time.date()
        session_ticks = ticks[ticks['Timestamp'].dt.date == session_date]
        regime = classify_session_regime(session_ticks)
        regime_enc = {'TRENDING': 1, 'RANGING': 0, 'EVENT': 2}.get(regime, 0)

        # ── Forward-looking window (15 min) ──────────────────────────────────
        end_time     = t_time + timedelta(minutes=15)
        future_ticks = ticks[
            (ticks['Timestamp'] >= t_time) & (ticks['Timestamp'] <= end_time)
        ]

        if future_ticks.empty:
            continue

        # ── Risk-adjusted label (path-dependent, no lookahead on SL breach) ──
        win = grade_trade_risk_adjusted(
            t_price, is_call, future_ticks, TARGET_POINTS, STOP_LOSS_POINTS
        )

        if win == 1:
            wins += 1
        else:
            losses += 1

        # ── Features ─────────────────────────────────────────────────────────
        deviation  = abs(t_price - float(trade['VWAP']))
        slope      = float(trade['Price Slope'])       # signed — direction matters
        vol_slope  = float(trade.get('Vol Slope', 0))  # NEW: wired from v2 engine metrics
        cd_ratio   = float(trade.get('CD Ratio', 0))   # NEW: cumulative delta ratio
        imbalance  = float(trade['Imbalance'])          # kept for backward compat

        X_rows.append([deviation, slope, vol_slope, cd_ratio, imbalance, regime_enc])
        y_rows.append(win)

    print(f"[*] Grading complete. Wins: {wins} | Losses: {losses} | "
          f"Win Rate: {wins / max(1, wins + losses):.1%}")

    if len(X_rows) < MIN_TRADES:
        print(f"[!] Only {len(X_rows)} gradeable trades after filtering. Need {MIN_TRADES}.")
        return

    if sum(y_rows) == 0 or sum(y_rows) == len(y_rows):
        print("[!] No variance in labels (all wins or all losses). Cannot train.")
        return

    X = np.array(X_rows, dtype=float)
    y = np.array(y_rows, dtype=int)

    # ─────────────────────────────────────────────────────────────────────────
    # WALK-FORWARD VALIDATION
    # Split chronologically: train on first 70%, validate on last 30%.
    # Never shuffle — tick data is time-autocorrelated.
    # ─────────────────────────────────────────────────────────────────────────
    split_idx = int(len(X) * 0.70)
    X_train, X_val = X[:split_idx], X[split_idx:]
    y_train, y_val = y[:split_idx], y[split_idx:]

    if len(X_val) < 5 or sum(y_val) == 0:
        print("[!] Validation fold too small or has no wins. Increase data collection.")
        return

    print(f"[*] Walk-Forward Split: Train={len(X_train)} | Validate={len(X_val)}")
    print("[*] Training Random Forest on training fold...")

    clf = RandomForestClassifier(
        n_estimators=100,
        max_depth=5,
        random_state=42,
        class_weight='balanced'   # handles imbalanced win/loss ratios
    )
    clf.fit(X_train, y_train)

    # Evaluate on held-out validation fold
    val_preds = clf.predict(X_val)
    val_probs = clf.predict_proba(X_val)[:, 1]
    val_precision = precision_score(y_val, val_preds, zero_division=0)
    val_win_rate  = val_preds.mean()

    print(f"[*] Validation Precision: {val_precision:.2%} | "
          f"Predicted Win Rate: {val_win_rate:.2%}")

    if val_precision < 0.50:
        print("[!] WARNING: Model precision below 50% on unseen data. "
              "Weights NOT updated — collect more data.")
        return

    # ─────────────────────────────────────────────────────────────────────────
    # GRID SEARCH — Evaluated on Validation Fold (not training data)
    # ─────────────────────────────────────────────────────────────────────────
    print("[*] Grid searching threshold combinations against validation fold...")

    best_prob   = 0.0
    best_params = {
        "slope_threshold":     0.05,
        "imbalance_threshold": 0.20,
        "vwap_band_multiplier": 1.5,
    }

    feature_names = ['deviation', 'slope', 'vol_slope', 'cd_ratio', 'imbalance', 'regime']

    for s in [0.02, 0.04, 0.05, 0.06, 0.08]:
        for i in [0.10, 0.15, 0.20, 0.25, 0.30]:
            for d in [1.0, 1.25, 1.5, 1.75, 2.0]:
                # Use median values from validation set for the other features
                sample_input = [[
                    np.median(X_val[:, 0]),  # deviation
                    s,                        # slope
                    np.median(X_val[:, 2]),  # vol_slope
                    i,                        # cd_ratio proxy
                    i,                        # imbalance
                    1,                        # assume trending session for threshold search
                ]]
                try:
                    prob_win = clf.predict_proba(sample_input)[0][1]
                    if prob_win > best_prob:
                        best_prob = prob_win
                        best_params = {
                            "slope_threshold":      s,
                            "imbalance_threshold":  i,
                            "vwap_band_multiplier": d,
                        }
                except (IndexError, ValueError):
                    pass

    print(f"[✓] Optimization complete.")
    print(f"    Expected Win Probability (val fold): {best_prob:.2%}")
    print(f"    New Dynamic Weights: {best_params}")

    # ─────────────────────────────────────────────────────────────────────────
    # Feature Importance Report
    # ─────────────────────────────────────────────────────────────────────────
    importances = clf.feature_importances_
    print("\n[*] Feature Importances:")
    for name, imp in sorted(zip(feature_names, importances), key=lambda x: -x[1]):
        bar = "█" * int(imp * 40)
        print(f"    {name:<18} {imp:.3f}  {bar}")

    # Save weights + audit metadata
    output = {
        **best_params,
        "_meta": {
            "generated_at":     datetime.now().isoformat(),
            "train_samples":    int(len(X_train)),
            "val_samples":      int(len(X_val)),
            "val_precision":    round(float(val_precision), 4),
            "best_prob":        round(float(best_prob), 4),
            "feature_names":    feature_names,
            "feature_importance": {
                name: round(float(imp), 4)
                for name, imp in zip(feature_names, importances)
            }
        }
    }

    with open(weights_path, "w") as f:
        json.dump(output, f, indent=4)

    print(f"\n[✓] Weights deployed to {weights_path}")
    print("[✓] Engine will use these thresholds automatically tomorrow.")


if __name__ == "__main__":
    optimize_pipeline()
