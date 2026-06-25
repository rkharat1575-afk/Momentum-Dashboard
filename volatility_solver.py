import math

def norm_cdf(x):
    """Cumulative distribution function for the standard normal distribution."""
    return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0

def norm_pdf(x):
    """Probability density function for the standard normal distribution."""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)

def bs_price(S, K, T, r, sigma, opt_type):
    """
    Calculate the Black-Scholes price of an option.
    S: Spot Price
    K: Strike Price
    T: Time to Expiry (in Years)
    r: Risk-free rate
    sigma: Volatility (IV)
    opt_type: 'CE' or 'PE'
    """
    if T <= 0.0001 or sigma <= 0.0001:
        return max(0.0, S - K) if opt_type == 'CE' else max(0.0, K - S)
        
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    
    if opt_type == 'CE':
        return S * norm_cdf(d1) - K * math.exp(-r * T) * norm_cdf(d2)
    elif opt_type == 'PE':
        return K * math.exp(-r * T) * norm_cdf(-d2) - S * norm_cdf(-d1)
    else:
        raise ValueError("opt_type must be 'CE' or 'PE'")

def bs_vega(S, K, T, r, sigma):
    """Calculate Black-Scholes Vega (derivative of price with respect to volatility)."""
    if T <= 0.0001 or sigma <= 0.0001:
        return 0.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    return S * norm_pdf(d1) * math.sqrt(T)

def calculate_iv(market_price, S, K, T, r=0.065, opt_type='CE', initial_vol=0.2, max_iter=100, tol=1e-5):
    """
    Calculate Implied Volatility using the Newton-Raphson method.
    S: Spot price
    K: Strike price
    T: Time to maturity in years
    r: Risk-free rate (Default: 6.5% for India)
    opt_type: 'CE' or 'PE'
    """
    # 1. Edge Case: Zero or negative price
    if market_price <= 0.0:
        return 0.0001
        
    # 2. Edge Case: Price below intrinsic value
    intrinsic = max(0.0, S - K) if opt_type == 'CE' else max(0.0, K - S)
    if market_price <= intrinsic:
        return 0.0001 # Can't calculate IV below intrinsic

    sigma = initial_vol
    
    for _ in range(max_iter):
        price = bs_price(S, K, T, r, sigma, opt_type)
        vega = bs_vega(S, K, T, r, sigma)
        
        diff = market_price - price
        
        if abs(diff) < tol:
            return sigma
            
        if vega < 1e-8:
            # Fallback if vega is effectively zero (deep ITM/OTM options)
            break
            
        sigma = sigma + diff / vega
        
        # Prevent negative volatility
        if sigma <= 0.0:
            sigma = 0.0001
            
    return sigma
