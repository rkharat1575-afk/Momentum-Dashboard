@echo off
echo ===========================================
echo   AI MOMENTUM ENGINE STARTUP SEQUENCE
echo ===========================================
echo.
echo [1] Updating Option Tokens for the Current Week...
set PYTHONIOENCODING=utf8
python auto_tokens.py
echo.
echo [2] Running Walk-Forward Optimizer (WFO)...
python auto_optimizer.py
echo.
echo [3] Launching Momentum Backend...
start "MOMENTUM BACKEND" cmd /k "python dashboard_backend.py"
echo.
echo [4] Launching React Dashboard UI...
cd "NIFTY MOMENTUM DASHBOARD FROM AI"
start "REACT DASHBOARD" cmd /k "npm run dev"
echo.
echo [SUCCESS] Sequence Complete! The Momentum Engine is perfectly aligned!
echo.
echo The React Dashboard will open automatically in your web browser.
