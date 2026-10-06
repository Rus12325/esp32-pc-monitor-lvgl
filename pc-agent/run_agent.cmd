@echo off
rem Тихий запуск агента (для задачи планировщика). Без консоли, без UAC
rem (повышение даёт сам таск с флагом HighestAvailable).
cd /d "%~dp0"
taskkill /F /IM python.exe >nul 2>&1
taskkill /F /IM pythonw.exe >nul 2>&1
start "" "C:\Python314\pythonw.exe" -u pc_agent.py
