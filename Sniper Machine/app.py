import streamlit as st
import pandas as pd
import numpy as np
import time
import threading
import plotly.graph_objects as go

# Page Configuration for "Great Visuals"
st.set_page_config(
    page_title="Sniper Machine Dashboard",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for Dark Mode & Sleek UI
st.markdown("""
<style>
    .stApp {
        background-color: #0b0f19;
        color: #FAFAFA;
    }
    .metric-card {
        background: rgba(30, 33, 41, 0.4);
        backdrop-filter: blur(10px);
        -webkit-backdrop-filter: blur(10px);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 15px;
        padding: 20px;
        box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
        text-align: center;
    }
    .metric-value {
        font-size: 2.5rem;
        font-weight: bold;
        color: #00FFCC;
    }
    .metric-label {
        font-size: 1rem;
        color: #A0AEC0;
        text-transform: uppercase;
        letter-spacing: 1px;
    }
    .signal-buy {
        background-color: rgba(0, 255, 127, 0.2);
        border: 2px solid #00FF7F;
        border-radius: 10px;
        padding: 20px;
        text-align: center;
        animation: pulse 2s infinite;
    }
    .signal-neutral {
        background-color: rgba(128, 128, 128, 0.1);
        border: 1px solid #555;
        border-radius: 10px;
        padding: 20px;
        text-align: center;
    }
    @keyframes pulse {
        0% { box-shadow: 0 0 0 0 rgba(0, 255, 127, 0.7); }
        70% { box-shadow: 0 0 0 20px rgba(0, 255, 127, 0); }
        100% { box-shadow: 0 0 0 0 rgba(0, 255, 127, 0); }
    }
</style>
""", unsafe_allow_html=True)

from data_streamer import DataStreamer

# Initialize session state for the data streamer singleton
if 'streamer' not in st.session_state:
    streamer_obj = DataStreamer()
    st.session_state.streamer = streamer_obj
    # Start the LIVE stream reader in the background
    def run_live(streamer_instance):
        streamer_instance.start_live_stream()
    threading.Thread(target=run_live, args=(streamer_obj,), daemon=True).start()

st.title("🎯 Sniper Machine: Nifty Scalping System")
st.markdown("Automated Quantitative Options Scalping Engine based on VWAP and Order Flow Imbalance.")

# Top Metrics Row
col1, col2, col3, col4 = st.columns(4)

# We use placeholders to update data live
ph_ltp = col1.empty()
ph_vwap = col2.empty()
ph_slope = col3.empty()
ph_imbalance = col4.empty()

st.markdown("### 📡 Live Signal Status")
ph_signal = st.empty()

st.markdown("### 📈 Trend Analytics")
ph_chart = st.empty()

# Mocking live updates for the dashboard
engine = st.session_state.streamer.engine

if len(engine.trend_history) > 0:
    latest = engine.trend_history.iloc[-1]
    
    # Calculate recent VWAP for display
    df = engine.calculate_vwap_bands(engine.trend_history.copy())
    vwap_val = df['vwap'].iloc[-1] if not df.empty else 0
    
    # Re-eval to get metrics for UI
    signal, reason, metrics = engine.evaluate_trend(latest['price'], latest['volume'], latest['bid_qty'], latest['ask_qty'])
    
    # Update Metrics
    ph_ltp.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Nifty Fut LTP</div>
            <div class="metric-value">{latest['price']:.2f}</div>
        </div>
    """, unsafe_allow_html=True)
    
    ph_vwap.markdown(f"""
        <div class="metric-card" style="border-left-color: #FF00FF;">
            <div class="metric-label">VWAP</div>
            <div class="metric-value">{vwap_val:.2f}</div>
        </div>
    """, unsafe_allow_html=True)
    
    slope_color = "#00FF7F" if metrics.get('price_slope', 0) > 0 else "#FF4500"
    ph_slope.markdown(f"""
        <div class="metric-card" style="border-left-color: {slope_color};">
            <div class="metric-label">Price Slope (5m)</div>
            <div class="metric-value" style="color: {slope_color};">{metrics.get('price_slope', 0.0):.2f}</div>
        </div>
    """, unsafe_allow_html=True)
    
    imb_color = "#00FF7F" if metrics.get('cd_ratio', 0) > 0 else "#FF4500"
    ph_imbalance.markdown(f'''
        <div class="metric-card" style="border-left-color: {imb_color};">
            <div class="metric-label">Cum Delta Ratio</div>
            <div class="metric-value" style="color: {imb_color};">{metrics.get('cd_ratio', 0.0):.2f}</div>
        </div>
    ''', unsafe_allow_html=True)
    
    # Update Signal Box
    if "BUY" in signal:
        ph_signal.markdown(f"""
            <div class="signal-buy">
                <h2>🚀 {signal.replace('_', ' ')} DETECTED</h2>
                <p style="font-size:1.2rem;">{reason}</p>
                <p>Alert dispatched to Telegram.</p>
            </div>
        """, unsafe_allow_html=True)
    else:
        direction = metrics.get("direction", "SIDEWAYS")
        color = "#00FF7F" if "BULL" in direction else "#FF4500" if "BEAR" in direction else "#ffd700"
        ph_signal.markdown(f"""
            <div class="signal-neutral">
                <h2 style="color: {color};">🧭 LIVE DIRECTION: {direction}</h2>
                <p style="font-size:1.2rem; color: #888;">{reason}</p>
            </div>
        """, unsafe_allow_html=True)
        
    # Chart
    if len(df) > 5:
        # Convert index to datetime if not already
        if not pd.api.types.is_datetime64_any_dtype(df['timestamp']):
            df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        # Resample into 10-second bars for Candlesticks
        df_chart = df.set_index('timestamp')
        ohlc = df_chart['price'].resample('10s').ohlc().dropna()
        vwap_resampled = df_chart[['vwap', 'vwap_upper', 'vwap_lower']].resample('10s').last().dropna()
        
        # Calculate Volume Anomalies for markers
        df_chart['vol_ma'] = df_chart['volume'].rolling(20).mean()
        df_chart['is_anomaly'] = (df_chart['volume'] > (df_chart['vol_ma'] * 1.5)) & (df_chart['vol_ma'] > 0)
        anomaly_candles = df_chart['is_anomaly'].resample('10s').max().dropna().astype(bool)
        
        chart_data = ohlc.join(vwap_resampled, how='inner').join(anomaly_candles.rename('has_anomaly'), how='left').tail(60) # Last 60 candles = 10 mins
        
        fig = go.Figure()
        
        # Candlestick
        fig.add_trace(go.Candlestick(
            x=chart_data.index,
            open=chart_data['open'],
            high=chart_data['high'],
            low=chart_data['low'],
            close=chart_data['close'],
            name='Nifty (10s)'
        ))
        
        # VWAP Line
        fig.add_trace(go.Scatter(
            x=chart_data.index, y=chart_data['vwap'], 
            mode='lines', name='VWAP (Value Area)', 
            line=dict(color='#FF00FF', width=2)
        ))
        
        # VWAP Upper
        fig.add_trace(go.Scatter(
            x=chart_data.index, y=chart_data['vwap_upper'], 
            mode='lines', name='Upper Resistance', 
            line=dict(color='rgba(255,255,255,0.3)', width=1, dash='dash')
        ))
        
        # VWAP Lower
        fig.add_trace(go.Scatter(
            x=chart_data.index, y=chart_data['vwap_lower'], 
            mode='lines', name='Lower Support', 
            line=dict(color='rgba(255,255,255,0.3)', width=1, dash='dash')
        ))
        
        # Volume Anomaly Markers
        anomaly_points = chart_data[chart_data['has_anomaly'] == True]
        if not anomaly_points.empty:
            fig.add_trace(go.Scatter(
                x=anomaly_points.index,
                y=anomaly_points['high'] + 5,
                mode='markers',
                marker=dict(symbol='triangle-down', size=12, color='#FFD700', line=dict(color='black', width=1)),
                name='Institutional Footprint'
            ))
        
        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=20, r=20, t=10, b=20),
            yaxis=dict(
                showgrid=True, 
                gridcolor='rgba(255,255,255,0.05)',
                zeroline=False,
                autorange=True,
                fixedrange=False
            ),
            xaxis=dict(
                showticklabels=True,
                showgrid=True,
                gridcolor='rgba(255,255,255,0.05)',
                rangeslider=dict(visible=False) # Important for clean candlestick charts
            ),
            height=350,
            hovermode="x unified",
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                )
        )
        ph_chart.plotly_chart(fig, width='stretch')
else:
    ph_signal.markdown("""
        <div class="signal-neutral">
            <h2>📡 INITIALIZING DATA STREAM...</h2>
            <p style="font-size:1.2rem; color: #888;">Waiting for market ticks</p>
        </div>
    """, unsafe_allow_html=True)

# Auto-refresh the page every 1 second
time.sleep(1.0)
st.rerun()
