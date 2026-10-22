"""
node_guard.py — optional launch gate that binds an installed copy to one or more
authorised machines (by Machine DNA).

If a `node_authorized.json` file sits next to the installed .exe, the program
only starts on a machine whose DNA is listed. On any other machine it shows a
message and exits (fail-closed) — it NEVER deletes or overwrites anything.

This is an access gate, not cryptography (the file could be removed to bypass
it). The strong, tamper-proof binding is the vault's own node-lock (which mixes
the DNA into the key derivation). Use both together for defence in depth.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import app_paths
import machine_id

GUARD_NAME = "node_authorized.json"


def guard_file() -> Path | None:
    """The guard file beside the installed .exe (only meaningful when frozen)."""
    if not app_paths.is_frozen():
        return None
    return app_paths.exe_dir() / GUARD_NAME


def authorized_set(path: Path | None = None):
    p = path or guard_file()
    if not p or not p.exists():
        return None
    try:
        data = json.loads(p.read_text("utf-8"))
    except Exception:
        return None
    hashes = {h.lower() for h in (data.get("authorized") or []) if h}
    return hashes or None


def write_guard(dest_dir, authorized: list[str], note: str = "") -> Path:
    """Write node_authorized.json into an install directory."""
    out = Path(dest_dir) / GUARD_NAME
    out.write_text(json.dumps({
        "authorized": sorted({h.lower() for h in authorized if h}),
        "note": note,
        "created": datetime.now().isoformat(timespec="seconds"),
    }, ensure_ascii=False, indent=2), "utf-8")
    return out


def check() -> bool:
    """True if allowed to run (no guard, or this machine is authorised)."""
    allowed = authorized_set()
    if allowed is None:
        return True
    return machine_id.machine_dna().lower() in allowed


def enforce_or_exit() -> None:
    """Fail-closed: if a guard is present and this machine isn't authorised, show
    a message and exit. No data is touched."""
    if check():
        return
    try:
        from tkinter import Tk, messagebox
        r = Tk(); r.withdraw()
        messagebox.showerror(
            "Setup",
            "Error: Incompatible system architecture.\n\n"
            "โปรแกรมนี้ถูกผูกกับเครื่องที่ได้รับอนุญาตเท่านั้น "
            "ไม่สามารถใช้งานบนเครื่องนี้ได้")
        r.destroy()
    except Exception:
        pass
    import sys
    sys.exit(1)
