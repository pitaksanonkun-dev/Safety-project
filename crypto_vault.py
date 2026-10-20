"""
crypto_vault.py — Core encryption primitives for a personal encrypted vault.

Scope (legitimate personal data protection):
  - Argon2id password -> key derivation
  - Password routing (real vault vs. decoy vault) for plausible deniability
  - AES-256-GCM authenticated encryption
  - A fixed 512-byte metadata "envelope" so an encrypted blob does not leak
    the original file type/extension.

Dependencies:
    pip install cryptography argon2-cffi
"""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass

from argon2.low_level import Type, hash_secret_raw
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# --- Argon2id parameters (tune to your hardware; higher = slower = stronger) --
_ARGON_TIME_COST = 4
_ARGON_MEMORY_COST = 512 * 1024  # 512 MiB
_ARGON_PARALLELISM = 4
_KEY_LEN = 32                    # 256-bit key for AES-256

METADATA_BOX_SIZE = 512
HEADER_CAPTURE_LEN = 32          # bytes of original header stored for restore


def derive_key(password: str, salt: bytes) -> bytes:
    """Derive a 256-bit key from a password with Argon2id."""
    return hash_secret_raw(
        secret=password.encode("utf-8"),
        salt=salt,
        time_cost=_ARGON_TIME_COST,
        memory_cost=_ARGON_MEMORY_COST,
        parallelism=_ARGON_PARALLELISM,
        hash_len=_KEY_LEN,
        type=Type.ID,
    )


# --- Password routing: plausible deniability -------------------------------
# One password field, two (or more) valid vaults. The entered password is
# hashed and compared against stored verifier hashes to pick which vault's
# key material to unlock. A wrong password matches nothing. This is the same
# idea as a VeraCrypt hidden volume: the decoy vault should hold *genuine*
# innocuous files you really keep, so it stands on its own.

@dataclass
class VaultRoute:
    name: str          # e.g. "real" or "decoy"
    salt: bytes
    key: bytes


def open_vault(password: str, vault_salts: dict[str, bytes]) -> VaultRoute | None:
    """
    Given the entered password and a map of {vault_name: salt}, derive the key
    for each configured vault. Return the route whose derived key successfully
    authenticates against that vault's data (see decrypt_blob raising on a bad
    key). Caller decides how to probe; here we just hand back derived keys.
    """
    for name, salt in vault_salts.items():
        key = derive_key(password, salt)
        # The actual "does this key work?" test happens when you try to decrypt
        # that vault's index with AES-GCM: a wrong key fails the auth tag.
        yield VaultRoute(name=name, salt=salt, key=key)


# --- Metadata envelope -----------------------------------------------------

def build_envelope(original_name: str, header: bytes) -> bytes:
    """Pack original filename + captured header into a fixed 512-byte box."""
    meta = {
        "v": 1,
        "name": original_name,
        "ext": os.path.splitext(original_name)[1],
        "header_hex": header.hex(),
        "header_len": len(header),
    }
    raw = json.dumps(meta, ensure_ascii=False).encode("utf-8")
    if len(raw) > METADATA_BOX_SIZE:
        raise ValueError("Metadata too large for 512-byte box")
    return raw + b"\0" * (METADATA_BOX_SIZE - len(raw))


def parse_envelope(box: bytes) -> dict:
    """Read a 512-byte metadata box back into a dict."""
    raw = box[:METADATA_BOX_SIZE].rstrip(b"\0")
    return json.loads(raw.decode("utf-8"))


# --- Authenticated encryption ----------------------------------------------

def encrypt_file(plaintext: bytes, original_name: str, key: bytes) -> bytes:
    """
    Produce a self-describing encrypted blob:
        nonce(12) || AES-256-GCM( envelope(512) || body )
    where body is the file content with its first 32 header bytes relocated
    into the envelope. Everything is under the GCM auth tag, so tampering is
    detected on decrypt.
    """
    header = plaintext[:HEADER_CAPTURE_LEN]
    body = plaintext[HEADER_CAPTURE_LEN:]
    envelope = build_envelope(original_name, header)

    nonce = secrets.token_bytes(12)
    aes = AESGCM(key)
    sealed = aes.encrypt(nonce, envelope + body, associated_data=None)
    return nonce + sealed


def decrypt_file(blob: bytes, key: bytes) -> tuple[str, bytes]:
    """Reverse encrypt_file. Raises if key is wrong or data was tampered."""
    nonce, sealed = blob[:12], blob[12:]
    aes = AESGCM(key)
    opened = aes.decrypt(nonce, sealed, associated_data=None)  # raises on bad key/tag

    box, body = opened[:METADATA_BOX_SIZE], opened[METADATA_BOX_SIZE:]
    meta = parse_envelope(box)
    header = bytes.fromhex(meta["header_hex"])
    return meta["name"], header + body


if __name__ == "__main__":
    # tiny self-test
    salt = secrets.token_bytes(16)
    k = derive_key("correct horse battery staple", salt)
    data = b"%PDF-1.7 ... the rest of a secret document ..."
    blob = encrypt_file(data, "report.pdf", k)
    name, restored = decrypt_file(blob, k)
    assert restored == data and name == "report.pdf"
    print("crypto_vault self-test OK, blob size:", len(blob))
