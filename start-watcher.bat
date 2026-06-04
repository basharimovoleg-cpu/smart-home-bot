@echo off
title Sisyphus Watcher
if "%~1"=="" (
    echo Usage: start-watcher.bat ^<TUNNEL_URL^>
    echo Example: start-watcher.bat https://xxx.trycloudflare.com
    pause
    exit /b 1
)
set TUNNEL_URL=%~1
echo ========================================
echo   Sisyphus Watcher — запуск...
echo   PowerShell окно откроется через 2 сек
echo   URL: %TUNNEL_URL%
echo ========================================
timeout /t 2 /nobreak >nul
powershell -ExecutionPolicy Bypass -File "%~dp0watch.ps1" -Url "%TUNNEL_URL%"
pause
