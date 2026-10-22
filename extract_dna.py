"""
extract_dna.py — show THIS machine's DNA (MAC + Motherboard UUID -> SHA-256) and
save it to authorized_dna.json so you can review it.

This only READS hardware identifiers and writes a readable JSON. It performs no
destructive action of any kind. Pair it with the vault's "node-lock" feature
(Settings) to bind the vault to this machine; a wrong machine then simply cannot
decrypt (fail-closed), and the Backup keys still recover the data on new
hardware — nothing is ever wiped.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import machine_id

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

OUT = Path(__file__).resolve().parent / "authorized_dna.json"


def main() -> int:
    comp = machine_id.components()
    OUT.write_text(json.dumps(comp, ensure_ascii=False, indent=2), "utf-8")
    print("=== Machine DNA ===")
    print("SHA-256 :", comp["dna_sha256"])
    print("short   :", machine_id.machine_dna_short())
    print("MAC     :", comp["mac"])
    print("MB UUID :", comp["motherboard_uuid"])
    print("\nบันทึกไว้ที่:", OUT)
    print("หมายเหตุ: ไฟล์นี้เก็บแค่ค่า fingerprint เพื่อให้ตรวจดู ไม่ใช่ความลับ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
