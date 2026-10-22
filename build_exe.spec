# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec — build a single standalone Document Organizer.exe that runs
WITHOUT Python installed on the target machine.

Build:  python -m PyInstaller build_exe.spec   (or double-click build_exe.bat)
Output: dist/Document Organizer.exe

Notes
  * onefile, windowed (no console).
  * Bundles read-only assets (card_template.png, fonts/) — the app reads them
    from sys._MEIPASS via app_paths.resource_dir().
  * The vault / settings / tokens are written next to the .exe via
    app_paths.state_dir(), so they persist (never the temp unpack dir).
  * collect_all() pulls data + hidden imports + binaries for the heavy packages
    that PyInstaller does not fully trace on its own.
"""

from PyInstaller.utils.hooks import collect_all

datas = [("card_template.png", "."), ("bible_key_template.png", "."),
         ("fonts", "fonts")]
binaries = []
hiddenimports = []

# Packages whose data files / dynamic libs / submodules must be collected.
for pkg in [
    "customtkinter", "tkinterdnd2", "pythainlp", "fitz", "cv2",
    "qrcode", "PIL", "argon2", "cryptography",
    "googleapiclient", "google_auth_oauthlib", "google_auth_httplib2",
    "google", "requests",
]:
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as exc:          # a missing optional package is not fatal
        print(f"[build_exe] skip {pkg}: {exc}")

# The .exe front door is the Health & Wellness cover app; it imports gui (the
# real vault) lazily, so make sure every local module is bundled.
hiddenimports += ["gui", "verse_card", "pdf_disguise", "drive_client",
                  "recipient_crypto", "file_crypto", "crypto_vault",
                  "secret_sharing", "vault", "qr_pointer", "make_portable",
                  "app_paths", "hidden_config", "pubkey_image", "machine_id",
                  "node_guard"]

a = Analysis(
    ["health_gate.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PyInstaller", "pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Health & Wellness",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                 # upx not required; avoids DLL-mangling surprises
    runtime_tmpdir=None,
    console=False,             # windowed: no console pops up
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="icon.ico",
)
