@echo off
REM Build a standalone Document Organizer.exe (no Python needed on target).
REM Needs PyInstaller: pip install pyinstaller
cd /d "%~dp0"
python -c "import PyInstaller" 1>nul 2>nul || python -m pip install pyinstaller
python -m PyInstaller --noconfirm --clean build_exe.spec
echo.
echo ==== Done. The .exe is in the "dist" folder. ====
pause
