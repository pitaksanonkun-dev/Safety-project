@echo off
REM Launch the vault GUI. Installs dependencies into the SAME interpreter that
REM runs the program, so "ModuleNotFoundError" cannot happen, and keeps this
REM window open so any error message stays readable.
cd /d "%~dp0"
echo Using Python:
python -c "import sys; print(sys.executable)"
echo.
echo Ensuring dependencies are installed...
python -m pip install -r requirements.txt -q
echo.
echo Starting Document Organizer...
python gui.py
echo.
echo ---- program exited (code %errorlevel%) ----
pause
