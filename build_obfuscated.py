"""
build_obfuscated.py — build Health & Wellness.exe with the CRYPTO/decrypt modules
obfuscated by PyArmor, while the (large) UI modules stay as-is.

Only the sensitive logic (AES, Argon2id, envelope/key-wrap, recipient-key, Shamir,
node-lock, machine DNA, hidden-channel) is obfuscated, so an adversary who unpacks
the exe cannot easily read how encryption / node-lock work. (The data is still
protected by the crypto itself regardless — this only raises the bar for RE.)

Steps:
  1. stage all project .py + assets into a build dir
  2. PyArmor-obfuscate the SENS modules and drop in pyarmor_runtime
  3. run PyInstaller (reusing build_exe.spec) from the staged dir

Usage:  python build_obfuscated.py
Needs:  pyarmor (pip install pyarmor), pyinstaller, and build_exe.spec present.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STAGE = HERE / "_obf_src"
OBF = HERE / "_obf_only"

SENS = ["crypto_vault.py", "vault.py", "file_crypto.py", "recipient_crypto.py",
        "secret_sharing.py", "node_guard.py", "machine_id.py", "hidden_config.py"]

ASSETS = ["fonts", "card_template.png", "bible_key_template.png", "icon.ico",
          "requirements.txt"]

SKIP_PY = {"build_obfuscated.py"}          # don't stage this build script itself


def _pyarmor() -> str:
    exe = shutil.which("pyarmor")
    if exe:
        return exe
    for base in (os.environ.get("LOCALAPPDATA", ""),):
        hit = list(Path(base).rglob("Scripts/pyarmor.exe")) if base else []
        if hit:
            return str(hit[0])
    raise SystemExit("ไม่พบ pyarmor — ติดตั้งด้วย: pip install pyarmor")


def main() -> int:
    pa = _pyarmor()
    for d in (STAGE, OBF):
        if d.exists():
            shutil.rmtree(d)
    STAGE.mkdir(parents=True)

    # 1) stage every .py + assets
    for p in HERE.glob("*.py"):
        if p.name not in SKIP_PY:
            shutil.copy2(p, STAGE / p.name)
    for a in ASSETS:
        src = HERE / a
        if src.is_dir():
            shutil.copytree(src, STAGE / a)
        elif src.exists():
            shutil.copy2(src, STAGE / a)

    # 2) obfuscate the sensitive modules, then overlay them + the runtime
    print("[obf] obfuscating:", ", ".join(SENS))
    subprocess.run([pa, "gen", "-O", str(OBF), *SENS], cwd=str(HERE), check=True)
    for name in SENS:
        shutil.copy2(OBF / name, STAGE / name)          # obfuscated over plaintext
    rt = next(OBF.glob("pyarmor_runtime_*"))
    shutil.copytree(rt, STAGE / rt.name)
    print("[obf] runtime:", rt.name)

    # 3) stage a spec that bundles the pyarmor runtime and searches the stage dir
    spec = (HERE / "build_exe.spec").read_text("utf-8")
    spec = spec.replace("pathex=[],", "pathex=['.'],")
    spec = spec.replace('"app_paths", "hidden_config"',
                        f'"app_paths", "hidden_config", "{rt.name}"')
    (STAGE / "build_exe.spec").write_text(spec, "utf-8")

    print("[build] running PyInstaller from the obfuscated stage…")
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
         "build_exe.spec", "--distpath", str(HERE / "dist"),
         "--workpath", str(HERE / "build")],
        cwd=str(STAGE), check=True)
    print("\nDONE -> dist/Health & Wellness.exe (crypto modules obfuscated)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
