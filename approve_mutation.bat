@echo off
echo ========================================================
echo        MOMENTUM ENGINE - ML MUTATION APPROVAL
echo ========================================================
echo.

if not exist "proposed_strategy_config.json" (
    echo [ERROR] No proposed mutation found! Please run the ML Optimizer first.
    pause
    exit /b
)

echo [INFO] Copying proposed optimal settings to live configuration...
copy /Y "proposed_strategy_config.json" "NIFTY MOMEMTUM DASHBOARD FROM AI\public\strategy_config.json"

echo.
echo [SUCCESS] Mutation Approved! The Momentum Engine has been upgraded.
echo Please refresh your dashboard browser to load the new DNA.
echo.
pause
