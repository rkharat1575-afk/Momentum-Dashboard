@echo off
color 0E
echo ===================================================
echo     STARTING LIVE DATA ENGINE ^& DASHBOARD
echo ===================================================

:: Verify backend script exists
if not exist "C:\sharekhan_terminal\dashboard_backend.py" (
    echo ERROR: dashboard_backend.py not found!
    pause
    exit /b 1
)

:: Kill any existing dashboard backend processes to free up the Sharekhan connection
taskkill /F /IM python.exe /FI "WINDOWTITLE eq Nifty Data Engine*" >nul 2>&1
taskkill /F /IM python.exe >nul 2>&1

:: Start the Python Backend Engine in a new separate window
start "Nifty Data Engine" cmd /k "cd /d C:\sharekhan_terminal && python dashboard_backend.py"

:: Give backend a moment to initialize
timeout /t 3 /nobreak >nul

:: Start the React Dashboard
cd /d "C:\sharekhan_terminal\NIFTY MOMENTUM DASHBOARD FROM AI"
if errorlevel 1 (
    echo ERROR: Dashboard directory not found!
    pause
    exit /b 1
)
npm run dev
