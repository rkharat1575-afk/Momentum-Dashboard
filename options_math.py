import math
from datetime import datetime

# Standard risk-free rate for Indian market
RISK_FREE_RATE = 0.07

def norm_cdf(x):
    """Cumulative distribution function for the standard normal distribution."""
    return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0

def norm_pdf(x):
    """Probability density function for the standard normal distribution."""
    return math.exp(-0.5 * x**2) / math.sqrt(2.0 * math.pi)

def calculate_time_to_expiry(expiry_date_str):
    """
    Calculates T (time to expiry in years) assuming Indian Market expiry at 15:30.
    expiry_date_str format: 'DD-MMM-YYYY' (e.g., '28-May-2026')
    """
    try:
        now = datetime.now()
        expiry_date = datetime.strptime(expiry_date_str, "%d-%b-%Y")
        expiry_datetime = expiry_date.replace(hour=15, minute=30, second=0)
        
        time_diff = expiry_datetime - now
        days_to_expiry = time_diff.total_seconds() / (24 * 3600)
        
        # Avoid division by zero on expiry day
        if days_to_expiry <= 0:
            return 0.0001
        
        return days_to_expiry / 365.0
    except:
        # Fallback to 1 day if parsing fails
        return 1.0 / 365.0

def calculate_implied_volatility(S, K, T, r, market_price, option_type="CE"):
    """
    Estimates Implied Volatility using Newton-Raphson. 
    Converts ITM options to OTM using Put-Call Parity for mathematical stability,
    which perfectly aligns with professional platforms like Trade Tiger.
    """
    if market_price <= 0 or T <= 0 or S <= 0 or K <= 0:
        return 0.15 # Fallback baseline IV

    # Use put-call parity to find equivalent out-of-the-money option price for stability
    if option_type == "CE" and S > K:
        # CE is ITM, convert to OTM PE
        market_price = market_price - S + K * math.exp(-r * T)
        option_type = "PE"
    elif option_type == "PE" and S < K:
        # PE is ITM, convert to OTM CE
        market_price = market_price - K * math.exp(-r * T) + S
        option_type = "CE"
        
    # If market price is negative after parity (no time value left), volatility is near zero
    if market_price <= 0:
        return 0.01

    # Safe initial seed (20% IV)
    sigma = 0.20

    # Newton-Raphson solver (up to 15 iterations for high precision)
    for _ in range(15):
        d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        
        if option_type == "CE":
            price_est = S * norm_cdf(d1) - K * math.exp(-r * T) * norm_cdf(d2)
        else:
            price_est = K * math.exp(-r * T) * norm_cdf(-d2) - S * norm_cdf(-d1)
            
        vega = S * norm_pdf(d1) * math.sqrt(T)
        
        # Prevent division by zero
        if vega < 1e-8: break
        
        diff = price_est - market_price
        
        # Stop if we are within 0.001 rupees of the actual price
        if abs(diff) < 0.001: break
        
        sigma -= diff / vega
        
        # Prevent negative volatility
        if sigma <= 0.001:
            sigma = 0.001
            break

    return max(0.01, min(sigma, 3.0)) # Clamp between 1% and 300%

def calculate_greeks(S, K, T, r, sigma, option_type="CE"):
    """
    Calculates Delta and Gamma using the Black-Scholes formula.
    """
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0, 0.0
        
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    
    # Gamma is the same for Calls and Puts
    gamma = norm_pdf(d1) / (S * sigma * math.sqrt(T))
    
    if option_type == "CE":
        delta = norm_cdf(d1)
    else:
        delta = norm_cdf(d1) - 1.0
        
    return delta, gamma

def get_order_book_imbalance(tick):
    """
    Calculates Level-2 Order Book imbalance (Bid Qty vs Ask Qty).
    Returns (ratio, signal_string, score_bonus)
    """
    bid_qty = float(tick.get("bidQty", 0))
    ask_qty = float(tick.get("offQty", 0))
    
    total = bid_qty + ask_qty
    if total == 0:
        return 1.0, "NONE", 0
        
    bid_ratio = bid_qty / total
    
    # 75% of volume on Bid means heavy institutional absorption of sellers
    if bid_ratio > 0.75:
        return bid_qty / max(1, ask_qty), "🔥 MASSIVE BUY WALL", 15
    elif bid_ratio > 0.60:
        return bid_qty / max(1, ask_qty), "🟢 BUYERS ABSORBING", 5
    elif bid_ratio < 0.25:
        return ask_qty / max(1, bid_qty), "🩸 MASSIVE SELL WALL", -15
    elif bid_ratio < 0.40:
        return ask_qty / max(1, bid_qty), "🔴 SELLERS AGGRESSIVE", -5
        
    return 1.0, "NEUTRAL", 0

def calculate_dynamic_targets(ltp, iv, vix=15.0):
    """
    Calculates dynamic Stop Loss and Targets based on Implied Volatility.
    Higher IV = Wider SL/Targets to avoid being stopped out by noise.
    """
    # Normalize IV using VIX or a baseline of 15%
    # iv is in decimal, so iv * 100 is percentage
    iv_pct = iv * 100 if iv < 1 else iv
    iv_factor = max(0.5, min(iv_pct / vix, 2.0)) if vix > 0 else 1.0
    
    # Dynamic percentages
    sl_pct = min(0.50, max(0.20, 0.30 * iv_factor))
    tgt1_pct = sl_pct * 1.5  # 1.5 R:R
    tgt2_pct = sl_pct * 2.5  # 2.5 R:R
    
    sl_price = round(ltp * (1 - sl_pct), 1)
    tgt1_price = round(ltp * (1 + tgt1_pct), 1)
    tgt2_price = round(ltp * (1 + tgt2_pct), 1)
    
    return sl_price, tgt1_price, tgt2_price

def score_gamma(gamma, ltp):
    """
    Scores the explosiveness of the option. Higher gamma = faster delta acceleration.
    Gamma is multiplied by LTP to normalize its effect relative to the premium paid.
    """
    if gamma <= 0: return 0
    # Normalized gamma impact
    gamma_impact = gamma * ltp * 100 
    
    if gamma_impact > 2.0:
        return 15 # Explosive
    elif gamma_impact > 1.0:
        return 10
    elif gamma_impact > 0.5:
        return 5
    return 0
