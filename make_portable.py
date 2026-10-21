"""
make_portable.py — build a CLEAN, shareable copy of the program for another
machine, WITHOUT any of your personal state or secrets.

Why this exists:
  The vault, login/private key, Google Drive token, settings and contacts all
  live in this folder (vault_store/, app_settings.json, drive_token.json, ...).
  If you just copy the whole folder to someone else, you hand them YOUR identity.
  This tool copies only the program itself — code, assets, launchers, manuals —
  so the destination machine starts fresh: on first login it creates its OWN
  vault and its OWN unique recipient keypair, fully independent from yours.

Output:
  <parent>/Document Organizer (portable) <timestamp>/      a clean folder
  <parent>/Document Organizer (portable) <timestamp>.zip   zipped, ready to send

Run:  python make_portable.py            (or double-click make_portable.bat)
"""

from __future__ import annotations

import fnmatch
import shutil
import sys
from datetime import datetime
from pathlib import Path

# The Windows console may be cp874/cp1252 and choke on Thai; force UTF-8 output.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SRC = Path(__file__).resolve().parent

# Non-.py files that SHOULD travel with the program (assets / launchers / docs).
INCLUDE_FILES = [
    "requirements.txt", "README.md", ".gitignore", "card_template.png",
    "run_gui.bat", "_launch.bat", "Document Organizer.vbs", "make_portable.py",
    "make_portable.bat",
    "คู่มือการใช้งาน-Document-Organizer.pdf",
    "คู่มือสร้าง-Google-Drive-API.pdf",
]
INCLUDE_DIRS = ["fonts"]            # bundled TH Sarabun fonts, etc.

# Anything matching these is PER-USER STATE or a SECRET and must never ship.
# (Belt-and-suspenders: *.py are whitelisted by glob and none of these are .py,
#  but we still refuse to copy a file whose name matches, just in case.)
DENY = [
    "vault_store", "vault_store_*", "vault.json",
    "app_settings.json", "*.seed", "recovery_key_*.json",
    "drive_token.json", "*token*.json",
    "client_secret*", "*client_secret*", "*service*account*.json", "*oauth*.json",
    "*.url", "_card_preview.png", "error.log",
    "__pycache__", ".git", "*.zip",
]


def _denied(name: str) -> bool:
    return any(fnmatch.fnmatch(name, pat) for pat in DENY)


def build_portable(src_dir=None, out_parent=None, make_zip: bool = True) -> dict:
    """Build a clean copy of the program. Returns a dict with keys:
    folder, zip, copied (list), leaked (list). Safe to call from the GUI."""
    src = Path(src_dir).resolve() if src_dir else SRC
    parent = Path(out_parent).resolve() if out_parent else src.parent
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = parent / f"Document Organizer (portable) {stamp}"
    dest.mkdir(parents=True, exist_ok=False)

    copied = []

    # 1) every Python module in the top folder (so new code is never forgotten)
    for p in sorted(src.glob("*.py")):
        if _denied(p.name):
            continue
        shutil.copy2(p, dest / p.name)
        copied.append(p.name)

    # 2) explicit non-.py files that exist
    for name in INCLUDE_FILES:
        if name.endswith(".py") or _denied(name):
            continue                       # .py already handled by the glob
        if (src / name).exists():
            shutil.copy2(src / name, dest / name)
            copied.append(name)

    # 3) whitelisted asset directories (filtered against DENY as a safety net)
    for dname in INCLUDE_DIRS:
        if (src / dname).is_dir():
            shutil.copytree(
                src / dname, dest / dname,
                ignore=lambda _d, names: [n for n in names if _denied(n)])
            copied.append(dname + "\\")

    # 4) SAFETY NET — scan the finished copy for anything secret that slipped in
    leaked = [p for p in dest.rglob("*") if p.is_file() and _denied(p.name)]
    for p in leaked:
        try:
            p.unlink()
        except Exception:
            pass

    # 5) zip it for easy sending
    archive = None
    if make_zip:
        archive = shutil.make_archive(str(dest), "zip", root_dir=dest.parent,
                                      base_dir=dest.name)

    return {"folder": str(dest), "zip": archive,
            "copied": copied, "leaked": [p.name for p in leaked]}


def main() -> int:
    info = build_portable()
    print("สร้างชุดแจกจ่ายสะอาดเรียบร้อย\n")
    print("โฟลเดอร์:", info["folder"])
    print("ไฟล์ zip :", info["zip"])
    print(f"\nรวมไฟล์ {len(info['copied'])} รายการ:")
    for n in info["copied"]:
        print("   +", n)
    if info["leaked"]:
        print("\n⚠️  ตรวจพบและลบไฟล์ลับที่หลุดเข้ามาออกแล้ว:",
              ", ".join(info["leaked"]))
    print("\nสิ่งที่ 'ไม่' ถูกใส่ไป (เพื่อความเป็นอิสระ/ปลอดภัย): vault_store, "
          "app_settings.json, drive_token.json, client_secret*, *.seed, "
          "ไฟล์สำรอง และ __pycache__")
    print("\nนำโฟลเดอร์หรือ zip นี้ไปเครื่องอื่นได้เลย — เครื่องนั้นจะสร้าง vault "
          "และกุญแจของตัวเองใหม่ตอน login ครั้งแรก เป็นอิสระจากเครื่องคุณ")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("สร้างชุดแจกจ่ายไม่สำเร็จ:", exc)
        sys.exit(1)
