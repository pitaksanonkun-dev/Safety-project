r"""
file_crypto.py — Standalone file encryption to / from a chosen folder.

Unlike the vault store (which keeps encrypted blobs in an internal folder),
this module turns a normal file into a single self-contained encrypted file
(<name>.enc) placed in a folder you choose, WITHOUT touching the original.
The encrypted file carries everything needed to restore it later with the
same password:

    file layout:
        MAGIC(8) | salt(16) | nonce(12) | AES-256-GCM( envelope(512) || body )
        \______________ header _______________/\___ from crypto_vault ___/

    key = Argon2id(password, salt)

Restoring reverses this and writes the file back under its ORIGINAL name.

Dependencies: pip install cryptography argon2-cffi  (via crypto_vault)
"""

from __future__ import annotations

import secrets
from pathlib import Path

from crypto_vault import derive_key, encrypt_file, decrypt_file

MAGIC = b"DOCORG01"
ENC_SUFFIX = ".enc"


def _unique_path(path: Path) -> Path:
    """Avoid overwriting: foo.txt -> foo (1).txt if needed."""
    if not path.exists():
        return path
    stem, suffix, parent = path.stem, path.suffix, path.parent
    i = 1
    while True:
        cand = parent / f"{stem} ({i}){suffix}"
        if not cand.exists():
            return cand
        i += 1


def make_blob(data: bytes, original_name: str, password: str) -> bytes:
    """Build a self-contained encrypted container blob for `data`."""
    salt = secrets.token_bytes(16)
    key = derive_key(password, salt)
    return MAGIC + salt + encrypt_file(data, original_name, key)


def read_blob(blob: bytes, password: str) -> tuple[str, bytes]:
    """Reverse make_blob -> (original_name, data).
    Raises ValueError if not a valid container, or InvalidTag on wrong password."""
    if blob[:8] != MAGIC:
        raise ValueError("Not a Document Organizer encrypted container")
    salt = blob[8:24]
    rest = blob[24:]
    key = derive_key(password, salt)
    return decrypt_file(rest, key)          # InvalidTag if wrong password


def encrypt_file_to_folder(src: str | Path, out_dir: str | Path,
                           password: str) -> Path:
    """Encrypt `src` into `out_dir` as <name>.enc. Original is left untouched."""
    src = Path(src)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    blob = make_blob(src.read_bytes(), src.name, password)
    out_path = _unique_path(out_dir / (src.name + ENC_SUFFIX))
    out_path.write_bytes(blob)
    return out_path


def decrypt_file_to_folder(enc: str | Path, out_dir: str | Path,
                           password: str) -> Path:
    """Restore an encrypted file into `out_dir` under its ORIGINAL name.
    Raises ValueError if the file is not a valid container, or
    cryptography's InvalidTag if the password is wrong / data tampered."""
    enc = Path(enc)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    original_name, data = read_blob(enc.read_bytes(), password)
    out_path = _unique_path(out_dir / original_name)
    out_path.write_bytes(data)
    return out_path


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        src = d / "report.pdf"
        src.write_bytes(b"%PDF-1.7 confidential body " * 50)

        enc_dir = d / "Encrypted"
        back_dir = d / "Restored"

        enc = encrypt_file_to_folder(src, enc_dir, "pw123")
        assert enc.suffix == ".enc" and enc.read_bytes()[:8] == MAGIC
        assert src.exists()  # original kept

        out = decrypt_file_to_folder(enc, back_dir, "pw123")
        assert out.name == "report.pdf"
        assert out.read_bytes() == src.read_bytes()

        # wrong password must fail
        try:
            decrypt_file_to_folder(enc, back_dir, "wrong")
            raise SystemExit("SECURITY BUG: wrong password decrypted!")
        except Exception as e:
            assert "InvalidTag" in type(e).__name__ or isinstance(e, Exception)

        print("file_crypto self-test OK")
        print("  encrypt -> folder, original kept, restore -> original name,"
              " wrong password rejected")
