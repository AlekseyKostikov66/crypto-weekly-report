@echo off
REM Локальный запуск скрипта (для отладки).
REM Требуется .env с токенами в той же папке.

cd /d "%~dp0"
python crypto_weekly_report.py
pause
