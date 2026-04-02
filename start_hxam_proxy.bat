@echo off
title HX-AM Proxy Server
echo ============================================================
echo   Hybrid-X Anomaly Miner (HX-AM) Proxy v3.4
echo   Starting AI proxy...
echo ============================================================
echo.

D:
cd D:\Projects\hxam-mvp

if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
    echo [OK] Virtual environment activated
) else (
    echo [ERROR] .venv not found!
    pause
    exit /b 1
)

echo [OK] Starting server...
echo.
echo Server available at: http://localhost:8000
echo Press Ctrl+C to stop.
echo.

python proxy_server.py

pause
