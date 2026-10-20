"""
vault_cli.py — Command-line front end for the encrypted vault.

Examples:
    python vault_cli.py init
    python vault_cli.py create-vault          # create a password slot/vault
    python vault_cli.py add  secret.pdf
    python vault_cli.py list
    python vault_cli.py get  <file_id> ./out
    python vault_cli.py remove <file_id>
    python vault_cli.py make-shares 2 3       # split DK: 2-of-3 recovery
    python vault_cli.py recover <vault_id> share1.hex share2.hex

The store lives in ./vault_store by default (override with --store PATH).
Passwords are read with getpass (never echoed, never passed on argv).
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

from vault import VaultStore


def _store(args) -> VaultStore:
    return VaultStore(args.store)


def _unlock(args):
    store = _store(args)
    if not store.config_path.exists():
        sys.exit("No store found. Run: vault_cli.py init")
    pw = getpass.getpass("Password: ")
    ov = store.unlock(pw)
    if ov is None:
        sys.exit("Unlocked nothing (wrong password or no matching slot).")
    return store, ov


def cmd_init(args):
    _store(args).init()
    print(f"Initialised store at {Path(args.store).resolve()}")


def cmd_create_vault(args):
    store = _store(args)
    store.init()
    pw = getpass.getpass("New vault password: ")
    pw2 = getpass.getpass("Confirm: ")
    if pw != pw2:
        sys.exit("Passwords do not match.")
    if not pw:
        sys.exit("Empty password refused.")
    ov = store.create_vault(pw)
    print(f"Created vault {ov.vault_id}")
    print("Tip: create a second vault with a different password as your decoy,")
    print("     and fill it with genuine, non-sensitive files you actually keep.")


def cmd_add(args):
    _, ov = _unlock(args)
    for f in args.files:
        fid = ov.add_file(f)
        print(f"added {f}  ->  {fid}")


def cmd_list(args):
    _, ov = _unlock(args)
    files = ov.list_files()
    if not files:
        print("(vault is empty)")
        return
    print(f"{'FILE ID':32}  {'SIZE':>10}  NAME")
    for f in files:
        print(f"{f['id']:32}  {f['size']:>10}  {f['name']}")


def cmd_get(args):
    _, ov = _unlock(args)
    out = ov.extract_file(args.file_id, args.out_dir)
    print(f"extracted -> {out}")


def cmd_remove(args):
    _, ov = _unlock(args)
    ov.remove_file(args.file_id)
    print(f"removed {args.file_id}")


def cmd_make_shares(args):
    _, ov = _unlock(args)
    shares = ov.export_recovery_shares(args.k, args.n)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Vault id for recovery: {ov.vault_id}")
    for idx, data in shares:
        p = out_dir / f"share_{idx}.hex"
        p.write_text(f"{idx}:{data.hex()}", "utf-8")
        print(f"  wrote {p}  (distribute this to a separate location)")
    print(f"Any {args.k} of {args.n} shares reconstruct the vault key.")


def cmd_recover(args):
    store = _store(args)
    shares = []
    for path in args.share_files:
        idx_str, hex_str = Path(path).read_text("utf-8").strip().split(":", 1)
        shares.append((int(idx_str), bytes.fromhex(hex_str)))
    ov = store.unlock_with_shares(args.vault_id, shares)
    print(f"Recovered vault {ov.vault_id} with {len(shares)} shares.")
    print(f"Files inside: {len(ov.list_files())}")
    print("Use 'list' / 'get' via a password, or re-wrap with a new password"
          " using the API (store.add_password).")


def main():
    p = argparse.ArgumentParser(description="Encrypted personal vault")
    p.add_argument("--store", default="vault_store", help="store directory")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init").set_defaults(func=cmd_init)
    sub.add_parser("create-vault").set_defaults(func=cmd_create_vault)

    a = sub.add_parser("add"); a.add_argument("files", nargs="+")
    a.set_defaults(func=cmd_add)

    sub.add_parser("list").set_defaults(func=cmd_list)

    g = sub.add_parser("get"); g.add_argument("file_id"); g.add_argument("out_dir")
    g.set_defaults(func=cmd_get)

    r = sub.add_parser("remove"); r.add_argument("file_id")
    r.set_defaults(func=cmd_remove)

    m = sub.add_parser("make-shares")
    m.add_argument("k", type=int); m.add_argument("n", type=int)
    m.add_argument("--out-dir", default="shares")
    m.set_defaults(func=cmd_make_shares)

    rc = sub.add_parser("recover")
    rc.add_argument("vault_id"); rc.add_argument("share_files", nargs="+")
    rc.set_defaults(func=cmd_recover)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
