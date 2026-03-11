@echo off
echo Stopping any existing Flask processes...
taskkill /F /IM python.exe /FI "WINDOWTITLE eq *app.py*" 2>nul
timeout /t 2 /nobreak >nul

echo Starting Transit Comparator web app...
echo.
echo Server will start at http://localhost:5000
echo Press Ctrl+C to stop the server
echo.

py app.py

pause
