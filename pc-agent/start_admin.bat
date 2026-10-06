@echo off
REM pc-agent launcher: сам поднимает права администратора (для температуры CPU
REM через драйвер LHM) и запускает агента. Перед стартом снимает обычные копии.
title PC-agent (ESP32 panel)

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [i] Запрашиваю права администратора...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

REM закрыть все python-агенты (чтобы не спорили за COM-порт)
taskkill /F /IM python.exe >nul 2>&1

cd /d "%~dp0"
echo [i] Агента запускаю из: %CD%
C:\Python314\python.exe -u pc_agent.py
pause
