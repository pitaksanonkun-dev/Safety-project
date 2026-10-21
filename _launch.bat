@echo off
REM Hidden launcher helper — called by "Document Organizer.vbs".
REM Runs through cmd so it resolves Python exactly like run_gui.bat does
REM (including the Microsoft Store alias, which wscript cannot launch directly).
REM Installs dependencies only if something is missing, then starts the app.
REM The VBS runs this with a hidden window, so no console is visible even though
REM we use python.exe (the app's own GUI window still appears normally).
cd /d "%~dp0"

python -c "import customtkinter, tkinterdnd2, fitz, cv2, qrcode, pythainlp, google.oauth2, google_auth_oauthlib, argon2, cryptography, PIL" 1>nul 2>nul
if errorlevel 1 python -m pip install -r requirements.txt

REM Front door is the Health & Wellness cover app; the vault opens only via the
REM hidden side-channel inside it.
python health_gate.py
