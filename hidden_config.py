"""
hidden_config.py — stores the cover app's secret-channel credentials so they can
be changed from a menu inside the vault instead of editing source code.

The Water Tracker's trigger value and the unlock password are kept as SALTED
SHA-256 hashes (never plaintext) in an innocuous-looking prefs file. The cover
app checks typed input against the hashes; a snoop reading the file sees only
random-looking values under bland keys, not the secrets themselves.

If nothing is configured yet, the cover app falls back to the constants defined
in health_gate.py, so it still works out of the box.
"""
from __future__ import annotations

import hashlib
import json
import secrets

import app_paths

# bland filename / keys so it doesn't advertise what it holds
PREFS = app_paths.state_dir() / "app_prefs.json"
_K_TRIGGER = "profile_id"        # looks like an app setting, is the trigger hash
_K_UNLOCK = "sync_token"         # looks like an app setting, is the unlock hash


def _hash(value: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{value}".encode("utf-8")).hexdigest()


def _load() -> dict:
    try:
        return json.loads(PREFS.read_text("utf-8"))
    except Exception:
        return {}


def _save(d: dict) -> None:
    try:
        PREFS.write_text(json.dumps(d, ensure_ascii=False, indent=2), "utf-8")
    except Exception:
        pass


def set_secret_channel(trigger: str, unlock: str) -> None:
    """Store salted hashes of the new trigger value and unlock password."""
    d = _load()
    st, su = secrets.token_hex(8), secrets.token_hex(8)
    d[_K_TRIGGER] = f"{st}${_hash(trigger, st)}"
    d[_K_UNLOCK] = f"{su}${_hash(unlock, su)}"
    _save(d)


def _verify(key: str, value: str):
    """Return True/False if a hash is stored for `key`, or None if not set."""
    rec = _load().get(key)
    if not rec or "$" not in rec:
        return None
    salt, h = rec.split("$", 1)
    return _hash(value, salt) == h


def verify_trigger(text: str):
    return _verify(_K_TRIGGER, (text or "").strip())


def verify_unlock(password: str):
    return _verify(_K_UNLOCK, password or "")


def is_configured() -> bool:
    d = _load()
    return bool(d.get(_K_TRIGGER) and d.get(_K_UNLOCK))
