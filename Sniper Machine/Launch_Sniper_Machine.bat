@echo off
echo =========================================
echo       SNIPER MACHINE INITIALIZING...
echo =========================================
echo.
echo Starting the Math Engine and Dashboard...

cd /d "%~dp0"
python -m streamlit run app.py

pause
