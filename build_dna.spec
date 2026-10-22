# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec — build the standalone Machine DNA tool:
    dist/DNA Collector.exe

Run it on the machine you want to authorise; it shows the DNA and exports
authorized_dna.json for the installer's "import DNA" step.

    python -m PyInstaller build_dna.spec
"""
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = ["machine_id"]

for pkg in ["customtkinter"]:
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as exc:
        print(f"[build_dna] skip {pkg}: {exc}")

a = Analysis(
    ["dna_tool.py"],
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
    pyz, a.scripts, a.binaries, a.datas, [],
    name="DNA Collector",
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    runtime_tmpdir=None, console=False, disable_windowed_traceback=False,
    target_arch=None, codesign_identity=None, entitlements_file=None,
    icon="icon.ico",
)
