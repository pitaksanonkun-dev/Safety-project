"""
app_paths.py — resolve paths correctly whether running as plain .py or as a
PyInstaller-built .exe.

Two very different kinds of path:

  resource_dir()  READ-ONLY bundled assets (fonts, card_template.png). In a
                  PyInstaller onefile .exe these are unpacked to a TEMPORARY
                  folder (sys._MEIPASS) on each run — fine for read-only data.

  state_dir()     PERSISTENT user state (vault_store/, app_settings.json,
                  drive_token.json, ...). This MUST survive between runs, so it
                  must NEVER be the temporary _MEIPASS folder. When frozen we use
                  the folder the .exe actually sits in; otherwise the source dir.

Getting this wrong in onefile mode would put the vault in a temp folder that
Windows wipes — i.e. silent data loss. Hence this single source of truth.
"""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_dir() -> Path:
    """Directory that holds bundled read-only assets."""
    if is_frozen():
        base = getattr(sys, "_MEIPASS", None)
        if base:
            return Path(base)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def state_dir() -> Path:
    """Directory for persistent user state; created if missing."""
    if is_frozen():
        d = Path(sys.executable).resolve().parent
    else:
        d = Path(__file__).resolve().parent
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return d
