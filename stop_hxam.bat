@echo off
echo Остановка HX-AM MVP сервера...
taskkill /F /FI "WINDOWTITLE eq Hybrid-X*" /T >nul 2>&1
taskkill /F /IM python.exe /FI "WINDOWTITLE eq *hxam*" /T >nul 2>&1
echo [OK] Сервер остановлен
pause
