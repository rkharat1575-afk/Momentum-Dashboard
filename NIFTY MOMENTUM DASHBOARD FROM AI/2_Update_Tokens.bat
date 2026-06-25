@echo off
color 0B
echo ===================================================
echo     STEP 2: UPDATE OPTION TOKENS
echo ===================================================

if not exist "C:\sharekhan_terminal\auto_tokens.py" (
    echo ERROR: auto_tokens.py not found in C:\sharekhan_terminal
    pause
    exit /b 1
)

cd /d "C:\sharekhan_terminal"
python auto_tokens.py
if errorlevel 1 (
    echo.
    echo WARNING: Token update script exited with an error. Check output above.
    pause
    exit /b 1
)
echo.
echo Tokens Updated Successfully!
pause
