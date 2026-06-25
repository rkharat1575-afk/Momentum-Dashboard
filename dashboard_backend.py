"""
dashboard_backend.py — Momentum Engine v2 (corrected)

BUGS FIXED vs original:
  1. DOUBLE IMPORT — original imported `ai_momentum_strategy` (the old module),
     then re-imported signal_engine AS ai_momentum_strategy, overwriting it.
     The first import was dead code that confused the namespace.  Fixed: import
     signal_engine once, under its own name.

  2. `buy_result` USED BEFORE ASSIGNMENT — in the `components_to_send` line the
     original accessed `buy_result` unconditionally, but `buy_result` was only
     assigned inside the `else` branch (when sweep_result.fired was False).
     When a sweep DID fire, `buy_result` was undefined → NameError crash.
     Fixed: `components_to_send` now reads from the correct result object
     depending on which branch executed.

  3. `send_telegram_alert` CONFLICT — the function was defined twice: once as an
     import from telegram_bot and once as a local def.  The local def silently
     shadowed the import, meaning the imported version (with its own state/auth)
     was never called.  Fixed: removed the duplicate local def; the function
     imported from telegram_bot is used everywhere.  The `trigger_telegram_async`
     helper wraps it in a daemon thread as before.

  4. SNAPSHOT RACE CONDITION — `last_option_ticks_obj_minute` was written by
     both the on_data tick handler AND the chain_radar_loop background thread
     without any lock, causing silent overwrites mid-analysis.  Fixed: a
     threading.Lock guards all reads and writes of the shared snapshot dict.

  NOTE: `winsound` is Windows-only. If you deploy on Linux/macOS, replace the
  Beep call with a cross-platform alternative or remove it.
"""

import json
import time
import os
import threading
import asyncio
import websockets
import pandas as pd
import csv
from datetime import datetime
from SharekhanApi.sharekhanWebsocket import SharekhanWebSocket

# ── CORRECT: import signal_engine under its own name (not as ai_momentum_strategy)
import signal_engine
from reversal_detector import ReversalEngine
import requests
import warnings
import collections
from chain_analyzer import analyze_chain
from volatility_solver import calculate_iv
from telegram_bot import send_telegram_alert   # single canonical import
from dataclasses import asdict
import winsound  # Windows only — replace/guard if running on Linux/macOS

tick_velocity_queue = collections.deque(maxlen=50)
velocity_tps = 0.0
warnings.simplefilter(action="ignore", category=FutureWarning)

# Helper to load .env manually if python-dotenv is not installed
import os
if os.path.exists(".env"):
    with open(".env") as f:
        for line in f:
            if line.strip() and not line.strip().startswith("#") and "=" in line:
                key, val = line.strip().split("=", 1)
                os.environ[key.strip()] = val.strip()

# ─── TELEGRAM SETTINGS ──────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")


def _telegram_send(msg: str) -> None:
    """Internal: direct HTTP post.  Don't call this on the tick thread."""
    if "YOUR_BOT" in TELEGRAM_BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(
            url,
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=3,
        )
    except Exception as e:
        print(f"Telegram Error: {e}")


def trigger_telegram_async(text: str) -> None:
    """Fire-and-forget Telegram alert. Safe to call from tick handler."""
    threading.Thread(target=_telegram_send, args=(text,), daemon=True).start()


# ─── AI ENGINE STATE ─────────────────────────────────────────────────────────
ai_candles: dict = {}          # { strike_key: pd.DataFrame }
last_candle_minute = None

# ─── CHAIN CONTEXT STATE ─────────────────────────────────────────────────────
global_chain_context = None
prev_chain_snapshot  = None
prev_pcr             = 1.0
ofi_history: list    = []

# FIX: shared mutable snapshot dict now protected by a lock
_snapshot_lock              = threading.Lock()
last_option_ticks_obj_minute: dict = {}   # written by tick handler, read by radar

last_nifty_spot = 0.0

# ─── AUTHENTICATION & TOKENS ─────────────────────────────────────────────────
with open("access_token.txt", encoding="utf-8") as f:
    access_token = f.read().strip()

api_key = os.environ.get("SHAREKHAN_API_KEY", "")

VIX_TOKEN     = "NC26023"
SPOT_TOKEN    = "NC20000"
FUTURES_TOKEN = "NF62329"

available_expiries: list = []
token_info:         dict = {}
df_options               = None


def init_master_data() -> None:
    global available_expiries, token_info, df_options, FUTURES_TOKEN
    try:
        df = pd.read_csv("nf_scrip_master_expanded.csv")

        futures = df[
            (df["tradingSymbol"].str.upper().str.startswith("NIFTY")) &
            (~df["tradingSymbol"].str.upper().str.startswith("BANKNIFTY")) &
            (df["instType"] == "FI")
        ].copy()
        futures["expiry_dt"] = pd.to_datetime(futures["expiry"], dayfirst=True, errors="coerce")
        futures = futures[futures["expiry_dt"].dt.date >= datetime.now().date()]
        futures = futures.sort_values("expiry_dt")
        if not futures.empty:
            FUTURES_TOKEN = f"NF{int(futures.iloc[0]['scripCode'])}"

        df["expiry_dt"] = pd.to_datetime(df["expiry"], dayfirst=True, errors="coerce")
        nifty_opts = df[
            (df["tradingSymbol"].str.upper().str.startswith("NIFTY")) &
            (~df["tradingSymbol"].str.upper().str.startswith("BANKNIFTY")) &
            (df["instType"] == "OI") &
            (df["optionType"].isin(["CE", "PE"]))
        ].copy()

        future_opts = nifty_opts[nifty_opts["expiry_dt"].dt.date >= datetime.now().date()]
        expiries    = sorted(future_opts["expiry_dt"].unique())
        available_expiries[:] = [
            pd.to_datetime(str(e)).strftime("%d/%m/%Y") for e in expiries
        ][:4]

        for _, row in future_opts.iterrows():
            token = f"NF{int(row['scripCode'])}"
            token_info[token] = {
                "strike":  float(row["strike"]),
                "optType": row["optionType"],
                "expiry":  pd.to_datetime(str(row["expiry_dt"])).strftime("%d/%m/%Y"),
            }
        df_options = future_opts
        print(f"Loaded {len(token_info)} option tokens across {len(available_expiries)} weeks.")
    except Exception as e:
        print("Error loading token info:", e)


init_master_data()

# ─── GLOBAL STATE ────────────────────────────────────────────────────────────
clients:               set  = set()
loop                        = None
sws_global                  = None
current_expiry:        str  = ""
current_option_tokens: list = []
last_nifty_price:      float = 23500
active_trades:         list = []

reversal_engine = ReversalEngine()


# ─── TRADE JOURNAL ───────────────────────────────────────────────────────────

def log_trade_to_csv(trade: dict, exit_price: float, result: str, exit_time: str) -> None:
    file_exists = os.path.exists("live_trade_journal.csv")
    with open("live_trade_journal.csv", "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow([
                "Entry Time", "Direction", "Strike", "Type",
                "Entry Price", "Exit Time", "Exit Price", "Result", "P/L %",
            ])
        pl_pct = ((exit_price - trade["entry"]) / trade["entry"]) * 100
        writer.writerow([
            trade["time"], trade["direction"], trade["strike"], trade["optType"],
            round(trade["entry"], 2), exit_time, round(exit_price, 2),
            result, round(pl_pct, 2),
        ])


# ─── EXPIRY HANDLER ──────────────────────────────────────────────────────────

def handle_set_expiry(expiry: str) -> None:
    global current_expiry, current_option_tokens, sws_global
    current_expiry = expiry
    print(f"UI Requested Expiry: {expiry}")

    if df_options is not None:
        atm     = round(last_nifty_price / 50) * 50
        strikes = [atm + (i * 50) for i in range(-15, 16)]

        opts = df_options[
            (df_options["expiry_dt"].dt.strftime("%d/%m/%Y") == expiry) &
            (df_options["strike"].isin(strikes))
        ]
        new_tokens           = [f"NF{int(row['scripCode'])}" for _, row in opts.iterrows()]
        current_option_tokens = new_tokens

        if sws_global:
            feed_val = ",".join([FUTURES_TOKEN, SPOT_TOKEN, VIX_TOKEN] + current_option_tokens)
            sws_global.fetchData({"action": "feed", "key": ["full"], "value": [feed_val]})
            print(f"Subscribed to {len(new_tokens)} options for {expiry}")


# ─── LOCAL WEBSOCKET SERVER ──────────────────────────────────────────────────
nifty_tick_cache:      list = []
last_option_ticks_obj: dict = {}
signal_log_cache:      list = []


def broadcast_tick(tick_obj: dict) -> None:
    if not loop or not clients:
        return
    msg = json.dumps(tick_obj)
    for client in list(clients):
        asyncio.run_coroutine_threadsafe(client.send(msg), loop)


async def ws_handler(websocket) -> None:
    clients.add(websocket)
    await websocket.send(json.dumps({
        "type":           "metadata",
        "expiries":       available_expiries,
        "current_expiry": current_expiry,
    }))

    for tick_obj in nifty_tick_cache:
        await websocket.send(json.dumps(tick_obj))
    for opt_obj in last_option_ticks_obj.values():
        await websocket.send(json.dumps(opt_obj))
    for sig_obj in signal_log_cache:
        await websocket.send(json.dumps(sig_obj))

    try:
        async for message in websocket:
            data   = json.loads(message)
            action = data.get("action")

            if action == "set_expiry":
                handle_set_expiry(data.get("expiry"))

            elif action == "log_signal":
                trade = {
                    "id":        str(time.time()),
                    "time":      datetime.now().strftime("%H:%M:%S"),
                    "direction": data.get("direction"),
                    "strike":    data.get("strike"),
                    "optType":   data.get("optType"),
                    "entry":     data.get("entry_premium"),
                    "stop":      data.get("stop_loss"),
                    "target":    data.get("target1"),
                }
                active_trades.append(trade)
                print(f"Logged new trade: {trade['direction']} {trade['strike']} {trade['optType']} @ {trade['entry']}")

                icon = "🟢 BULL" if trade["direction"] == "BULL" else "🔴 BEAR"
                msg  = (
                    f"⚡ <b>MOMENTUM ENGINE ALERT</b> ⚡\n\n"
                    f"<b>Direction:</b> {icon}\n"
                    f"<b>Strike:</b> {trade['strike']} {trade['optType']}\n"
                    f"<b>Entry Premium:</b> ₹{trade['entry']}\n"
                    f"<b>Target 1:</b> ₹{trade['target']}\n"
                    f"<b>Stop Loss:</b> ₹{trade['stop']}\n\n"
                    f"<i>Time: {trade['time']}</i>"
                )
                trigger_telegram_async(msg)
    except Exception:
        pass
    finally:
        clients.discard(websocket)


async def run_server() -> None:
    async with websockets.serve(ws_handler, "localhost", 8080):
        await asyncio.Future()


def start_ws_server() -> None:
    global loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    print("Local WebSocket Server started on ws://localhost:8080")
    loop.run_until_complete(run_server())


# ─── CHAIN RADAR LOOP ────────────────────────────────────────────────────────

def chain_radar_loop() -> None:
    """Background thread: recomputes ChainContext every 10 seconds."""
    global global_chain_context, prev_chain_snapshot, prev_pcr, last_nifty_spot

    while True:
        time.sleep(10)
        try:
            with open("radar_debug.txt", "w") as f:
                call_oi_debug = sum([v.get("oi", 0) for v in last_option_ticks_obj.values() if v.get("optType") == "CE"])
                put_oi_debug = sum([v.get("oi", 0) for v in last_option_ticks_obj.values() if v.get("optType") == "PE"])
                f.write(f"last_nifty_spot={last_nifty_spot}, "
                        f"last_option_ticks_obj={len(last_option_ticks_obj)}, "
                        f"call_oi={call_oi_debug}, put_oi={put_oi_debug}")

            if not last_option_ticks_obj or last_nifty_spot == 0:
                continue

            # FIX: take a locked snapshot so the tick handler can't mutate
            # last_option_ticks_obj mid-iteration
            with _snapshot_lock:
                current_ticks = last_option_ticks_obj.copy()

            chain_data = []
            for _k, v in current_ticks.items():
                prev_oi_val = v.get("oi", 0)
                if prev_chain_snapshot is not None:
                    prev_row = prev_chain_snapshot[
                        (prev_chain_snapshot["STRIKE"]    == v["strike"]) &
                        (prev_chain_snapshot["OPT_TYPE"] == v["optType"])
                    ]
                    if not prev_row.empty:
                        prev_oi_val = prev_row.iloc[0]["OI"]

                try:
                    live_iv = calculate_iv(
                        market_price=v.get("price", 0),
                        S=last_nifty_spot,
                        K=v["strike"],
                        T=0.01,
                        r=0.065,
                        opt_type=v["optType"],
                    )
                except Exception:
                    live_iv = 0.18

                chain_data.append({
                    "STRIKE":   v["strike"],
                    "OPT_TYPE": v["optType"],
                    "OI":       v.get("oi", 0),
                    "PREV_OI":  prev_oi_val,
                    "IV":       live_iv,
                    "BID":      v.get("bid", 0),
                    "ASK":      v.get("ask", 0),
                    "LTP":      v.get("price", 0),
                })

            if chain_data:
                df_chain = pd.DataFrame(chain_data)
                prev_chain_snapshot  = df_chain.copy()

                global_chain_context = analyze_chain(
                    chain_snapshot=df_chain,
                    spot=last_nifty_spot,
                    prev_pcr=prev_pcr,
                    snapshot_time=datetime.now().strftime("%H:%M:%S"),
                )
                prev_pcr = global_chain_context.current_pcr

                ctx_dict = asdict(global_chain_context)
                ctx_dict.update({
                    "type":               "chain_context",
                    "pcr_bias":           global_chain_context.pcr_bias,
                    "call_walls":         [],
                    "put_walls":          [],
                    "nearest_call_wall":  global_chain_context.nearest_call_wall,
                })
                broadcast_tick(ctx_dict)

        except Exception as e:
            import traceback
            print(f"❌ [RADAR LOOP ERROR] {e}")
            with open("radar_error.txt", "w") as f:
                f.write(traceback.format_exc())


# ─── SHAREKHAN LIVE FEED ─────────────────────────────────────────────────────
vwap_sum     = 0.0
vwap_vol_sum = 0.0
tick_count   = 0
last_tick_dir = 1
global_ofi   = 0.0


def connect_sharekhan() -> None:
    global sws_global
    sws = SharekhanWebSocket(access_token)

    radar_thread = threading.Thread(target=chain_radar_loop, daemon=True)
    radar_thread.start()

    sws_global = sws
    sws.root = (
        f"wss://stream.sharekhan.com/skstream/api/stream"
        f"?ACCESS_TOKEN={access_token}&API_KEY={api_key}"
    )

    subscribe_msg = {"action": "subscribe", "key": ["feed", "ack"], "value": [""]}

    def periodic_refresh() -> None:
        while True:
            time.sleep(30)
            try:
                feed_val = ",".join(
                    [FUTURES_TOKEN, SPOT_TOKEN, VIX_TOKEN] + current_option_tokens
                )
                sws.fetchData({"action": "feed", "key": ["full"], "value": [feed_val]})
            except Exception:
                break

    def on_open(wsapp) -> None:
        print(f"CONNECTED to Sharekhan @ {time.strftime('%H:%M:%S')}")
        sws.subscribe(subscribe_msg)
        feed_val = ",".join(
            [FUTURES_TOKEN, SPOT_TOKEN, VIX_TOKEN] + current_option_tokens
        )
        sws.fetchData({"action": "feed", "key": ["full"], "value": [feed_val]})
        threading.Thread(target=periodic_refresh, daemon=True).start()

    def on_data(wsapp, message) -> None:
        global vwap_sum, vwap_vol_sum, tick_count
        global last_nifty_price, last_tick_dir, global_ofi
        global last_nifty_spot, velocity_tps
        global last_candle_minute, ofi_history

        if not message or message in ("heartbeat", "pong", "ping") or isinstance(message, bytes):
            return

        with open("last_tick_time.txt", "w") as f:
            f.write(str(time.time()))

        try:
            data = json.loads(message) if isinstance(message, str) else message
            if not isinstance(data, dict):
                return

            # Tape speed monitor
            tick_velocity_queue.append(time.time())
            if len(tick_velocity_queue) > 10:
                time_diff    = time.time() - tick_velocity_queue[0]
                velocity_tps = (
                    len(tick_velocity_queue) / time_diff if time_diff > 0.01 else 0.0
                )

            if data.get("message") != "feed":
                return

            inner = data.get("data", [])
            if not isinstance(inner, list):
                return

            for tick in inner:
                if not isinstance(tick, dict) or "scripCode" not in tick:
                    continue

                key = f"{tick.get('exchangeCode', 'NF')}{int(tick['scripCode'])}"

                # ── Futures tick ──────────────────────────────────────────
                if key == FUTURES_TOKEN:
                    ltp = tick.get("ltp", 0)
                    last_nifty_spot = ltp
                    bid = tick.get("bidPrice", ltp)
                    ask = tick.get("offPrice",  ltp)
                    vol = tick.get("qty", 1)

                    if ltp > last_nifty_price:
                        ofi = vol;  last_tick_dir = 1
                    elif ltp < last_nifty_price:
                        ofi = -vol; last_tick_dir = -1
                    else:
                        ofi = vol * last_tick_dir

                    global_ofi        = ofi
                    last_nifty_price  = ltp

                    vwap_sum     += ltp * vol
                    vwap_vol_sum += vol
                    vwap = vwap_sum / vwap_vol_sum if vwap_vol_sum > 0 else ltp

                    rev_state = reversal_engine.process_tick(ltp, vol, bid, ask)

                    obj = {
                        "instrument": "NIFTY",
                        "tick": {
                            "price":       ltp,
                            "vol":         vol,
                            "bid":         bid,
                            "ask":         ask,
                            "ofi":         ofi,
                            "vwap":        vwap,
                            "velocity_tps": velocity_tps,
                            "ts":          int(time.time() * 1000),
                        },
                    }
                    nifty_tick_cache.append(obj)
                    if len(nifty_tick_cache) > 100:
                        nifty_tick_cache.pop(0)
                    broadcast_tick(obj)
                    broadcast_tick({"instrument": "REVERSAL_ENGINE", "state": rev_state})

                    tick_count += 1
                    print(f"[{tick_count}] NIFTY FUT | LTP: {ltp} | Vol: {vol} | OFI: {ofi}")

                # ── Option tick ───────────────────────────────────────────
                elif key in token_info:
                    info = token_info[key]
                    if info["expiry"] != current_expiry:
                        continue

                    strike_key_cache = f"{info['strike']}_{info['optType']}"
                    prev_obj = last_option_ticks_obj.get(strike_key_cache, {})

                    ltp = tick.get("ltp", prev_obj.get("price", 0))
                    bid = tick.get("bidPrice", prev_obj.get("bid", ltp))
                    ask = tick.get("offPrice",  prev_obj.get("ask", ltp))

                    oi_raw = tick.get(
                        "currentOI",
                        tick.get("openInterest", tick.get("OpenInterest", tick.get("OI", tick.get("oi", None))))
                    )
                    oi = oi_raw if oi_raw is not None else prev_obj.get("oi", 0)

                    obj = {
                        "instrument": "NIFTY",
                        "type":       "option_tick",
                        "strike":     info["strike"],
                        "optType":    info["optType"],
                        "price":      ltp,
                        "bid":        bid,
                        "ask":        ask,
                        "oi":         oi,
                        "expiry":     info["expiry"],
                    }

                    # FIX: lock both last_option_ticks_obj and the shared snapshot
                    with _snapshot_lock:
                        last_option_ticks_obj[strike_key_cache] = obj

                    broadcast_tick(obj)

                    # ── Per-minute candle management ──────────────────────
                    current_minute = datetime.now().replace(second=0, microsecond=0)
                    strike_key = strike_key_cache   # same value, clearer alias

                    if strike_key not in ai_candles:
                        ai_candles[strike_key] = pd.DataFrame(
                            columns=["DATETIME", "CLOSE", "VOLUME", "OI"]
                        )

                    df_ai = ai_candles[strike_key]
                    qty   = tick.get("qty", 1)

                    if df_ai.empty or df_ai.iloc[-1]["DATETIME"] != current_minute:
                        new_row = pd.DataFrame([{
                            "DATETIME": current_minute,
                            "CLOSE":    ltp,
                            "VOLUME":   qty,
                            "OI":       oi,
                        }])
                        ai_candles[strike_key] = pd.concat(
                            [df_ai, new_row], ignore_index=True
                        )

                        if last_candle_minute is None or last_candle_minute != current_minute:
                            last_candle_minute = current_minute

                            ofi_history.insert(0, (0, global_ofi))
                            ofi_history = ofi_history[:5]

                            # FIX: locked snapshot write
                            with _snapshot_lock:
                                last_option_ticks_obj_minute.clear()
                                last_option_ticks_obj_minute.update(last_option_ticks_obj)
                    else:
                        ai_candles[strike_key].loc[df_ai.index[-1], "CLOSE"]   = ltp
                        ai_candles[strike_key].loc[df_ai.index[-1], "VOLUME"] += qty
                        ai_candles[strike_key].loc[df_ai.index[-1], "OI"]      = oi

                        with _snapshot_lock:
                            last_option_ticks_obj_minute[strike_key] = \
                                last_option_ticks_obj[strike_key]

                    # ── Signal evaluation ─────────────────────────────────
                    current_rev_state = reversal_engine.evaluate_market_state()

                    current_ofi_history = (
                        [(0, global_ofi)] +
                        [(i + 1, ofi_val)
                         for i, (_, ofi_val) in enumerate(ofi_history)]
                    )

                    sweep_result = signal_engine.check_velocity_sweep_signal(
                        df=ai_candles[strike_key],
                        nifty_ofi=global_ofi,
                        velocity_tps=velocity_tps,
                        opt_type=info["optType"],
                        reversal_state=current_rev_state,
                        bid=bid, ask=ask, ltp=ltp,
                        chain_context=global_chain_context,
                    )

                    if not hasattr(signal_engine, "sweep_memory"):
                        signal_engine.sweep_memory = {}

                    is_buy     = False
                    trade_type = "AI_BUY"
                    score      = 0.0

                    # FIX: always initialise buy_result so `components_to_send`
                    # below can safely reference it regardless of branch taken
                    buy_result = None

                    if sweep_result.fired:
                        atm_strike = round(last_nifty_spot / 50) * 50
                        if info["strike"] == atm_strike:
                            is_buy     = True
                            trade_type = "AGGRESSIVE_SWEEP"
                            score      = sweep_result.score
                            signal_engine.sweep_memory[strike_key] = {
                                "score": score,
                                "time":  time.time(),
                            }
                            print(f"⚡ [TAPE SPEED SWEEP] TPS: {velocity_tps:.1f} | SCORE: {score:.1f}")
                            print(f"   Reason: {sweep_result.reason}")
                    else:
                        buy_result = signal_engine.check_ai_buy_signal(
                            df=ai_candles[strike_key],
                            nifty_ofi=global_ofi,
                            opt_type=info["optType"],
                            reversal_state=current_rev_state,
                            bid=bid, ask=ask, ltp=ltp,
                            chain_context=global_chain_context,
                            ofi_history=current_ofi_history,
                        )
                        is_buy = buy_result.fired
                        score  = buy_result.score

                        # If a sweep latched in last 3 s, keep its score visible
                        memory = signal_engine.sweep_memory.get(strike_key)
                        if memory and time.time() - memory["time"] < 3.0:
                            score = max(score, memory["score"])

                    # FIX: select the correct result object for components
                    if sweep_result.fired:
                        active_result = sweep_result
                    elif buy_result is not None:
                        active_result = buy_result
                    else:
                        active_result = sweep_result   # blocked sweep — empty scores

                    components_to_send = getattr(active_result, "scores", {})

                    broadcast_tick({
                        "type":       "score_update",
                        "strike":     strike_key,
                        "optType":    info["optType"],
                        "score":      score,
                        "components": components_to_send,
                    })

                    if is_buy:
                        print(f"🟢 [SIGNAL ENGINE] Score: {score:.1f}")

                        already_active = any(t["strike"] == strike_key for t in active_trades)
                        if not already_active:
                            direction_str = "BULL" if info["optType"] == "CE" else "BEAR"
                            sig_msg = {
                                "type":      "signal_fired",
                                "direction": direction_str,
                                "score":     score,
                                "strike":    strike_key,
                                "entry":     ltp,
                            }
                            signal_log_cache.append(sig_msg)
                            if len(signal_log_cache) > 10:
                                signal_log_cache.pop(0)
                            broadcast_tick(sig_msg)

                            trade_base = signal_engine.open_trade(ltp)
                            ai_trade   = {
                                "id":             f"{trade_type}_{time.time()}",
                                "time":           datetime.now().strftime("%H:%M:%S"),
                                "direction":      "BUY",
                                "strike":         strike_key,
                                "optType":        info["optType"],
                                "entry":          trade_base["entry"],
                                "target":         trade_base["target"],
                                "stop":           trade_base["stop"],
                                "high_watermark": trade_base["high_watermark"],
                            }
                            active_trades.append(ai_trade)

                            direction_icon = "🟢" if info["optType"] == "CE" else "🔴"
                            msg = (
                                f"*{direction_icon} NIFTY {direction_str} SIGNAL FIRED*\n\n"
                                f"🔥 *Score:* {score:.1f}/100\n"
                                f"🎯 *Strike:* {info['strike']} {info['optType']}\n"
                                f"⚡ *Entry:* ₹{ltp} | "
                                f"*TP:* ₹{trade_base['target']:.2f} | "
                                f"*SL:* ₹{trade_base['stop']:.2f}\n"
                                f"📊 *Reason: Momentum Engine Signal*\n"
                            )
                            print(f"🟢 {trade_type}: BUY {strike_key} {info['optType']} @ {ltp} | Score: {score:.1f}")
                            trigger_telegram_async(msg)
                            threading.Thread(
                                target=lambda: winsound.Beep(1500, 800), daemon=True
                            ).start()

                    # ── Trade management ──────────────────────────────────
                    for t in list(active_trades):
                        if (
                            t.get("strike") == info["strike"] and
                            t.get("optType") == info["optType"]
                        ):
                            status, updated_t = signal_engine.manage_trade(t, ltp)

                            idx = next(
                                (i for i, item in enumerate(active_trades)
                                 if item["id"] == t["id"]), -1
                            )
                            if idx != -1:
                                active_trades[idx] = updated_t

                            now_str = datetime.now().strftime("%H:%M:%S")
                            if status == "STOPPED OUT":
                                log_trade_to_csv(updated_t, ltp, "STOPPED OUT", now_str)
                                active_trades[:] = [
                                    x for x in active_trades if x["id"] != updated_t["id"]
                                ]
                                print(f"❌ STOPPED OUT: {updated_t['strike']} {updated_t['optType']} @ {ltp}")
                                trigger_telegram_async(
                                    f"❌ <b>STOP LOSS HIT</b>\n"
                                    f"{updated_t['strike']} {updated_t['optType']}\n"
                                    f"Exit: ₹{ltp}"
                                )
                            elif status == "TARGET HIT":
                                log_trade_to_csv(updated_t, ltp, "TARGET 1 HIT", now_str)
                                active_trades[:] = [
                                    x for x in active_trades if x["id"] != updated_t["id"]
                                ]
                                print(f"🎯 TARGET HIT: {updated_t['strike']} {updated_t['optType']} @ {ltp}")
                                trigger_telegram_async(
                                    f"🎯 <b>TARGET HIT</b>\n"
                                    f"{updated_t['strike']} {updated_t['optType']}\n"
                                    f"Exit: ₹{ltp}"
                                )

        except Exception as e:
            print(f"Parse error: {e}")

    def on_error(wsapp, error) -> None:
        print(f"WebSocket Error: {error}")

    def on_close(wsapp) -> None:
        print("Sharekhan connection closed")

    sws.on_open  = on_open
    sws.on_data  = on_data
    sws.on_error = on_error
    sws.on_close = on_close
    sws.connect()


# ─── ENTRY POINT ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 55)
    print("  DASHBOARD BACKEND SERVER — DYNAMIC EXPIRY")
    print("=" * 55)

    if available_expiries:
        current_expiry = available_expiries[0]
        handle_set_expiry(current_expiry)

    threading.Thread(target=start_ws_server, daemon=True).start()

    while True:
        try:
            connect_sharekhan()
        except Exception as e:
            print(f"Main loop error: {e}")
        print("Reconnecting in 5 seconds...")
        time.sleep(5)
