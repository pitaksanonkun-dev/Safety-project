"""
check_password.py — diagnose a login problem by testing a password VISIBLY
against your real vault_store (read-only; it never changes your vault).

Run it from the program folder, passing your password as an argument:

    python check_password.py "YourPasswordHere"

It prints whether the password unlocks the vault, and shows exactly what
characters it received (to catch a Thai-keyboard / Caps-Lock / stray-space
problem that the dotted password box hides).
"""

import sys
from pathlib import Path

from vault import VaultStore

STORE_DIR = str(Path(__file__).resolve().parent / "vault_store")


def main():
    if len(sys.argv) > 1:
        pw = sys.argv[1]
    else:
        pw = input("Type the password to test: ")

    store = VaultStore(STORE_DIR)
    if not Path(store.config_path).exists():
        print("No vault_store found next to this script.")
        return
    cfg = store._read_config()
    n_slots = len(cfg.get("slots", []))

    print(f"vault_store: {STORE_DIR}")
    print(f"password slots in vault: {n_slots}")
    print(f"you typed {len(pw)} characters: {pw!r}")
    # flag common hidden problems
    if pw != pw.strip():
        print("  ! WARNING: there is a leading/trailing SPACE in what you typed.")
    if any('฀' <= c <= '๿' for c in pw):
        print("  ! WARNING: it contains THAI characters — your keyboard may be in Thai mode.")

    ov = store.unlock(pw)
    print("RESULT:", "UNLOCK OK - this password is correct" if ov
          else "WRONG PASSWORD - does not match any slot")


if __name__ == "__main__":
    main()
