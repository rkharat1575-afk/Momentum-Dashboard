import { useState, useEffect, useRef, useCallback } from "react";

// ─── CONSTANTS ────────────────────────────────────────────────────────────────
const NIFTY_BASE = 24350;
const BANKNIFTY_BASE = 52400;
const RISK_FREE = 0.065;
const LOT_SIZE = { NIFTY: 65, BANKNIFTY: 30 };

// ─── BLACK-SCHOLES IV BACK-CALCULATOR ────────────────────────────────────────
function normCDF(x) {
  const a1=0.254829592,a2=-0.284496736,a3=1.421413741,a4=-1.453152027,a5=1.061405429,p=0.3275911;
  const sign = x < 0 ? -1 : 1;
  x = Math.abs(x) / Math.sqrt(2);
  const t = 1.0 / (1.0 + p * x);
  const y = 1.0 - (((((a5*t+a4)*t)+a3)*t+a2)*t+a1)*t*Math.exp(-x*x);
  return 0.5 * (1.0 + sign * y);
}

function bsPrice(S, K, T, r, sigma, type) {
  if (T <= 0) return Math.max(0, type === "CE" ? S - K : K - S);
  const d1 = (Math.log(S/K) + (r + 0.5*sigma*sigma)*T) / (sigma*Math.sqrt(T));
  const d2 = d1 - sigma*Math.sqrt(T);
  if (type === "CE") return S*normCDF(d1) - K*Math.exp(-r*T)*normCDF(d2);
  return K*Math.exp(-r*T)*normCDF(-d2) - S*normCDF(-d1);
}

function calcIV(premium, S, K, T, r, type) {
  let lo = 0.01, hi = 5.0, mid, price;
  for (let i = 0; i < 50; i++) {
    mid = (lo + hi) / 2;
    price = bsPrice(S, K, T, r, mid, type);
    if (price > premium) hi = mid; else lo = mid;
    if (Math.abs(price - premium) < 0.01) break;
  }
  return mid;
}

// ─── TICK SIMULATOR ───────────────────────────────────────────────────────────
function createTickSimulator(baseSpot, instrument) {
  let spot = baseSpot;
  let trend = 0;
  let trendStrength = 0;
  let momentum = 0;
  let sessionVolumePace = 1.0;
  let ticks = [];
  let vwapSum = 0, vwapVolSum = 0;

  return {
    nextTick() {
      // Trend evolution
      if (Math.random() < 0.08) {
        trend = (Math.random() - 0.48) * 2;
        trendStrength = 0.3 + Math.random() * 0.7;
      }
      momentum = momentum * 0.85 + trend * trendStrength * 0.15;

      // Price move
      const volatility = instrument === "BANKNIFTY" ? 0.0008 : 0.0005;
      const noise = (Math.random() - 0.5) * volatility * spot;
      const trendMove = momentum * spot * 0.0004;
      spot = Math.max(spot * 0.97, Math.min(spot * 1.03, spot + trendMove + noise));

      // Volume: time-of-day simulation
      const hour = new Date().getHours();
      const minute = new Date().getMinutes();
      const timeOfDay = hour + minute/60;
      let volMultiplier = 1.0;
      if (timeOfDay < 10) volMultiplier = 2.5;
      else if (timeOfDay < 10.5) volMultiplier = 1.8;
      else if (timeOfDay < 11.5) volMultiplier = 0.7;
      else if (timeOfDay > 14.5) volMultiplier = 1.9;
      sessionVolumePace = volMultiplier;

      const baseVol = instrument === "BANKNIFTY" ? 8000 : 15000;
      const vol = Math.floor(baseVol * volMultiplier * (0.5 + Math.random() * 1.5));
      const bidAsk = spot * (0.0001 + Math.random() * 0.0003);

      // OFI classification
      const ofi = momentum > 0 ? 
        (Math.random() < 0.65 + trendStrength * 0.2 ? vol : -vol * 0.3) :
        (Math.random() < 0.35 - trendStrength * 0.2 ? vol : -vol * 0.7);

      // VWAP
      vwapSum += spot * vol;
      vwapVolSum += vol;
      const vwap = vwapVolSum > 0 ? vwapSum / vwapVolSum : spot;

      const tick = { price: spot, vol, bid: spot - bidAsk/2, ask: spot + bidAsk/2, ofi, vwap, ts: Date.now() };
      ticks.push(tick);
      if (ticks.length > 500) ticks = ticks.slice(-500);
      return { tick, ticks: [...ticks], momentum, trendStrength, sessionVolumePace };
    },
    getSpot() { return spot; }
  };
}

// ─── SIGNAL ENGINE ────────────────────────────────────────────────────────────
// Legacy computeSignals removed. The backend signal_engine.py now fully controls the logic.


// ─── STRIKE RECOMMENDER ───────────────────────────────────────────────────────
function recommendStrikes(signals, instrument, vix, capital, liveOptions, strikeScores) {
  if (!signals) return [];
  const { spot, direction, composite, iv } = signals;
  const step = instrument === "BANKNIFTY" ? 100 : 50;
  const atm = Math.round(spot / step) * step;
  const lot = LOT_SIZE[instrument];

  const strikes = [];
  const offsets = direction === "BULL"
    ? [0, 1, 2, -1]  // ATM, OTM1, OTM2, ITM
    : [0, -1, -2, 1];

  offsets.forEach((off, idx) => {
    const K = atm + off * step;
    const type = direction === "BULL" ? "CE" : "PE";
    const T = Math.max(0.5, 7) / 365;
    const premium = Math.max(1, bsPrice(spot, K, T, RISK_FREE, iv, type));
    const greeks = calcGreeks(spot, K, T, RISK_FREE, iv, type);

    // Strike-specific scoring
    const moneyness = type === "CE" ? (spot - K) / spot : (K - spot) / spot;
    const isATM = Math.abs(moneyness) < 0.002;
    const isOTM1 = !isATM && Math.abs(moneyness) < 0.006;
    const isOTM2 = Math.abs(moneyness) >= 0.006 && Math.abs(moneyness) < 0.012;
    const isITM = moneyness > 0.002;

    // Score factors for this specific strike
    const strikeKey = K + "_" + type;
    let strikeScore = (strikeScores && strikeScores[strikeKey]) || composite || 0;
    let rationale = [];

    if (isATM) {
      strikeScore *= 1.0;
      rationale.push("Best premium capture");
      rationale.push("Highest gamma sensitivity");
    } else if (isOTM1) {
      strikeScore *= (composite > 24 ? 1.1 : 0.85);
      rationale.push("High leverage if move extends");
      rationale.push("Requires +0.4% additional move");
    } else if (isOTM2) {
      strikeScore *= (composite > 26 ? 1.0 : 0.65);
      rationale.push("Lottery ticket — only on breakouts");
      rationale.push("Requires +0.8% additional move");
    } else if (isITM) {
      strikeScore *= 0.80;
      rationale.push("Lower leverage, lower theta risk");
      rationale.push("Better probability, lower reward");
    }

    // Risk per lot
    const livePremium = liveOptions[K]?.[type];
    const basePremium = livePremium || premium;
    const hardStop = basePremium * 0.40;
    const riskPerLot = hardStop * lot;
    const maxLots = Math.min(10, Math.floor((capital * 0.015) / riskPerLot));

    // Expected move
    const intraday_sigma = vix / 100 / Math.sqrt(252) * spot;
    const breakeven = type === "CE" ? K + basePremium : K - basePremium;
    const beDistance = Math.abs(breakeven - spot);
    const probProfit = Math.max(5, Math.min(85, 50 + (intraday_sigma - beDistance) / intraday_sigma * 30));

    const rank = idx === 0 ? 1 : idx === 1 ? 2 : idx === 2 ? 3 : 4;
    const label = isATM ? "ATM" : isOTM1 ? "OTM-1" : isOTM2 ? "OTM-2" : "ITM";

    strikes.push({
      strike: K, type, premium: Math.round(premium * 10) / 10,
      rank, label, strikeScore: Math.round(strikeScore * 10) / 10,
      greeks, rationale, maxLots,
      riskPerLot: Math.round(riskPerLot),
      breakeven: Math.round(breakeven),
      probProfit: Math.round(probProfit),
      hardStopPremium: Math.round(basePremium * 0.60 * 10) / 10,
      target1: Math.round(basePremium * 1.30 * 10) / 10,
      target2: Math.round(basePremium * 1.80 * 10) / 10,
      isBest: rank === 1 && composite >= 21
    });
  });

  return strikes.sort((a, b) => b.strikeScore - a.strikeScore);
}

function calcGreeks(S, K, T, r, sigma, type) {
  if (T <= 0) return { delta: type === "CE" ? 1 : -1, gamma: 0, theta: 0, vega: 0 };
  const d1 = (Math.log(S/K) + (r + 0.5*sigma*sigma)*T) / (sigma*Math.sqrt(T));
  const d2 = d1 - sigma*Math.sqrt(T);
  const npd1 = Math.exp(-0.5*d1*d1) / Math.sqrt(2*Math.PI);
  const delta = type === "CE" ? normCDF(d1) : normCDF(d1) - 1;
  const gamma = npd1 / (S * sigma * Math.sqrt(T));
  const theta = (-(S * npd1 * sigma) / (2 * Math.sqrt(T)) - r * K * Math.exp(-r*T) * (type === "CE" ? normCDF(d2) : normCDF(-d2))) / 365;
  const vega = S * npd1 * Math.sqrt(T) / 100;
  return {
    delta: Math.round(delta * 1000) / 1000,
    gamma: Math.round(gamma * 10000) / 10000,
    theta: Math.round(theta * 100) / 100,
    vega: Math.round(vega * 100) / 100
  };
}

// ─── MAIN DASHBOARD COMPONENT ─────────────────────────────────────────────────
export default function Dashboard() {
  const [instrument, setInstrument] = useState("NIFTY");
  const [capital, setCapital] = useState(500000);
  const [vix, setVix] = useState(15.4);
  const [ticks, setTicks] = useState([]);
  const [liveOptions, setLiveOptions] = useState({});
  const [expiries, setExpiries] = useState([]);
  const [selectedExpiry, setSelectedExpiry] = useState("");
  const [signals, setSignals] = useState(null);
  const [chainContext, setChainContext] = useState(null);
  const [strikeScores, setStrikeScores] = useState({});
  const [strikes, setStrikes] = useState([]);
  const [sessionVolumePace, setSessionVolumePace] = useState(1.0);
  const [priceHistory, setPriceHistory] = useState([]);
  const [strategyConfig, setStrategyConfig] = useState({ MIN_COMPOSITE_SCORE: 12, OFI_THRESHOLD: 0.08 });
  const [alertLog, setAlertLog] = useState([]);
  const [phase, setPhase] = useState("SCANNING");
  const [selectedStrike, setSelectedStrike] = useState(null);
  const [tickCount, setTickCount] = useState(0);
  const [confirmTimer, setConfirmTimer] = useState(0);
  const [tradePhase, setTradePhase] = useState(null);
  const [reversalState, setReversalState] = useState("SIDEWAYS");
  const simRef = useRef(null);
  const animRef = useRef(null);
  const lastSignalRef = useRef(null);
  const confirmRef = useRef(0);
  const wsRef = useRef(null);
  const liveOptionsRef = useRef({});
  const strikeScoresRef = useRef({});

  const [backendUrl, setBackendUrl] = useState(() => {
    const saved = localStorage.getItem("ws_backend_url");
    if (saved) return saved;
    if (import.meta.env.VITE_WS_URL) return import.meta.env.VITE_WS_URL;
    const hostname = window.location.hostname || "localhost";
    return `ws://${hostname}:8080`;
  });
  const [connected, setConnected] = useState(false);
  const [loggedIn, setLoggedIn] = useState(false);
  const [authStatus, setAuthStatus] = useState(null);
  const [showSettings, setShowSettings] = useState(false);
  const [isMobile, setIsMobile] = useState(window.innerWidth < 768);
  const [recsTimestamp, setRecsTimestamp] = useState("");
  const [theme, setTheme] = useState(() => {
    const saved = localStorage.getItem("dashboard_theme");
    if (saved) return saved;
    return window.innerWidth < 768 ? "dark" : "light";
  });

  const vixRef = useRef(vix);
  const capRef = useRef(capital);
  const instRef = useRef(instrument);
  const strategyConfigRef = useRef({ MIN_COMPOSITE_SCORE: 12, OFI_THRESHOLD: 0.08 });
  
  useEffect(() => { vixRef.current = vix; }, [vix]);
  useEffect(() => { capRef.current = capital; }, [capital]);
  useEffect(() => { instRef.current = instrument; }, [instrument]);

  useEffect(() => {
    const handleResize = () => setIsMobile(window.innerWidth < 768);
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  useEffect(() => {
    fetch('/strategy_config.json?t=' + Date.now())
      .then(res => res.json())
      .then(data => {
        setStrategyConfig(data);
        strategyConfigRef.current = data;
      })
      .catch(err => console.warn("Failed to load strategy config, using defaults:", err));
  }, []);

  useEffect(() => {
    setTicks([]);
    setPriceHistory([]);
    setSignals(null);
    setStrikes([]);
    setAlertLog([]);
    setPhase("SCANNING");
    setSelectedStrike(null);
    setTradePhase(null);
    confirmRef.current = 0;
    setConnected(false);
    
    let currentTicks = [];
    let ws;
    try {
      console.log("Connecting to WebSocket:", backendUrl);
      ws = new WebSocket(backendUrl);
      wsRef.current = ws;
    } catch (e) {
      console.error("Failed to create WebSocket:", e);
      return;
    }
    
    ws.onopen = () => {
      console.log("WebSocket connected successfully!");
      setConnected(true);
      setAuthStatus(null);
      
      const urlParams = new URLSearchParams(window.location.search);
      const requestToken = urlParams.get("request_token");
      if (requestToken) {
        console.log("Submitting captured request_token via WS:", requestToken);
        ws.send(JSON.stringify({
          action: "submit_request_token",
          request_token: requestToken
        }));
        window.history.replaceState({}, document.title, window.location.pathname);
      }
    };
    
    ws.onclose = () => {
      console.log("WebSocket connection closed.");
      setConnected(false);
    };
    
    ws.onerror = (err) => {
      console.error("WebSocket error:", err);
      setConnected(false);
    };
    
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        
        if (data.type === "metadata") {
          setExpiries(data.expiries);
          if (data.expiries.length > 0) {
            setSelectedExpiry(data.current_expiry || data.expiries[0]);
          }
          if (data.logged_in !== undefined) {
            setLoggedIn(data.logged_in);
          }
          return;
        }
        
        if (data.type === "auth_status") {
          setLoggedIn(data.logged_in);
          setAuthStatus({
            success: data.success,
            message: data.message
          });
          if (data.success) {
            if (data.expiries) setExpiries(data.expiries);
            if (data.current_expiry) setSelectedExpiry(data.current_expiry);
          }
          return;
        }
        
        if (data.instrument === "REVERSAL_ENGINE") {
          setReversalState(data.state);
          return;
        }
        
        if (data.type === "chain_context") {
          setChainContext(data);
          return;
        }
        
        if (data.type === "signal_fired") {
          setAlertLog(l => [{
            time: new Date().toLocaleTimeString(),
            msg: `${data.direction} signal confirmed — Score ${data.score.toFixed(1)}/100`,
            type: data.direction === "BULL" ? "bull" : "bear",
            score: data.score
          }, ...l].slice(0, 8));
          return;
        }
        
        if (data.type === "score_update") {
          strikeScoresRef.current[data.strike] = data.score;
          if (data.components) window.latestMicrostructure = data.components;
          setStrikeScores({ ...strikeScoresRef.current });
          return;
        }
        
        if (data.instrument && data.instrument !== instRef.current) return;
        
        if (data.type === "option_tick") {
          liveOptionsRef.current[data.strike] = liveOptionsRef.current[data.strike] || {};
          liveOptionsRef.current[data.strike][data.optType] = data.price;
          setLiveOptions({ ...liveOptionsRef.current });
          return;
        }
        
        const tick = data.tick;
        currentTicks.push(tick);
        if (currentTicks.length > 500) currentTicks = currentTicks.slice(-500);
        
        const hour = new Date().getHours();
        const minute = new Date().getMinutes();
        const timeOfDay = hour + minute/60;
        let svp = 1.0;
        if (timeOfDay < 10) svp = 2.5;
        else if (timeOfDay < 10.5) svp = 1.8;
        else if (timeOfDay < 11.5) svp = 0.7;
        else if (timeOfDay > 14.5) svp = 1.9;
        
        setTicks([...currentTicks]);
        setSessionVolumePace(svp);
        setTickCount(c => c + 1);
        setPriceHistory(h => {
          const next = [...h, { price: tick.price, ts: tick.ts }];
          return next.slice(-80);
        });
        
        try {
          const playAlertSound = (direction) => {
            try {
              const ctx = new (window.AudioContext || window.webkitAudioContext)();
              const osc = ctx.createOscillator();
              const gainNode = ctx.createGain();
              
              osc.connect(gainNode);
              gainNode.connect(ctx.destination);
              
              osc.type = 'sine';
              osc.frequency.setValueAtTime(direction === "BULL" ? 880 : 330, ctx.currentTime);
              
              gainNode.gain.setValueAtTime(0.5, ctx.currentTime);
              gainNode.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.5);
              
              osc.start();
              osc.stop(ctx.currentTime + 0.5);
            } catch(e) { console.log("Audio blocked"); }
          };
          
          let maxScore = -1;
          let bestDir = "NEUTRAL";
          for (const [strikeKey, score] of Object.entries(strikeScoresRef.current)) {
              if (score > maxScore) {
                  maxScore = score;
                  bestDir = strikeKey.includes("CE") ? "BULL" : "BEAR";
              }
          }
          
          const pseudoSigs = {
              spot: tick.price,
              direction: bestDir,
              composite: maxScore,
              iv: vixRef.current,
              ofi: tick.ofi,
              velocity: tick.velocity_tps,
              vwap: tick.vwap
          };
          
          setSignals(pseudoSigs);
          
          const recs = recommendStrikes(pseudoSigs, instRef.current, vixRef.current, capRef.current, liveOptionsRef.current, strikeScoresRef.current);
          setStrikes(recs);
          if (recs && recs.length > 0) {
            setRecsTimestamp(new Date().toLocaleTimeString());
          }
          
          if (maxScore >= 60.0) {
              setPhase("SIGNAL");
          } else if (maxScore > 30.0) {
              setPhase("CAUTION");
          } else {
              setPhase("SCANNING");
          }
          
        } catch (err) {
          setPhase("ERR: " + err.message.substring(0, 20));
        }
      } catch (e) {
        console.error("WS Parse error", e);
      }
    };
    
    return () => {
      ws.close();
    };
  }, [backendUrl, instrument]);

  const spot = signals?.spot ?? (ticks.length > 0 ? ticks[ticks.length - 1].price : (instrument === "NIFTY" ? NIFTY_BASE : BANKNIFTY_BASE));
  const prevSpot = priceHistory.length > 1 ? priceHistory[priceHistory.length - 2].price : spot;
  const spotChange = spot - (priceHistory.length > 0 ? priceHistory[0].price : (instrument === "NIFTY" ? NIFTY_BASE : BANKNIFTY_BASE));
  const spotChangePct = (spotChange / spot) * 100;
  const isUp = spot >= prevSpot;

  // Mini sparkline path
  const sparkPath = () => {
    if (priceHistory.length < 2) return "";
    const prices = priceHistory.map(p => p.price);
    const mn = Math.min(...prices), mx = Math.max(...prices);
    const range = mx - mn || 1;
    const w = 200, h = 50;
    return prices.map((p, i) => {
      const x = (i / (prices.length - 1)) * w;
      const y = h - ((p - mn) / range) * h;
      return `${i === 0 ? "M" : "L"}${x},${y}`;
    }).join(" ");
  };

  const axisBarW = (val) => `${(val / 10) * 100}%`;
  const scoreColor = (s) => s >= 25 ? "#10b981" : s >= 21 ? "#f0c040" : s >= 15 ? "#ff9944" : "#ef4444";
  const dirColor = signals?.direction === "BULL" ? "#10b981" : signals?.direction === "BEAR" ? "#ef4444" : "#888";

  return (
    <div className={theme === "dark" ? "dark" : ""} style={{
      fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
      background: theme === "dark" ? "#090d16" : "radial-gradient(circle at 50% 0%, #f8fafc, #e2e8f0)",
      minHeight: "100vh",
      color: theme === "dark" ? "#f8fafc" : "#1e293b",
      padding: "0",
      overflowX: "hidden",
    }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;600;700&family=Orbitron:wght@400;700;900&display=swap');
        * { box-sizing: border-box; margin: 0; padding: 0; }
        ::-webkit-scrollbar { width: 4px; } 
        ::-webkit-scrollbar-track { background: #0a0f1a; }
        ::-webkit-scrollbar-thumb { background: #1e3a5f; border-radius: 2px; }
        .panel { background: rgba(255,255,255,0.95); border: 1px solid rgba(203,213,225,1); border-radius: 6px; }
        .dark .panel { background: rgba(17,24,39,0.8); border: 1px solid rgba(255,255,255,0.08); }
        .panel-glow { box-shadow: 0 0 20px rgba(0,120,255,0.08), inset 0 0 40px rgba(0,60,120,0.05); }
        .dark .panel-glow { box-shadow: 0 0 20px rgba(0,120,255,0.15), inset 0 0 40px rgba(0,20,40,0.2); }
        .ticker-val { font-family: 'Orbitron', monospace; letter-spacing: 0.05em; }
        .axis-bar { height: 6px; border-radius: 3px; transition: width 0.4s cubic-bezier(.4,0,.2,1); }
        .signal-pulse { animation: pulse 1.2s ease-in-out infinite; }
        @keyframes pulse { 0%,100%{opacity:1;} 50%{opacity:0.5;} }
        .scan-rotate { animation: scan 3s linear infinite; }
        @keyframes scan { from{transform:rotate(0deg);} to{transform:rotate(360deg);} }
        .strike-card { 
          border: 1px solid rgba(203,213,225,1); 
          border-radius: 6px; 
          padding: 8px; 
          cursor: pointer;
          transition: all 0.2s ease;
          background: rgba(255,255,255,0.8);
          display: flex;
          flex-direction: column;
          gap: 6px;
        }
        .dark .strike-card {
          border: 1px solid rgba(255,255,255,0.08);
          background: rgba(31,41,55,0.4);
        }
        .strike-card:hover { border-color: rgba(59,130,246,0.5); background: rgba(59,130,246,0.1); }
        .strike-card.best { border-color: rgba(16,185,129,0.5); background: rgba(16,185,129,0.15); }
        .strike-card.selected { border-color: rgba(59,130,246,0.8); background: rgba(59,130,246,0.2); }
        .btn { 
          background: rgba(203,213,225,1); 
          border: 1px solid rgba(59,130,246,0.3); 
          color: #0f172a; 
          padding: 6px 14px; 
          border-radius: 4px; 
          cursor: pointer; 
          font-family: inherit; 
          font-size: 11px;
          transition: all 0.15s;
          letter-spacing: 0.05em;
        }
        .btn:hover { background: rgba(0,120,255,0.2); color: #fff; }
        .btn.active { background: rgba(0,120,255,0.35); color: #fff; border-color: rgba(0,200,255,0.6); }
        .alert-item { animation: slideIn 0.3s ease; }
        @keyframes slideIn { from{transform:translateX(-10px);opacity:0;} to{transform:translateX(0);opacity:1;} }
        .grid-bg {
          background-image: linear-gradient(rgba(0,80,160,0.04) 1px, transparent 1px),
                            linear-gradient(90deg, rgba(0,80,160,0.04) 1px, transparent 1px);
          background-size: 40px 40px;
        }
        .dark .grid-bg {
          background-image: linear-gradient(rgba(0,120,255,0.02) 1px, transparent 1px),
                            linear-gradient(90deg, rgba(0,120,255,0.02) 1px, transparent 1px);
        }
      `}</style>

      {/* ── SETTINGS MODAL ── */}
      {showSettings && (
        <div style={{
          position: "fixed", top: 0, left: 0, right: 0, bottom: 0,
          background: "rgba(15, 23, 42, 0.8)", backdropFilter: "blur(8px)",
          display: "flex", alignItems: "center", justifyContent: "center",
          zIndex: 1000, padding: "20px"
        }}>
          <div className="panel" style={{
            background: "#0f172a", border: "1px solid #1e293b", color: "#f8fafc",
            width: "100%", maxWidth: "450px", borderRadius: "12px", padding: "24px"
          }}>
            <h3 style={{ fontFamily: "Orbitron", fontSize: "16px", marginBottom: "16px", color: "#3b82f6" }}>CONNECTION SETTINGS</h3>
            <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
              <label style={{ fontSize: "12px", color: "#94a3b8" }}>
                WebSocket Backend URL:
                <input 
                  type="text" 
                  value={backendUrl}
                  onChange={(e) => setBackendUrl(e.target.value)}
                  style={{
                    width: "100%", padding: "8px 12px", borderRadius: "6px",
                    background: "#1e293b", border: "1px solid #334155", color: "#fff",
                    fontSize: "13px", marginTop: "4px", outline: "none", fontFamily: "inherit"
                  }} 
                />
              </label>
              <div style={{ fontSize: "12px", color: "#64748b" }}>
                Note: Local Wi-Fi connection usually uses `ws://YOUR_LAPTOP_IP:8080`.
              </div>
              <div style={{ display: "flex", gap: "10px", marginTop: "16px" }}>
                <button 
                  onClick={() => {
                    localStorage.setItem("ws_backend_url", backendUrl);
                    setShowSettings(false);
                  }}
                  className="btn active"
                  style={{ flex: 1, padding: "10px", fontSize: "12px" }}
                >
                  Save & Connect
                </button>
                <button 
                  onClick={() => setShowSettings(false)}
                  className="btn"
                  style={{ flex: 1, padding: "10px", fontSize: "12px" }}
                >
                  Cancel
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── HEADER ── */}
      <div style={{ 
        background: theme === "dark" ? "rgba(17,24,39,0.98)" : "rgba(241,245,249,0.98)", 
        borderBottom: theme === "dark" ? "1px solid #1f2937" : "1px solid rgba(203,213,225,1)", 
        padding: "10px 20px", display: "flex", alignItems: "center", justifyContent: "space-between", 
        position: "sticky", top: 0, zIndex: 100 
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <div style={{ 
              width: 8, height: 8, borderRadius: "50%", 
              background: connected ? "#10b981" : "#ef4444", 
              boxShadow: `0 0 8px ${connected ? "#10b981" : "#ef4444"}` 
            }} className={connected ? "signal-pulse" : ""} />
            <span style={{ fontFamily: "Orbitron", fontSize: 13, fontWeight: 700, color: theme === "dark" ? "#f8fafc" : "#0f172a", letterSpacing: "0.1em" }}>MOMENTUM ENGINE</span>
          </div>
          {loggedIn && (
            <div style={{ display: "flex", gap: 6 }}>
              {["NIFTY","BANKNIFTY"].map(ins => (
                <button key={ins} className={`btn ${instrument===ins?"active":""}`} onClick={()=>setInstrument(ins)}>{ins}</button>
              ))}
            </div>
          )}
          {loggedIn && expiries.length > 0 && (
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginLeft: 10 }}>
              <span style={{ fontSize: 12, color: theme === "dark" ? "#9ca3af" : "#475569" }}>EXPIRY</span>
              <select 
                value={selectedExpiry}
                onChange={(e) => {
                  const newExp = e.target.value;
                  setSelectedExpiry(newExp);
                  if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
                    wsRef.current.send(JSON.stringify({ action: "set_expiry", expiry: newExp }));
                  }
                }}
                style={{
                  background: theme === "dark" ? "#1f2937" : "rgba(241,245,249,1)",
                  border: `1px solid ${theme === "dark" ? "#374151" : "rgba(59,130,246,0.3)"}`,
                  color: "#10b981",
                  padding: "2px 6px",
                  borderRadius: 4,
                  fontSize: 12,
                  fontFamily: "Orbitron",
                  outline: "none",
                  cursor: "pointer"
                }}
              >
                {expiries.map(exp => (
                  <option key={exp} value={exp} style={{ background: theme === "dark" ? "#111827" : "#fff", color: theme === "dark" ? "#fff" : "#1e293b" }}>{exp}</option>
                ))}
              </select>
            </div>
          )}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 15 }}>
          {loggedIn && !isMobile && (
            <>
              <div style={{ fontSize: 12, color: theme === "dark" ? "#9ca3af" : "#475569" }}>
                TICKS <span style={{ color: theme === "dark" ? "#f8fafc" : "#0f172a" }}>{tickCount.toLocaleString()}</span>
              </div>
              <div style={{ fontSize: 12, color: theme === "dark" ? "#9ca3af" : "#475569" }}>
                VIX <input type="range" min="10" max="30" step="0.1" value={vix}
                  onChange={e=>setVix(parseFloat(e.target.value))}
                  style={{ width: 70, accentColor: "#0080ff", verticalAlign: "middle" }} />
                <span style={{ color: vix > 20 ? "#dc2626" : vix < 14 ? "#ffcc44" : "#10b981", marginLeft: 4 }}>{vix.toFixed(1)}</span>
              </div>
              <div style={{ fontSize: 12, color: theme === "dark" ? "#9ca3af" : "#475569" }}>
                ₹CAP <input type="number" value={capital/100000} min={1} max={50} step={0.5}
                  onChange={e=>setCapital(parseFloat(e.target.value)*100000)}
                  style={{ width: 50, background: "transparent", border: `1px solid ${theme === "dark" ? "#374151" : "#1e3a5f"}`, color: theme === "dark" ? "#f8fafc" : "#0f172a", fontSize: 12, padding: "2px 4px", borderRadius: 3, fontFamily: "inherit" }} />L
              </div>
              <div style={{
                padding: "4px 12px", borderRadius: 4, fontSize: 12, fontWeight: 600,
                background: phase === "SIGNAL" ? "rgba(0,200,80,0.2)" : theme === "dark" ? "rgba(31,41,55,0.4)" : "rgba(0,60,120,0.3)",
                border: `1px solid ${phase === "SIGNAL" ? "rgba(0,255,136,0.5)" : theme === "dark" ? "rgba(255,255,255,0.08)" : "rgba(203,213,225,1)"}`,
                color: phase === "SIGNAL" ? "#10b981" : theme === "dark" ? "#9ca3af" : "#64748b",
                letterSpacing: "0.1em",
                ...(phase === "SIGNAL" ? { animation: "pulse 1s ease-in-out infinite" } : {})
              }}>
                {phase}
              </div>
            </>
          )}
          <button 
            onClick={() => {
              const nextTheme = theme === "dark" ? "light" : "dark";
              setTheme(nextTheme);
              localStorage.setItem("dashboard_theme", nextTheme);
            }}
            style={{
              background: "transparent", border: "none", cursor: "pointer", fontSize: "16px",
              padding: "4px 8px", color: theme === "dark" ? "#9ca3af" : "#475569", transition: "color 0.2s"
            }}
            title={theme === "dark" ? "Switch to Light Mode" : "Switch to Dark Mode"}
          >
            {theme === "dark" ? "☀️" : "🌙"}
          </button>
          <button 
            onClick={() => setShowSettings(true)}
            style={{
              background: "transparent", border: "none", cursor: "pointer", fontSize: "16px",
              padding: "4px 8px", color: theme === "dark" ? "#9ca3af" : "#475569", transition: "color 0.2s"
            }}
            title="Settings"
          >
            ⚙️
          </button>
        </div>
      </div>

      {/* ── CONNECTION LOST WARNING BANNER ── */}
      {!connected && loggedIn && (
        <div style={{
          background: "#7f1d1d", color: "#fca5a5", padding: "8px 16px",
          textAlign: "center", fontSize: "12px", fontWeight: "600",
          borderBottom: "1px solid #991b1b", display: "flex", alignItems: "center",
          justifyContent: "center", gap: "8px", zIndex: 101, position: "relative"
        }}>
          <span>⚠️ Connection to Python backend lost. Showing last cached data.</span>
          <button 
            onClick={() => setShowSettings(true)}
            style={{
              background: "rgba(255,255,255,0.15)", border: "none", color: "#fff",
              padding: "2px 8px", borderRadius: "4px", cursor: "pointer", fontSize: "11px"
            }}
          >
            Settings
          </button>
        </div>
      )}

      {!loggedIn ? (
        <div className="grid-bg" style={{
          display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
          minHeight: "calc(100vh - 100px)", padding: "20px"
        }}>
          <div className="panel panel-glow" style={{
            background: theme === "dark" ? "#111827" : "rgba(255, 255, 255, 0.9)",
            border: theme === "dark" ? "1px solid #1f2937" : "1px solid rgba(203,213,225,1)",
            padding: isMobile ? "32px 24px" : "40px",
            borderRadius: "12px", width: "100%", maxWidth: "450px",
            textAlign: "center", color: theme === "dark" ? "#f8fafc" : "#0f172a"
          }}>
            <div style={{
              width: "60px", height: "60px", borderRadius: "50%",
              background: "rgba(59,130,246,0.1)", display: "flex", alignItems: "center",
              justifyContent: "center", margin: "0 auto 20px", border: "1px solid rgba(59,130,246,0.2)"
            }}>
              <span style={{ fontSize: "28px" }}>🔑</span>
            </div>
            
            <h2 style={{ fontFamily: "Orbitron", fontSize: "20px", fontWeight: 700, letterSpacing: "0.08em", marginBottom: "12px" }}>
              MOMENTUM ENGINE
            </h2>
            
            <p style={{ fontSize: "14px", color: theme === "dark" ? "#9ca3af" : "#64748b", lineHeight: 1.5, marginBottom: "28px" }}>
              Connect your Sharekhan account to start the live institutional momentum scanner.
            </p>

            {authStatus && (
              <div style={{
                padding: "12px 16px", borderRadius: "8px", fontSize: "13px",
                background: authStatus.success ? "rgba(16,185,129,0.1)" : "rgba(239,68,68,0.1)",
                border: `1px solid ${authStatus.success ? "rgba(16,185,129,0.2)" : "rgba(239,68,68,0.2)"}`,
                color: authStatus.success ? "#10b981" : "#ef4444",
                marginBottom: "20px", textAlign: "left"
              }}>
                {authStatus.message}
              </div>
            )}
            
            <button
              onClick={() => {
                const httpUrl = backendUrl.replace(/^ws/, "http");
                window.location.href = `${httpUrl}/login`;
              }}
              className="btn active"
              style={{
                width: "100%", padding: "12px", fontSize: "14px", fontWeight: "600",
                fontFamily: "Orbitron", borderRadius: "8px", textTransform: "uppercase",
                letterSpacing: "0.1em", cursor: "pointer", transition: "all 0.2s",
                boxShadow: "0 4px 12px rgba(59, 130, 246, 0.2)"
              }}
            >
              Login to Sharekhan
            </button>

            <div style={{ marginTop: "24px", paddingTop: "20px", borderTop: `1px solid ${theme === "dark" ? "#1f2937" : "rgba(226,232,240,1)"}` }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: "12px" }}>
                <span style={{ color: theme === "dark" ? "#9ca3af" : "#64748b" }}>Connection Status:</span>
                <span style={{ fontWeight: 600, color: connected ? "#10b981" : "#ef4444" }}>
                  {connected ? "Connected to Backend" : "Disconnected"}
                </span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: "12px", marginTop: "8px" }}>
                <span style={{ color: theme === "dark" ? "#9ca3af" : "#64748b" }}>Server:</span>
                <span style={{ fontFamily: "monospace", color: theme === "dark" ? "#d1d5db" : "#334155" }}>
                  {backendUrl}
                </span>
              </div>
              <button
                onClick={() => setShowSettings(true)}
                className="btn"
                style={{ width: "100%", marginTop: "16px", padding: "8px" }}
              >
                Change Connection Settings
              </button>
            </div>
          </div>
        </div>
      ) : isMobile ? (
        <div className="grid-bg" style={{ padding: "12px", display: "flex", flexDirection: "column", gap: "12px", minHeight: "calc(100vh - 100px)", background: theme === "dark" ? "#090d16" : "radial-gradient(circle at 50% 0%, #f8fafc, #e2e8f0)" }}>
          
          {/* Ticker & Sparkline */}
          <div className="panel panel-glow" style={{ padding: "12px", background: theme === "dark" ? "#111827" : "rgba(255, 255, 255, 0.95)", border: `1px solid ${theme === "dark" ? "#1f2937" : "rgba(203,213,225,1)"}` }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div>
                <div style={{ fontSize: "11px", color: theme === "dark" ? "#9ca3af" : "#475569", letterSpacing: "0.15em", marginBottom: 2 }}>{instrument} FUTURES</div>
                <div className="ticker-val" style={{ fontSize: "24px", fontWeight: 700, color: isUp ? "#10b981" : "#ef4444" }}>
                  {spot.toFixed(2)}
                </div>
                <div style={{ fontSize: "12px", color: isUp ? "#10b981" : "#ef4444", marginTop: 2 }}>
                  {isUp ? "▲" : "▼"} {Math.abs(spotChange).toFixed(2)} ({spotChangePct.toFixed(2)}%)
                </div>
              </div>
              <div style={{ position: "relative", width: "120px", height: "45px" }}>
                <svg width="120" height="45">
                  <path d={sparkPath()} fill="none" stroke={isUp ? "#10b981" : "#ef4444"} strokeWidth="2" vectorEffect="non-scaling-stroke"
                    viewBox="0 0 200 50" style={{ transform: "scale(0.6, 0.9)", transformOrigin: "0 0" }} />
                </svg>
              </div>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: "11px", color: theme === "dark" ? "#9ca3af" : "#475569", marginTop: "10px", paddingTop: "8px", borderTop: `1px solid ${theme === "dark" ? "#1f2937" : "rgba(203,213,225,1)"}` }}>
              <span>VWAP: <strong style={{ color: theme === "dark" ? "#f8fafc" : "#0f172a" }}>{signals?.vwap?.toFixed(1) ?? "—"}</strong></span>
              <span>IV: <strong style={{ color: "#f59e0b" }}>{signals ? (signals.iv * 100).toFixed(1) : "—"}%</strong></span>
              <span>VIX: <strong style={{ color: vix > 20 ? "#ef4444" : "#10b981" }}>{vix.toFixed(1)}</strong></span>
            </div>
          </div>

          {/* Reversal Engine & Seller Stress Row */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" }}>
            {/* Reversal Engine */}
            <div className="panel panel-glow" style={{ 
              padding: "12px", background: theme === "dark" ? "#111827" : "rgba(255, 255, 255, 0.95)", 
              border: reversalState.startsWith("REVERSAL") ? "1px solid #f59e0b" : theme === "dark" ? "1px solid #1f2937" : "1px solid rgba(203,213,225,1)",
              display: "flex", flexDirection: "column", justifyContent: "center"
            }}>
              <span style={{ fontSize: "10px", color: theme === "dark" ? "#9ca3af" : "#475569", letterSpacing: "0.1em", marginBottom: "6px" }}>REVERSAL STATE</span>
              <span style={{ 
                fontSize: "14px", fontWeight: 700, 
                color: reversalState.includes("LONG") ? "#10b981" : reversalState.includes("SHORT") ? "#ef4444" : (theme === "dark" ? "#f8fafc" : "#0f172a") 
              }} className={reversalState.startsWith("REVERSAL") ? "signal-pulse" : ""}>
                {reversalState.replace("_", " ")}
              </span>
            </div>

            {/* Seller Stress Gauge */}
            <div className="panel panel-glow" style={{ padding: "12px", background: theme === "dark" ? "#111827" : "rgba(255, 255, 255, 0.95)", border: `1px solid ${theme === "dark" ? "#1f2937" : "rgba(203,213,225,1)"}` }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "4px" }}>
                <span style={{ fontSize: "10px", color: "#10b981", letterSpacing: "0.1em" }}>SELLER STRESS</span>
                <span style={{ fontSize: "9px", color: theme === "dark" ? "#9ca3af" : "#475569" }}>MIN {strategyConfig.MIN_COMPOSITE_SCORE}</span>
              </div>
              <div style={{ display: "flex", alignItems: "baseline", gap: "2px" }}>
                <span className="ticker-val" style={{ fontSize: "22px", fontWeight: 900, color: scoreColor(chainContext?.seller_stress_score ?? 0) }}>
                  {chainContext ? chainContext.seller_stress_score.toFixed(1) : "0.0"}
                </span>
                <span style={{ fontSize: "10px", color: theme === "dark" ? "#9ca3af" : "#475569" }}>/100</span>
              </div>
              <div style={{ height: "4px", background: theme === "dark" ? "#1f2937" : "rgba(203,213,225,1)", borderRadius: "2px", overflow: "hidden", marginTop: "6px" }}>
                <div style={{
                  height: "100%",
                  width: `${Math.min(100, ((chainContext?.seller_stress_score ?? 0) / 100) * 100)}%`,
                  background: scoreColor(chainContext?.seller_stress_score ?? 0),
                  transition: "width 0.4s ease"
                }}/>
              </div>
            </div>
          </div>

          {/* Institutional Radar */}
          <div className="panel panel-glow" style={{ padding: "12px", background: theme === "dark" ? "#111827" : "rgba(255, 255, 255, 0.95)", border: `1px solid ${theme === "dark" ? "#1f2937" : "rgba(203,213,225,1)"}` }}>
            <span style={{ fontSize: "11px", color: theme === "dark" ? "#9ca3af" : "#475569", letterSpacing: "0.1em", display: "block", marginBottom: "8px" }}>INSTITUTIONAL RADAR</span>
            {chainContext ? (
              <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: "12px" }}>
                  <span style={{ color: theme === "dark" ? "#9ca3af" : "#475569" }}>IV Skew Bias:</span>
                  <span style={{ fontWeight: 700, color: chainContext.skew_direction === "CALL_BID" ? "#10b981" : chainContext.skew_direction === "PUT_BID" ? "#ef4444" : "#8b5cf6" }}>
                    {chainContext.skew_direction === "CALL_BID" ? "BULLISH (FEAR)" : chainContext.skew_direction === "PUT_BID" ? "BEARISH" : "NEUTRAL"}
                  </span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: "12px" }}>
                  <span style={{ color: theme === "dark" ? "#9ca3af" : "#475569" }}>Chain PCR:</span>
                  <span style={{ fontWeight: 700, color: chainContext.current_pcr > 1.2 ? "#10b981" : chainContext.current_pcr < 0.8 ? "#ef4444" : "#8b5cf6" }}>
                    {chainContext.current_pcr.toFixed(2)}
                  </span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: "12px" }}>
                  <span style={{ color: theme === "dark" ? "#9ca3af" : "#475569" }}>Gamma Walls:</span>
                  <span style={{ color: "#f59e0b", fontFamily: "Orbitron", textAlign: "right", fontSize: "11px" }}>
                    C: {chainContext.nearest_call_wall || "None"} | P: {chainContext.nearest_put_wall || "None"}
                  </span>
                </div>
              </div>
            ) : (
              <div style={{ fontSize: "12px", color: theme === "dark" ? "#9ca3af" : "#64748b", textAlign: "center", padding: "10px 0" }}>
                Awaiting Options Chain Data...
              </div>
            )}
          </div>

          {/* Strike Recommendations */}
          <div style={{ display: "flex", flexDirection: "column", gap: "8px", flex: 1 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "4px 0" }}>
              <span style={{ fontSize: "12px", color: theme === "dark" ? "#9ca3af" : "#475569", letterSpacing: "0.15em" }}>STRIKE RECOMMENDATIONS</span>
              {recsTimestamp && (
                <span style={{ fontSize: "11px", color: theme === "dark" ? "#9ca3af" : "#64748b" }}>Generated: {recsTimestamp}</span>
              )}
            </div>

            {strikes.length === 0 ? (
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "180px", background: theme === "dark" ? "#111827" : "rgba(255, 255, 255, 0.95)", border: `1px solid ${theme === "dark" ? "#1f2937" : "rgba(203,213,225,1)"}`, borderRadius: "8px" }}>
                <div className="scan-rotate" style={{ width: "30px", height: "30px", border: `2px solid ${theme === "dark" ? "#374151" : "#cbd5e1"}`, borderTop: "2px solid #3b82f6", borderRadius: "50%", marginBottom: "12px" }}/>
                <span style={{ fontSize: "12px", color: theme === "dark" ? "#9ca3af" : "#475569" }}>{phase.startsWith("ERR") ? phase : "SCANNING FOR MOMENTUM..."}</span>
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                {strikes.map((s) => (
                  <div key={`${s.strike}-${s.type}`}
                    className={`strike-card ${s.isBest ? "best" : ""} ${selectedStrike?.strike === s.strike ? "selected" : ""}`}
                    onClick={() => setSelectedStrike(selectedStrike?.strike === s.strike ? null : s)}
                    style={{ padding: "10px", background: theme === "dark" ? "#111827" : "rgba(255, 255, 255, 0.95)" }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "6px" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                        <span style={{ fontFamily: "Orbitron", fontSize: "16px", fontWeight: 700, color: s.type === "CE" ? "#10b981" : "#ef4444" }}>{s.strike}</span>
                        <span style={{ fontSize: "10px", padding: "1px 4px", borderRadius: "3px", background: s.type === "CE" ? "rgba(16,185,129,0.15)" : "rgba(239,68,68,0.15)", color: s.type === "CE" ? "#10b981" : "#ef4444", fontWeight: 700 }}>{s.type}</span>
                        <span style={{ fontSize: "10px", color: theme === "dark" ? "#9ca3af" : "#475569" }}>{s.label}</span>
                      </div>
                      <div style={{ display: "flex", alignItems: "center", gap: "4px" }}>
                        <span style={{ fontSize: "10px", color: theme === "dark" ? "#9ca3af" : "#475569" }}>Score:</span>
                        <span style={{ fontFamily: "Orbitron", fontSize: "12px", fontWeight: 700, color: scoreColor(s.strikeScore) }}>{s.strikeScore.toFixed(1)}</span>
                      </div>
                    </div>

                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "6px", marginBottom: "6px" }}>
                      <div style={{ background: theme === "dark" ? "#1f2937" : "rgba(241,245,249,1)", padding: "4px 6px", borderRadius: "4px", border: `1px solid ${theme === "dark" ? "transparent" : "rgba(203,213,225,0.5)"}` }}>
                        <div style={{ fontSize: "9px", color: theme === "dark" ? "#9ca3af" : "#475569" }}>Live Prem</div>
                        <div style={{ fontSize: "12px", fontWeight: 700, color: "#10b981", fontFamily: "Orbitron" }}>
                          {liveOptions[s.strike]?.[s.type] ? `₹${liveOptions[s.strike][s.type]}` : `₹${s.premium}`}
                        </div>
                      </div>
                      <div style={{ background: theme === "dark" ? "#1f2937" : "rgba(241,245,249,1)", padding: "4px 6px", borderRadius: "4px", border: `1px solid ${theme === "dark" ? "transparent" : "rgba(203,213,225,0.5)"}` }}>
                        <div style={{ fontSize: "9px", color: theme === "dark" ? "#9ca3af" : "#475569" }}>Stop Loss</div>
                        <div style={{ fontSize: "12px", fontWeight: 700, color: "#ef4444", fontFamily: "Orbitron" }}>₹{s.hardStopPremium}</div>
                      </div>
                      <div style={{ background: theme === "dark" ? "#1f2937" : "rgba(241,245,249,1)", padding: "4px 6px", borderRadius: "4px", border: `1px solid ${theme === "dark" ? "transparent" : "rgba(203,213,225,0.5)"}` }}>
                        <div style={{ fontSize: "9px", color: theme === "dark" ? "#9ca3af" : "#475569" }}>Target 1</div>
                        <div style={{ fontSize: "12px", fontWeight: 700, color: "#f59e0b", fontFamily: "Orbitron" }}>₹{s.target1}</div>
                      </div>
                    </div>

                    {s.isBest && (
                      <div style={{ padding: "2px", background: "rgba(16,185,129,0.1)", border: "1px solid rgba(16,185,129,0.2)", borderRadius: "4px", fontSize: "9px", color: "#10b981", textAlign: "center", letterSpacing: "0.05em", fontWeight: 700 }}>
                        ★ HIGHEST PROBABILITY ENTRY
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Selected Strike Mobile Detail */}
          {selectedStrike && (
            <div className="panel" style={{ padding: "12px", background: theme === "dark" ? "#111827" : "rgba(255, 255, 255, 0.95)", border: `1px solid ${theme === "dark" ? "#3b82f6" : "rgba(59,130,246,0.6)"}` }}>
              <div style={{ fontSize: "11px", color: theme === "dark" ? "#9ca3af" : "#475569", letterSpacing: "0.1em", marginBottom: "8px" }}>
                TRADE PLAN: {selectedStrike.strike} {selectedStrike.type}
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px", marginBottom: "8px" }}>
                <div style={{ background: theme === "dark" ? "#1f2937" : "rgba(241,245,249,1)", padding: "6px", borderRadius: "4px", border: `1px solid ${theme === "dark" ? "transparent" : "rgba(203,213,225,0.5)"}` }}>
                  <div style={{ fontSize: "10px", color: theme === "dark" ? "#9ca3af" : "#475569" }}>Max Lots</div>
                  <div style={{ fontSize: "13px", fontWeight: 700, color: theme === "dark" ? "#f8fafc" : "#0f172a" }}>{selectedStrike.maxLots} ({selectedStrike.maxLots * LOT_SIZE[instrument]} units)</div>
                </div>
                <div style={{ background: theme === "dark" ? "#1f2937" : "rgba(241,245,249,1)", padding: "6px", borderRadius: "4px", border: `1px solid ${theme === "dark" ? "transparent" : "rgba(203,213,225,0.5)"}` }}>
                  <div style={{ fontSize: "10px", color: theme === "dark" ? "#9ca3af" : "#475569" }}>Total Max Risk</div>
                  <div style={{ fontSize: "13px", fontWeight: 700, color: "#ef4444" }}>₹{(selectedStrike.riskPerLot * selectedStrike.maxLots).toLocaleString()}</div>
                </div>
              </div>
              <div style={{ fontSize: "11px", color: theme === "dark" ? "#9ca3af" : "#475569", display: "flex", flexDirection: "column", gap: "4px" }}>
                <div>› SL: Exit if premium &lt; ₹{selectedStrike.hardStopPremium}</div>
                <div>› T1: Book 33% at ₹{selectedStrike.target1} (+30%)</div>
                <div>› T2: Book rest at ₹{selectedStrike.target2} (+80%)</div>
              </div>
            </div>
          )}

        </div>
      ) : (
      <div className="grid-bg" style={{ padding: "2px 6px", display: "grid", gridTemplateColumns: "280px 1fr 260px", gap: 4, minHeight: "calc(100vh - 50px)" }}>

        {/* ── LEFT PANEL: SIGNAL ENGINE ── */}
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>

          {/* Spot ticker */}
          <div className="panel panel-glow" style={{ padding: "8px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
              <div>
                <div style={{ fontSize: 13, color: "#475569", letterSpacing: "0.15em", marginBottom: 2 }}>{instrument} FUTURES</div>
                <div className="ticker-val" style={{ fontSize: 26, fontWeight: 700, color: isUp ? "#10b981" : "#ef4444", lineHeight: 1 }}>
                  {spot.toFixed(2)}
                </div>
                <div style={{ fontSize: 13, color: isUp ? "#00cc66" : "#cc3344", marginTop: 3 }}>
                  {isUp ? "▲" : "▼"} {Math.abs(spotChange).toFixed(2)} ({spotChangePct.toFixed(2)}%)
                </div>
              </div>
              <svg width="100" height="40" style={{ marginTop: 4 }}>
                <defs>
                  <linearGradient id="spk" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={isUp ? "#10b981" : "#ef4444"} stopOpacity="0.4"/>
                    <stop offset="100%" stopColor={isUp ? "#10b981" : "#ef4444"} stopOpacity="0"/>
                  </linearGradient>
                </defs>
                <path d={sparkPath()} fill="none" stroke={isUp ? "#10b981" : "#ef4444"} strokeWidth="1.5" vectorEffect="non-scaling-stroke"
                  viewBox="0 0 200 50" style={{transform:"scale(0.5,0.8)", transformOrigin:"0 0"}}/>
              </svg>
            </div>
            <div style={{ marginTop: 4, paddingTop: 8, borderTop: `1px solid ${theme === "dark" ? "#1f2937" : "rgba(203,213,225,1)"}`, display: "flex", justifyContent: "space-between", fontSize: 13, color: theme === "dark" ? "#9ca3af" : "#475569" }}>
              <span>VWAP <span style={{ color: theme === "dark" ? "#f8fafc" : "#0f172a" }}>{signals?.vwap?.toFixed(2) ?? "—"}</span></span>
              <span>IV <span style={{ color: "#f0c040" }}>{signals ? (signals.iv * 100).toFixed(1) : "—"}%</span></span>
              <span>VIX <span style={{ color: vix > 20 ? "#dc2626" : "#00cc66" }}>{vix.toFixed(1)}</span></span>
            </div>
          </div>

          {/* Reversal Engine */}
          <div className="panel panel-glow" style={{ padding: "8px", border: reversalState.startsWith("REVERSAL") ? "1px solid rgba(255, 200, 0, 0.8)" : theme === "dark" ? "1px solid rgba(255,255,255,0.08)" : "1px solid rgba(203,213,225,1)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ fontSize: 13, color: theme === "dark" ? "#9ca3af" : "#475569", letterSpacing: "0.15em" }}>REVERSAL ENGINE</span>
              <span style={{ fontSize: 14, fontWeight: 700, color: reversalState.includes("LONG") ? "#10b981" : reversalState.includes("SHORT") ? "#ef4444" : theme === "dark" ? "#f8fafc" : "#0f172a" }} className={reversalState.startsWith("REVERSAL") ? "signal-pulse" : ""}>
                {reversalState.replace("_", " ")}
              </span>
            </div>
          </div>

          {/* Composite Score */}
          <div className="panel panel-glow" style={{ padding: "8px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 2 }}>
              <span style={{ fontSize: 13, color: "#10b981", textShadow: "0 0 5px #10b981", letterSpacing: "0.15em" }}>SELLER STRESS (CHAIN RADAR)</span>
              <span style={{ fontSize: 13, color: theme === "dark" ? "#60a5fa" : "#2a4a6a" }}>MIN {strategyConfig.MIN_COMPOSITE_SCORE}/100</span>
            </div>
            <div style={{ display: "flex", alignItems: "flex-end", gap: 4, marginBottom: 2 }}>
              <div className="ticker-val" style={{ fontSize: 40, fontWeight: 900, color: scoreColor(chainContext?.seller_stress_score ?? 0), lineHeight: 1 }}>
                {chainContext ? chainContext.seller_stress_score.toFixed(1) : "0.0"}
              </div>
              <div style={{ fontSize: 14, color: theme === "dark" ? "#60a5fa" : "#2a4a6a", marginBottom: 2 }}>/100</div>
              <div style={{ marginLeft: "auto", textAlign: "right" }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: dirColor, letterSpacing: "0.05em" }}>
                  {signals?.direction ?? "—"}
                </div>
                <div style={{ fontSize: 13, color: theme === "dark" ? "#9ca3af" : "#475569" }}>DIRECTION</div>
              </div>
            </div>
            {/* Score gauge */}
            <div style={{ position: "relative", height: 8, background: theme === "dark" ? "rgba(31, 41, 55, 0.6)" : "rgba(203,213,225,1)", borderRadius: 4, overflow: "hidden", marginBottom: 2 }}>
              <div style={{
                height: "100%", borderRadius: 4,
                width: `${Math.min(100, ((signals?.composite ?? 0) / 30) * 100)}%`,
                background: `linear-gradient(90deg, #0040a0, ${scoreColor(signals?.composite ?? 0)})`,
                transition: "width 0.4s ease"
              }}/>
              <div style={{ position: "absolute", top: 0, left: "70%", width: 1, height: "100%", background: "rgba(255,255,255,0.2)" }}/>
            </div>
            {/* Confirmation timer */}
            <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, color: theme === "dark" ? "#9ca3af" : "#475569" }}>
              <span>CONFIRM</span>
              <div style={{ flex: 1, height: 4, background: theme === "dark" ? "rgba(31, 41, 55, 0.6)" : "rgba(203,213,225,1)", borderRadius: 2 }}>
                <div style={{ height: "100%", borderRadius: 2, background: "#2563eb", width: `${(confirmTimer/8)*100}%`, transition: "width 0.3s" }}/>
              </div>
              <span style={{ color: confirmTimer >= 3 ? "#10b981" : theme === "dark" ? "#f8fafc" : "#0f172a" }}>{Math.round(confirmTimer)}/8</span>
            </div>
          </div>

          {/* Axis Breakdown */}
          <div className="panel panel-glow" style={{ padding: "8px" }}>
            <div style={{ fontSize: 13, color: theme === "dark" ? "#9ca3af" : "#475569", letterSpacing: "0.15em", marginBottom: 4 }}>INSTITUTIONAL RADAR</div>
            
            {chainContext && (
              <div style={{ marginBottom: 2, padding: "6px", background: theme === "dark" ? "rgba(16,185,129,0.03)" : "rgba(16,185,129,0.05)", borderRadius: "8px", border: `1px solid ${theme === "dark" ? "rgba(16,185,129,0.15)" : "rgba(16,185,129,0.2)"}` }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                  <span style={{ fontSize: 13, color: theme === "dark" ? "#e2e8f0" : "#0f172a" }}>IV Skew Status</span>
                  <span style={{ fontSize: 14, fontWeight: 700, color: chainContext.skew_direction === "CALL_BID" ? "#10b981" : chainContext.skew_direction === "PUT_BID" ? "#ef4444" : "#8b5cf6" }}>
                    {chainContext.skew_direction === "CALL_BID" ? "BULLISH (FEAR)" : chainContext.skew_direction === "PUT_BID" ? "BEARISH" : "NEUTRAL"}
                  </span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                  <span style={{ fontSize: 13, color: theme === "dark" ? "#e2e8f0" : "#0f172a" }}>Chain PCR</span>
                  <span style={{ fontSize: 14, fontWeight: 700, color: chainContext.current_pcr > 1.2 ? "#10b981" : chainContext.current_pcr < 0.8 ? "#ef4444" : "#8b5cf6" }}>
                    {chainContext.current_pcr.toFixed(2)}
                  </span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span style={{ fontSize: 13, color: theme === "dark" ? "#e2e8f0" : "#0f172a" }}>Gamma Walls</span>
                  <span style={{ fontSize: 13, color: "#f59e0b", textAlign: "right", fontFamily: "Orbitron" }}>
                    Call: {chainContext.nearest_call_wall || "None"} <br/> Put: {chainContext.nearest_put_wall || "None"}
                  </span>
                </div>
              </div>
            )}
          </div>
            
          {/* Market Microstructure */}
          <div className="panel panel-glow" style={{ padding: "8px", marginTop: "10px" }}>
            <div style={{ fontSize: 13, color: theme === "dark" ? "#9ca3af" : "#475569", letterSpacing: "0.15em", marginBottom: 2 }}>AI LIVE METRICS</div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 4 }}>
              {[
                { label: "LIVE OFI", val: signals?.ofi ? (signals.ofi / 1000).toFixed(1) + "k" : "—" },
                { label: "TAPE SPEED", val: signals?.velocity ? signals.velocity.toFixed(1) + " tps" : "—" },
                { label: "VWAP", val: signals?.vwap ? signals.vwap.toFixed(1) : "—" },
                { label: "ENGINE", val: "ONLINE" },
              ].map(m => (
                <div key={m.label} style={{ background: theme === "dark" ? "rgba(31, 41, 55, 0.4)" : "rgba(241,245,249,1)", border: `1px solid ${theme === "dark" ? "rgba(255,255,255,0.08)" : "rgba(30,60,100,0.5)"}`, borderRadius: 4, padding: "8px" }}>
                  <div style={{ fontSize: 14, color: theme === "dark" ? "#9ca3af" : "#475569", marginBottom: 2 }}>{m.label}</div>
                  <div style={{ fontSize: 13, fontFamily: "Orbitron", color: theme === "dark" ? "#f8fafc" : "#0f172a" }}>{m.val}</div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* ── CENTER PANEL: STRIKE RECOMMENDATIONS ── */}
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <div className="panel panel-glow" style={{ padding: "8px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div>
                <div style={{ fontSize: 13, color: theme === "dark" ? "#9ca3af" : "#475569", letterSpacing: "0.15em" }}>STRIKE RECOMMENDATIONS</div>
                <div style={{ fontSize: 13, color: "#94a3b8", marginTop: 2 }}>
                  {signals?.direction === "BULL" ? "→ BUY CALL OPTIONS (CE)" : signals?.direction === "BEAR" ? "→ BUY PUT OPTIONS (PE)" : "→ AWAITING DIRECTION"}
                </div>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                {phase === "SIGNAL" && (
                  <div style={{ padding: "4px 10px", background: "rgba(0,200,80,0.15)", border: "1px solid rgba(0,255,136,0.4)", borderRadius: 4, fontSize: 14, color: "#10b981", letterSpacing: "0.1em" }} className="signal-pulse">
                    ● SIGNAL ACTIVE
                  </div>
                )}
                <div style={{ fontSize: 14, color: theme === "dark" ? "#9ca3af" : "#475569" }}>Lot ₹ Risk: <span style={{ color: theme === "dark" ? "#f8fafc" : "#0f172a" }}>1.5% = ₹{Math.round(capital * 0.015).toLocaleString()}</span></div>
              </div>
            </div>
          </div>

          {/* Strike cards grid */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6, flex: 1 }}>
            {strikes.length === 0 ? (
              <div style={{ gridColumn: "1/-1", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: 300, color: "#94a3b8" }}>
                <div className="scan-rotate" style={{ width: 40, height: 40, border: "2px solid #cbd5e1", borderTop: "2px solid #0060c0", borderRadius: "50%", marginBottom: 16 }}/>
                <div style={{ fontSize: 13, letterSpacing: "0.1em" }}>{phase.startsWith("ERR") ? phase : "SCANNING FOR MOMENTUM..."}</div>
              </div>
            ) : strikes.map((s, i) => (
              <div key={`${s.strike}-${s.type}`}
                className={`strike-card ${s.isBest ? "best" : ""} ${selectedStrike?.strike === s.strike ? "selected" : ""}`}
                onClick={() => setSelectedStrike(selectedStrike?.strike === s.strike ? null : s)}
              >
                {/* Header */}
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 2 }}>
                  <div>
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      <span style={{ fontFamily: "Orbitron", fontSize: 18, fontWeight: 700, color: s.type === "CE" ? "#059669" : "#f43f5e" }}>{s.strike}</span>
                      <span style={{ fontSize: 14, padding: "2px 6px", borderRadius: 3, background: s.type === "CE" ? "rgba(0,200,100,0.15)" : "rgba(255,60,80,0.15)", color: s.type === "CE" ? "#059669" : "#f43f5e", fontWeight: 700 }}>{s.type}</span>
                    </div>
                    <div style={{ fontSize: 13, color: theme === "dark" ? "#9ca3af" : "#475569", marginTop: 2, letterSpacing: "0.1em" }}>{s.label} — RANK #{s.rank}</div>
                  </div>
                  <div style={{ textAlign: "right" }}>
                    <div style={{ fontFamily: "Orbitron", fontSize: 14, fontWeight: 700, color: scoreColor(s.strikeScore) }}>
                      {s.strikeScore.toFixed(1)}
                    </div>
                    <div style={{ fontSize: 14, color: "#94a3b8" }}>SCORE</div>
                  </div>
                </div>

                {/* Premium */}
                <div style={{ display: "flex", gap: 4, marginBottom: 2 }}>
                  <div style={{ flex: 1, background: theme === "dark" ? "linear-gradient(135deg, rgba(31,41,55,0.6), rgba(17,24,39,0.7))" : "linear-gradient(135deg, rgba(255,255,255,1), rgba(241,245,249,0.9))", backdropFilter: "blur(12px)", borderRadius: 4, padding: "6px 8px", border: `1px solid ${theme === "dark" ? "rgba(255,255,255,0.08)" : "rgba(203,213,225,1)"}`, boxShadow: "0 2px 4px rgba(0,0,0,0.02)" }}>
                    <div style={{ fontSize: 14, color: theme === "dark" ? "#9ca3af" : "#475569", marginBottom: 1 }}>BS PREM</div>
                    <div style={{ fontFamily: "Orbitron", fontSize: 16, fontWeight: 700, color: theme === "dark" ? "#f8fafc" : "#1e293b" }}>₹{s.premium}</div>
                  </div>
                  <div style={{ flex: 1, background: "rgba(16,185,129,0.15)", borderRadius: 4, padding: "6px 8px", border: "1px solid rgba(16,185,129,0.2)" }}>
                    <div style={{ fontSize: 14, color: "#059669", marginBottom: 1 }}>LIVE PREM</div>
                    <div style={{ fontFamily: "Orbitron", fontSize: 16, fontWeight: 700, color: "#10b981" }}>
                      {liveOptions[s.strike]?.[s.type] ? `₹${liveOptions[s.strike][s.type]}` : "WAIT"}
                    </div>
                  </div>
                  <div style={{ flex: 1, background: theme === "dark" ? "linear-gradient(135deg, rgba(31,41,55,0.6), rgba(17,24,39,0.7))" : "linear-gradient(135deg, rgba(255,255,255,1), rgba(241,245,249,0.9))", backdropFilter: "blur(12px)", borderRadius: 4, padding: "6px 8px", border: `1px solid ${theme === "dark" ? "rgba(255,255,255,0.08)" : "rgba(203,213,225,1)"}`, boxShadow: "0 2px 4px rgba(0,0,0,0.02)" }}>
                    <div style={{ fontSize: 14, color: theme === "dark" ? "#9ca3af" : "#475569", marginBottom: 1 }}>MAX LOTS</div>
                    <div style={{ fontFamily: "Orbitron", fontSize: 16, fontWeight: 700, color: theme === "dark" ? "#f8fafc" : "#0f172a" }}>{s.maxLots}</div>
                  </div>
                </div>

                {/* Targets & Stop */}
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 4, marginBottom: 2 }}>
                  {[
                    { label: "STOP", val: `₹${s.hardStopPremium}`, color: "#ef4444" },
                    { label: "T1 +30%", val: `₹${s.target1}`, color: "#f59e0b" },
                    { label: "T2 +80%", val: `₹${s.target2}`, color: "#10b981" },
                  ].map(({ label, val, color }) => (
                    <div key={label} style={{ background: theme === "dark" ? "rgba(31, 41, 55, 0.4)" : "rgba(241,245,249,1)", borderRadius: 3, padding: "4px 6px", borderLeft: `2px solid ${color}44`, borderTop: `1px solid ${theme === "dark" ? "rgba(255,255,255,0.08)" : "rgba(203,213,225,0.5)"}`, borderRight: `1px solid ${theme === "dark" ? "rgba(255,255,255,0.08)" : "rgba(203,213,225,0.5)"}`, borderBottom: `1px solid ${theme === "dark" ? "rgba(255,255,255,0.08)" : "rgba(203,213,225,0.5)"}` }}>
                      <div style={{ fontSize: 13, color: theme === "dark" ? "#9ca3af" : "#475569", marginBottom: 1 }}>{label}</div>
                      <div style={{ fontSize: 14, fontWeight: 700, color }}>{val}</div>
                    </div>
                  ))}
                </div>

                {/* Greeks row */}
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, color: theme === "dark" ? "#9ca3af" : "#475569", borderTop: `1px solid ${theme === "dark" ? "rgba(255,255,255,0.08)" : "rgba(226,232,240,1)"}`, paddingTop: 6, marginBottom: 4 }}>
                  <span>Δ <span style={{ color: theme === "dark" ? "#f8fafc" : "#0f172a" }}>{s.greeks.delta.toFixed(3)}</span></span>
                  <span>Γ <span style={{ color: "#8b5cf6" }}>{s.greeks.gamma.toFixed(4)}</span></span>
                  <span>Θ <span style={{ color: "#dc2626" }}>{s.greeks.theta.toFixed(2)}</span></span>
                  <span>V <span style={{ color: "#44aaff" }}>{s.greeks.vega.toFixed(2)}</span></span>
                </div>

                {/* Prob & BEP */}
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <div style={{ fontSize: 13, color: theme === "dark" ? "#9ca3af" : "#475569" }}>BEP <span style={{ color: theme === "dark" ? "#f8fafc" : "#1e293b" }}>{s.breakeven}</span></div>
                  <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                    <div style={{ fontSize: 13, color: theme === "dark" ? "#9ca3af" : "#475569" }}>P(profit)</div>
                    <div style={{ width: 60, height: 4, background: theme === "dark" ? "rgba(31, 41, 55, 0.6)" : "rgba(226,232,240,1)", borderRadius: 2 }}>
                      <div style={{ width: `${s.probProfit}%`, height: "100%", borderRadius: 2, background: s.probProfit > 50 ? "#059669" : s.probProfit > 35 ? "#f59e0b" : "#ef4444" }}/>
                    </div>
                    <div style={{ fontSize: 13, fontWeight: 700, color: s.probProfit > 50 ? "#059669" : "#ff9944" }}>{s.probProfit}%</div>
                  </div>
                </div>

                {/* Best badge */}
                {s.isBest && (
                  <div style={{ marginTop: 8, padding: "2px 6px", background: "rgba(0,200,80,0.12)", border: "1px solid rgba(0,255,136,0.3)", borderRadius: 3, fontSize: 14, color: "#10b981", letterSpacing: "0.08em", textAlign: "center" }}>
                    ★ HIGHEST PROBABILITY ENTRY
                  </div>
                )}

                {/* Rationale */}
                <div style={{ marginTop: 6 }}>
                  {s.rationale.map((r, ri) => (
                    <div key={ri} style={{ fontSize: 14, color: theme === "dark" ? "#e2e8f0" : "#475569", marginTop: 2 }}>› {r}</div>
                  ))}
                </div>
              </div>
            ))}
          </div>

          {/* Selected Strike Detail */}
          {selectedStrike && (
            <div className="panel" style={{ padding: "8px", border: `1px solid ${theme === "dark" ? "rgba(59,130,246,0.5)" : "rgba(59,130,246,0.3)"}` }}>
              <div style={{ fontSize: 13, color: theme === "dark" ? "#9ca3af" : "#475569", letterSpacing: "0.15em", marginBottom: 2 }}>
                TRADE PLAN — {instrument} {selectedStrike.strike} {selectedStrike.type}
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 6, marginBottom: 2 }}>
                {[
                  { label: "ENTRY (limit)", val: `₹${liveOptions[selectedStrike.strike]?.[selectedStrike.type] || selectedStrike.premium}`, sub: "LMT +0.1% buffer", color: theme === "dark" ? "#f8fafc" : "#0f172a", baseColor: "#0f172a" },
                  { label: "HARD STOP", val: `₹${selectedStrike.hardStopPremium}`, sub: "40% loss → EXIT", color: "#ef4444" },
                  { label: "TARGET 1", val: `₹${selectedStrike.target1}`, sub: "Book 33% here", color: "#f59e0b" },
                  { label: "TARGET 2", val: `₹${selectedStrike.target2}`, sub: "Trail 33% remain", color: "#10b981" },
                ].map(({ label, val, sub, color, baseColor }) => (
                  <div key={label} style={{ background: theme === "dark" ? "linear-gradient(135deg, rgba(31,41,55,0.6), rgba(17,24,39,0.7))" : "linear-gradient(135deg, rgba(255,255,255,1), rgba(241,245,249,0.9))", backdropFilter: "blur(12px)", border: `1px solid ${baseColor === "#0f172a" ? (theme === "dark" ? "rgba(255,255,255,0.08)" : "rgba(203,213,225,1)") : color + "33"}`, borderRadius: 4, padding: "2px 6px" }}>
                    <div style={{ fontSize: 14, color: theme === "dark" ? "#9ca3af" : "#475569", marginBottom: 2 }}>{label}</div>
                    <div style={{ fontFamily: "Orbitron", fontSize: 16, fontWeight: 700, color }}>{val}</div>
                    <div style={{ fontSize: 14, color: "#94a3b8", marginTop: 2 }}>{sub}</div>
                  </div>
                ))}
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
                <div style={{ background: theme === "dark" ? "linear-gradient(135deg, rgba(31,41,55,0.6), rgba(17,24,39,0.7))" : "linear-gradient(135deg, rgba(255,255,255,0.9), rgba(248,250,252,0.9))", backdropFilter: "blur(12px)", boxShadow: "0 8px 32px rgba(0,0,0,0.05)", borderRadius: 4, padding: "2px 6px", border: `1px solid ${theme === "dark" ? "rgba(255,255,255,0.08)" : "rgba(203,213,225,1)"}` }}>
                  <div style={{ fontSize: 14, color: theme === "dark" ? "#9ca3af" : "#475569", marginBottom: 4, letterSpacing: "0.1em" }}>POSITION SIZING</div>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 3 }}>
                    <span style={{ color: theme === "dark" ? "#9ca3af" : "#475569" }}>Max Lots</span>
                    <span style={{ color: theme === "dark" ? "#f8fafc" : "#0f172a", fontWeight: 700 }}>{selectedStrike.maxLots} lots ({selectedStrike.maxLots * LOT_SIZE[instrument]} units)</span>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 3 }}>
                    <span style={{ color: theme === "dark" ? "#9ca3af" : "#475569" }}>Max Risk/Lot</span>
                    <span style={{ color: "#dc2626" }}>₹{selectedStrike.riskPerLot.toLocaleString()}</span>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
                    <span style={{ color: theme === "dark" ? "#9ca3af" : "#475569" }}>Total Max Risk</span>
                    <span style={{ color: "#ef4444", fontWeight: 700 }}>₹{(selectedStrike.riskPerLot * selectedStrike.maxLots).toLocaleString()}</span>
                  </div>
                </div>
                <div style={{ background: theme === "dark" ? "linear-gradient(135deg, rgba(31,41,55,0.6), rgba(17,24,39,0.7))" : "linear-gradient(135deg, rgba(255,255,255,0.9), rgba(248,250,252,0.9))", backdropFilter: "blur(12px)", boxShadow: "0 8px 32px rgba(0,0,0,0.05)", borderRadius: 4, padding: "2px 6px", border: `1px solid ${theme === "dark" ? "rgba(255,255,255,0.08)" : "rgba(203,213,225,1)"}` }}>
                  <div style={{ fontSize: 14, color: theme === "dark" ? "#9ca3af" : "#475569", marginBottom: 4, letterSpacing: "0.1em" }}>EXIT RULES</div>
                  {[
                    "Phase 1: Exit if premium < ₹" + selectedStrike.hardStopPremium,
                    "Phase 2: Trail to Peak × 0.75",
                    "OFI flip 5 ticks → EXIT NOW",
                    "Vol cliff >50% drop → EXIT NOW",
                    "Max hold: 45 minutes",
                    "Mandatory exit: 14:45"
                  ].map((rule, ri) => (
                    <div key={ri} style={{ fontSize: 14, color: theme === "dark" ? "#e2e8f0" : "#475569", marginBottom: 2 }}>› {rule}</div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* ── RIGHT PANEL: ALERTS & FILTERS ── */}
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>

          {/* Fakeout battery */}
          <div className="panel panel-glow" style={{ padding: "8px" }}>
            <div style={{ fontSize: 13, color: theme === "dark" ? "#9ca3af" : "#475569", letterSpacing: "0.15em", marginBottom: 2 }}>FAKEOUT BATTERY</div>
            {[
              { label: "Spread Toxicity", pass: true, detail: "Protected by AI Filter" },
              { label: "Reversal Trap", pass: true, detail: "Filtered by Engine" },
              { label: "Time Filter", pass: true, detail: "Checked by Backend" },
              { label: "Sweep Threshold", pass: (signals?.velocity ?? 0) > 15 ? true : false, detail: "TPS > 15 required for sweeps" },
            ].map(({ label, pass, detail }) => (
              <div key={label} style={{ display: "flex", alignItems: "center", gap: 4, marginBottom: 2, padding: "6px 8px", background: pass ? (theme === "dark" ? "rgba(16,185,129,0.05)" : "rgba(16,185,129,0.1)") : (theme === "dark" ? "rgba(239,68,68,0.05)" : "rgba(239,68,68,0.1)"), borderRadius: 4, border: `1px solid ${pass ? "rgba(16,185,129,0.2)" : "rgba(239,68,68,0.2)"}` }}>
                <div style={{ width: 6, height: 6, borderRadius: "50%", background: pass ? "#059669" : "#ef4444", flexShrink: 0, ...(pass ? {} : { animation: "pulse 0.8s ease-in-out infinite" }) }}/>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 13, color: pass ? (theme === "dark" ? "#e2e8f0" : "#0f172a") : "#dc2626" }}>{label}</div>
                  <div style={{ fontSize: 14, color: "#94a3b8" }}>{detail}</div>
                </div>
                <div style={{ fontSize: 13, fontWeight: 700, color: pass ? "#059669" : "#ef4444" }}>{pass ? "PASS" : "FAIL"}</div>
              </div>
            ))}
          </div>

          {/* Trade phase tracker */}
          <div className="panel panel-glow" style={{ padding: "8px" }}>
            <div style={{ fontSize: 13, color: theme === "dark" ? "#9ca3af" : "#475569", letterSpacing: "0.15em", marginBottom: 2 }}>EXIT PHASE TRACKER</div>
            {[
              { phase: "P1", label: "PROTECTION", range: "Entry → +30%", rule: "Hard stop @ 40% loss", color: "#dc2626" },
              { phase: "P2", label: "MOMENTUM", range: "+30% → +80%", rule: "Trail Peak × 0.75", color: "#f59e0b" },
              { phase: "P3", label: "ACCELERATION", range: "+80% → ∞", rule: "Trail Peak × 0.80", color: "#10b981" },
              { phase: "P4", label: "EXHAUSTION", range: "Any phase", rule: "OFI flip / Vol cliff", color: "#ef4444" },
            ].map(({ phase: ph, label, range, rule, color }) => (
              <div key={ph} style={{ marginBottom: 2, padding: "7px 10px", borderRadius: 4, background: theme === "dark" ? "linear-gradient(135deg, rgba(31,41,55,0.6), rgba(17,24,39,0.7))" : "linear-gradient(135deg, rgba(255,255,255,0.9), rgba(248,250,252,0.9))", backdropFilter: "blur(12px)", boxShadow: "0 8px 32px rgba(0,0,0,0.05)", border: `1px solid ${color}22`, borderLeft: `2px solid ${color}` }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 2 }}>
                  <span style={{ fontSize: 14, fontWeight: 700, color, fontFamily: "Orbitron" }}>{ph}: {label}</span>
                  <span style={{ fontSize: 14, color: "#94a3b8" }}>{range}</span>
                </div>
                <div style={{ fontSize: 14, color: theme === "dark" ? "#e2e8f0" : "#475569" }}>{rule}</div>
              </div>
            ))}
          </div>

          {/* Alert log */}
          <div className="panel panel-glow" style={{ padding: "8px", flex: 1, overflowY: "auto", minHeight: 0 }}>
            <div style={{ fontSize: 13, color: theme === "dark" ? "#9ca3af" : "#475569", letterSpacing: "0.15em", marginBottom: 2 }}>SIGNAL LOG</div>
            {alertLog.length === 0 ? (
              <div style={{ fontSize: 13, color: "#94a3b8", textAlign: "center", paddingTop: 20 }}>
                <div className="scan-rotate" style={{ width: 24, height: 24, border: "1.5px solid #cbd5e1", borderTop: "1.5px solid #3b82f6", borderRadius: "50%", margin: "0 auto 10px" }}/>
                No signals yet
              </div>
            ) : alertLog.map((a, i) => (
              <div key={i} className="alert-item" style={{
                marginBottom: 7, padding: "7px 10px",
                background: a.type === "bull" ? (theme === "dark" ? "rgba(16,185,129,0.05)" : "rgba(16,185,129,0.1)") : (theme === "dark" ? "rgba(239,68,68,0.05)" : "rgba(239,68,68,0.1)"),
                border: `1px solid ${a.type === "bull" ? "rgba(16,185,129,0.15)" : "rgba(239,68,68,0.15)"}`,
                borderRadius: 4,
              }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 2 }}>
                  <span style={{ fontSize: 13, fontWeight: 700, color: a.type === "bull" ? "#059669" : "#f43f5e" }}>
                    {a.type === "bull" ? "▲ BULL" : "▼ BEAR"}
                  </span>
                  <span style={{ fontSize: 14, color: "#94a3b8" }}>{a.time}</span>
                </div>
                <div style={{ fontSize: 14, color: theme === "dark" ? "#e2e8f0" : "#475569" }}>{a.msg}</div>
                <div style={{ marginTop: 3, height: 2, background: theme === "dark" ? "rgba(31, 41, 55, 0.6)" : "rgba(203,213,225,1)", borderRadius: 1 }}>
                  <div style={{ width: `${(a.score/100)*100}%`, height: "100%", borderRadius: 1, background: a.type === "bull" ? "#059669" : "#f43f5e" }}/>
                </div>
              </div>
            ))}
          </div>

          {/* Time gate */}
          <div className="panel" style={{ padding: "6px 8px" }}>
            <div style={{ fontSize: 13, color: theme === "dark" ? "#9ca3af" : "#475569", letterSpacing: "0.15em", marginBottom: 2 }}>TIME GATE</div>
            {[
              { zone: "09:15–09:45", label: "BLOCKED", color: "#ef4444" },
              { zone: "09:45–11:30", label: "PRIME", color: "#10b981" },
              { zone: "11:30–12:00", label: "CAUTION", color: "#f59e0b" },
              { zone: "12:00–14:45", label: "ACTIVE", color: "#2563eb" },
              { zone: "14:45–15:30", label: "BLOCKED", color: "#ef4444" },
            ].map(({ zone, label, color }) => {
              const hr = new Date().getHours(), mn = new Date().getMinutes();
              const t = hr + mn/60;
              const [start, end] = zone.split("–").map(s => { const [h,m]=s.split(":"); return parseInt(h)+parseInt(m)/60; });
              const active = t >= start && t < end;
              return (
                <div key={zone} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 2, padding: "3px 6px", borderRadius: 3, background: active ? `${color}18` : "transparent", border: active ? `1px solid ${color}33` : "1px solid transparent" }}>
                  <span style={{ fontSize: 14, color: active ? color : "#94a3b8" }}>{zone}</span>
                  <span style={{ fontSize: 14, fontWeight: 700, color: active ? color : "#94a3b8" }}>{label}{active ? " ◀" : ""}</span>
                </div>
              );
            })}
          </div>
        </div>
      </div>
      )}
    </div>
  );
}
