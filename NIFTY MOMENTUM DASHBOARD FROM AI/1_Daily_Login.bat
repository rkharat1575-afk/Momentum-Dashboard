@echo off
color 0A
echo ===================================================
echo     STEP 1: DAILY SHAREKHAN LOGIN
echo ===================================================

if not exist "C:\sharekhan_terminal\daily_login_v2.py" (
    echo ERROR: daily_login_v2.py not found in C:\sharekhan_terminal
    pause
    exit /b 1
)

cd /d "C:\sharekhan_terminal"
python daily_login_v2.py
if errorlevel 1 (
    echo.
    echo WARNING: Login script exited with an error. Check output above.
)
echo.
pause
