"""
machine_id.py — a stable per-machine fingerprint ("DNA") from the MAC address
and the motherboard (SMBIOS) UUID, hashed with SHA-256.

Used for OPTIONAL node-locking: the vault can mix this DNA into its key
derivation so the data only decrypts on the authorised machine. Nothing is ever
destroyed — a wrong machine simply cannot derive the key (fail-closed), and the
Backup (Shamir) keys still recover the vault on new hardware.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
import uuid

_NO_WINDOW = 0x08000000 if sys.platform.startswith("win") else 0


def _mac() -> str:
    return "%012x" % uuid.getnode()


def _run(cmd) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10,
                              creationflags=_NO_WINDOW).stdout or ""
    except Exception:
        return ""


def _motherboard_uuid() -> str:
    if sys.platform.startswith("win"):
        out = _run(["powershell", "-NoProfile", "-Command",
                    "(Get-CimInstance -ClassName Win32_ComputerSystemProduct).UUID"])
        if not out.strip():
            out = _run(["wmic", "csproduct", "get", "uuid"])
        for line in out.splitlines():
            s = line.strip()
            if s and s.lower() != "uuid" and len(s) >= 8:
                return s
    else:
        for p in ("/sys/class/dmi/id/product_uuid", "/etc/machine-id"):
            try:
                from pathlib import Path
                v = Path(p).read_text().strip()
                if v:
                    return v
            except Exception:
                continue
    return ""


def machine_dna() -> str:
    """SHA-256 hex of (MAC | Motherboard UUID)."""
    raw = f"{_mac()}|{_motherboard_uuid()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def machine_dna_short() -> str:
    h = machine_dna()[:12].upper()
    return f"{h[:4]}-{h[4:8]}-{h[8:12]}"


def components() -> dict:
    return {"mac": _mac(),
            "motherboard_uuid": _motherboard_uuid(),
            "dna_sha256": machine_dna()}


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    c = components()
    print("Machine DNA (SHA-256):", c["dna_sha256"])
    print("  short:", machine_dna_short())
    print("  MAC  :", c["mac"])
    print("  Motherboard UUID:", c["motherboard_uuid"])
