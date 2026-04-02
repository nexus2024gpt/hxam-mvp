@echo off
title HX-AM Proxy Stopper
echo ============================================================
echo   Hybrid-X Anomaly Miner (HX-AM) Proxy v3.4
echo   Stopping server...
echo ============================================================
echo.

set "FOUND=0"
for /f "tokens=2 delims=," %%A in ('tasklist /fi "imagename eq python.exe" /fo csv /nh 2^>nul') do (
    set "pid=%%~A"
    wmic process where "ProcessId=%%~A" get CommandLine /format:value 2>nul | findstr /i "proxy_server.py" >nul
    if not errorlevel 1 (
        echo Found proxy_server.py with PID: %%~A
        taskkill /F /PID %%~A >nul 2>&1
        echo [OK] Process terminated.
        set "FOUND=1"
        goto :stopped
    )
)

:stopped
if "%FOUND%"=="0" (
    echo [WARNING] No running proxy_server.py found.
)
echo.
echo HX-AM Proxy stopped.
pause
