# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec — build a single self-contained installer:
    dist/PC Health & Wellness Setup.exe

It bundles the already-built program (dist/Health & Wellness.exe) as a payload
and, at run time, the GUI wizard copies it to the folder the user chooses.

Build the program FIRST (build_exe.spec), then:
    python -m PyInstaller build_installer.spec
"""
from PyInstaller.utils.hooks import collect_all

datas = [("dist/Health & Wellness.exe", ".")]     # payload -> _MEIPASS root
binaries = []
hiddenimports = ["machine_id"]

for pkg in ["customtkinter"]:
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as exc:
        print(f"[build_installer] skip {pkg}: {exc}")

a = Analysis(
    ["installer.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PyInstaller", "pytest", "cv2", "fitz", "pythainlp",
              "googleapiclient", "numpy"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PC Health & Wellness Setup",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="icon.ico",
)
