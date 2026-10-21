"""
app_paths.py — resolve paths correctly whether running as plain .py or as a
PyInstaller-built .exe.

Two very different kinds of path:

  resource_dir()  READ-ONLY bundled assets (fonts, card_template.png). In a
                  PyInstaller onefile .exe these are unpacked to a TEMPORARY
                  folder (sys._MEIPASS) on each run — fine for read-only data.

  state_dir()     PERSISTENT user state (vault_store/, app_settings.json,
                  drive_token.json, ...). This MUST survive between runs, so it
                  must NEVER be the temporary _MEIPASS folder.

                  For a built .exe it lives in a PER-USER folder under
                  %LOCALAPPDATA% — deliberately NOT next to the .exe — so that
                  giving the .exe (or even its whole folder) to someone else
                  never carries your vault/login along, and every Windows user /
                  machine gets their own independent vault. For plain .py it is
                  the source folder (developer convenience).

Getting this wrong in onefile mode would put the vault in a temp folder that
Windows wipes — i.e. silent data loss. Hence this single source of truth.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_FOLDER = "HealthWellness"       # per-user state folder name under LOCALAPPDATA


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


def exe_dir() -> Path:
    """Folder the .exe sits in (used only for one-time migration)."""
    return Path(sys.executable).resolve().parent


def state_dir() -> Path:
    """Directory for persistent user state; created if missing."""
    if is_frozen():
        base = (os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
                or str(Path.home()))
        d = Path(base) / APP_FOLDER
    else:
        d = Path(__file__).resolve().parent
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return d
