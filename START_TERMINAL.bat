@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
title SK Terminal v4.2
color 0A
cd C:\sharekhan_terminal

echo.
echo ============================================
echo   SK TERMINAL v4.2 - STARTING
echo ============================================

echo.
echo [1/4] Daily Login...
python daily_login_v2.py
if errorlevel 1 ( echo Login failed & pause & exit )

echo.
echo [2/4] Downloading scrip master and setting tokens...
python auto_setup.py
if errorlevel 1 ( echo Setup failed & pause & exit )

echo.
echo [3/4] Starting Tick Feeder...
start "SK Tick Feeder" cmd /k "cd C:\sharekhan_terminal && python tick_live.py"
timeout /t 6 /nobreak >nul

echo.
echo [4/4] Setting tokens from live price...
python set_tokens.py

echo.
echo [5/5] Launching Dashboard...
start "SK Dashboard" cmd /k "cd C:\sharekhan_terminal && python -m streamlit run sharekhan_terminal_v4.py"

echo.
echo ============================================
echo   ALL DONE - Dashboard opening in browser
echo ============================================
pause
