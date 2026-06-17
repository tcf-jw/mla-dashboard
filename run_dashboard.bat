@echo off
REM Fallback launcher (shows a console window). For a window-less launch,
REM double-click "Launch Dashboard.vbs" instead.
cd /d "%~dp0"
python -m streamlit run app.py
pause
