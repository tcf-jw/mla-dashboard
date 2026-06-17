@echo off
REM Run this ONCE on first setup to pull all available history.
REM Shows progress; afterwards use "Refresh Data.vbs" for quick incremental updates.
cd /d "%~dp0"
set PYTHONPATH=src
python -m mla_dashboard.refresh --backfill
pause
