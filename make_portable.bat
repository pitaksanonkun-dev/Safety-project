@echo off
REM Build a clean, shareable copy of the program (no vault / token / settings).
REM Double-click this, then send the resulting .zip to the other machine.
cd /d "%~dp0"
python make_portable.py
echo.
pause
