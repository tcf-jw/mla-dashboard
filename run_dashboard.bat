@echo off
REM Fallback launcher (shows a console window). For a window-less launch,
REM double-click "Launch Dashboard.vbs" instead.
REM Tops up the local data store first, then serves it. A refresh failure
REM (offline, API down) is non-fatal: the dashboard still starts on stored data.
cd /d "%~dp0"
set PYTHONPATH=src
python -m mla_dashboard.refresh
if errorlevel 1 echo WARNING: refresh failed, launching with stored data.
python -m streamlit run app.py
pause
