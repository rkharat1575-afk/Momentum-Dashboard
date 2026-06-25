@echo off
echo Setting up daily ML Optimizer at 3:35 PM...
schtasks /create /tn "SniperMachineMLOptimizer" /tr "\"c:\sharekhan_terminal\Sniper Machine\Run_Optimizer.bat\"" /sc daily /st 15:35
echo.
echo Task scheduled successfully! The ML Optimizer will now run automatically every day at 3:35 PM.
pause
