# Document Organizer — Personal Encrypted Vault

An offline, local encrypted vault for protecting your own sensitive files.
Built on standard, auditable cryptography.

## What it does

- **AES-256-GCM** authenticated encryption for every file (tampering is detected).
- **Argon2id** password hashing / key derivation (memory-hard, ~0.5 s per attempt).
- **Envelope encryption (key wrapping):** your password unwraps a random
  per-vault *data key*; the data key encrypts files. Changing the password
  only re-wraps the key — your files are never re-encrypted.
- **Plausible deniability:** one password field, multiple vaults. Each password
  opens whichever vault it unlocks; a wrong password opens nothing. Give a
  *decoy* vault its own password and fill it with genuine, non-sensitive files.
- **Shamir's Secret Sharing** recovery: split the data key into `n` shares,
  any `k` of which rebuild it. Distribute shares across locations
  (disk / NAS / USB) so no single seized location holds a usable key.

## Files

| File | Purpose |
|------|---------|
| `crypto_vault.py`  | Argon2id KDF, AES-256-GCM, 512-byte metadata envelope |
| `secret_sharing.py`| Shamir's Secret Sharing over GF(256) |
| `vault.py`         | Vault engine: key hierarchy, password routing, index, files |
| `vault_cli.py`     | Command-line interface |
| `gui.py`           | CustomTkinter UI (login + file dashboard) |

Each module has a `__main__` self-test: `python vault.py`, `python secret_sharing.py`, etc.

## Install & run

```bash
pip install -r requirements.txt

# GUI
python gui.py

# CLI
python vault_cli.py init
python vault_cli.py create-vault
python vault_cli.py add  path/to/secret.pdf
python vault_cli.py list
python vault_cli.py get  <file_id> ./out
python vault_cli.py make-shares 2 3        # 2-of-3 recovery shares
python vault_cli.py recover <vault_id> shares/share_1.hex shares/share_3.hex
```

> On Windows, the CLI reads passwords interactively (getpass). Piping a
> password into it will not work — type it at the prompt.

## Forgotten / lost password — recovery

There is **no password backdoor** (by design — a backdoor would make the vault
insecure). Recovery works through **Shamir recovery shares** that you create
*while you still know the password*:

1. **Set up recovery in advance** — in the GUI, log in and click
   **"Backup key…"**, choose e.g. `2,3` (any 2 of 3 shares recover the key),
   and save the share files. **Store them in separate places** (different USB
   drives / locations); never keep `k` or more together.
   *(CLI equivalent: `vault_cli.py make-shares 2 3`.)*

2. **If you forget the password** — on the login screen press **`Ctrl+Shift+R`**
   to open *Recover access*, load your share files, and set a **new password**.
   The share files carry the vault id, so you don't need to remember it.
   *(CLI equivalent: `vault_cli.py recover <vault_id> share_1.hex share_3.hex`.)*

> If you never created shares and forget every password, the data is
> unrecoverable. Create the shares now, before you need them.

## Security notes (read these)

1. **Pair with full-disk encryption.** This vault protects individual files,
   but true "an examiner cannot even prove a hidden vault exists" deniability
   needs full-disk/hidden-container encryption underneath (BitLocker on
   Windows, or VeraCrypt). On a plain filesystem the number of password slots
   and the blob directories are visible. Turn on FDE for a serious threat model.

2. **Secure deletion is unreliable on SSD/NVMe.** Overwriting a file does not
   guarantee erasure because of wear-leveling and over-provisioning — the old
   data can survive in spare cells. The dependable approach is to encrypt from
   the start (this vault + FDE) so unencrypted data never hits the disk; then
   "wiping" is just deleting a key.

3. **Back up your shares and passwords.** There is no recovery backdoor. If you
   lose every password *and* fewer than `k` Shamir shares remain, the data is
   gone. That is the point — but it cuts both ways.

4. **Keep the store and your backups on media you control.** If you sync shares
   to a cloud account, use *your own* account, and remember a single location
   should never hold `k` or more shares.

## Intentionally NOT included

This build does not implement anti-forensic behaviour that exists to deceive an
investigation rather than protect your data:

- No metadata/timestamp falsification ("timestomping") of decoy files. A decoy
  vault should hold real, innocuous files you actually keep — their timestamps
  are naturally genuine and need no faking.
- No automatic destructive "duress wipe" or covert exfiltration wired to a
  password. Back up and delete *your own* data deliberately instead.

The encryption, deniability, and recovery features above already give you
strong protection without fabricating evidence or auto-destroying data.
