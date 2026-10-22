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

import sys

import app_paths
import machine_id

GUARD_NAME = "node_authorized.json"
DNA_MAGIC = b"DOCORGDNA1"          # marks the DNA binding appended inside the .exe


def guard_file() -> Path | None:
    """The guard file beside the installed .exe (only meaningful when frozen)."""
    if not app_paths.is_frozen():
        return None
    return app_paths.exe_dir() / GUARD_NAME


def _file_authorized(path: Path | None = None):
    """Authorised DNAs from the (deletable) node_authorized.json, if present."""
    p = path or guard_file()
    if not p or not p.exists():
        return set()
    try:
        data = json.loads(p.read_text("utf-8"))
        return {h.lower() for h in (data.get("authorized") or []) if h}
    except Exception:
        return set()


# --- DNA binding embedded INSIDE the .exe (can't be bypassed by deleting a file) ---
# Trailer layout, appended to the very end of the exe:
#   DNA_MAGIC | json | len(json, 4 bytes big-endian) | DNA_MAGIC
def _read_exe_trailer(exe_path):
    try:
        with open(exe_path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            n = min(size, 65536)
            f.seek(size - n)
            tail = f.read(n)
    except Exception:
        return set()
    if tail[-len(DNA_MAGIC):] != DNA_MAGIC:
        return set()
    try:
        ln = int.from_bytes(tail[-len(DNA_MAGIC) - 4:-len(DNA_MAGIC)], "big")
        end = len(tail) - len(DNA_MAGIC) - 4
        data = tail[end - ln:end]
        if tail[end - ln - len(DNA_MAGIC):end - ln] != DNA_MAGIC:
            return set()
        return {h.lower() for h in json.loads(data).get("authorized", []) if h}
    except Exception:
        return set()


def embedded_authorized():
    """Authorised DNAs embedded in THIS running .exe (frozen only)."""
    if not app_paths.is_frozen():
        return set()
    return _read_exe_trailer(sys.executable)


def embed_into_exe(exe_path, authorized: list[str]) -> None:
    """Append a DNA binding to an .exe so the lock can't be removed by deleting a
    separate file. (Appending leaves the PyInstaller archive readable.)"""
    data = json.dumps({"authorized": sorted({h.lower() for h in authorized if h})}
                      ).encode("utf-8")
    with open(exe_path, "ab") as f:
        f.write(DNA_MAGIC + data + len(data).to_bytes(4, "big") + DNA_MAGIC)


def authorized_set(path: Path | None = None):
    """Union of DNAs bound via the embedded trailer AND the json file; None if the
    install carries no binding at all."""
    s = embedded_authorized() | _file_authorized(path)
    return s or None


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
