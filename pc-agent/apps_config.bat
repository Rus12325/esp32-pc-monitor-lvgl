@echo off
rem Редактор кнопок быстрого запуска (apps.json). Обычные права, без UAC.
cd /d "%~dp0"
start "" "C:\Python314\pythonw.exe" apps_config.py
if errorlevel 1 start "" "C:\Python314\python.exe" apps_config.py
