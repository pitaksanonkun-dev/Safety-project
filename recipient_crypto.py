"""
recipient_crypto.py — public-key ("sealed box") encryption so a recipient can
decrypt WITHOUT typing any password.

How it compares to the password mode:
  * Password mode  -> the data key is derived from a secret both sides must
    know (Argon2id). The secret must travel out-of-band; embedding it in the
    file would defeat the encryption.
  * Recipient mode -> the data key is a random key WRAPPED to each recipient's
    X25519 PUBLIC key. Only that recipient's PRIVATE key (which never leaves
    their machine) can unwrap it. The public key may be shared openly (e.g. over
    LINE); it is not a secret. So nothing secret travels with the file, yet the
    recipient types nothing.

Scheme (ephemeral-static ECDH, a libsodium/age-style sealed box):
    seal:  eph = new X25519 keypair
           shared = ECDH(eph_priv, recipient_pub)
           key    = HKDF-SHA256(shared, info = "docorg-seal-v1" | eph_pub | recipient_pub)
           out    = eph_pub(32) | nonce(12) | AES-256-GCM(key, nonce, payload)
    open:  shared = ECDH(my_priv, eph_pub);  same HKDF;  AES-GCM decrypt

Only `cryptography` is required (already a dependency).
"""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey, X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_RAW = serialization.Encoding.Raw
_PRIV_FMT = serialization.PrivateFormat.Raw
_PUB_FMT = serialization.PublicFormat.Raw
_NOENC = serialization.NoEncryption()

_INFO = b"docorg-seal-v1"
_PUB_PREFIX = "DOCORGPK1:"       # tags a shareable public-key string


# --- key generation / serialization -----------------------------------------
def generate_keypair() -> tuple[bytes, bytes]:
    """Return (private_raw, public_raw), 32 bytes each."""
    priv = X25519PrivateKey.generate()
    priv_raw = priv.private_bytes(_RAW, _PRIV_FMT, _NOENC)
    pub_raw = priv.public_key().public_bytes(_RAW, _PUB_FMT)
    return priv_raw, pub_raw


def public_from_private(private_raw: bytes) -> bytes:
    priv = X25519PrivateKey.from_private_bytes(private_raw)
    return priv.public_key().public_bytes(_RAW, _PUB_FMT)


def encode_public(public_raw: bytes) -> str:
    """A compact, shareable string for a public key (safe to send openly).
    Format: 'DOCORGPK1:' + base64url(pub || first-4-bytes-of-SHA256(pub))."""
    checksum = hashlib.sha256(public_raw).digest()[:4]
    body = base64.urlsafe_b64encode(public_raw + checksum).decode("ascii").rstrip("=")
    return _PUB_PREFIX + body


def decode_public(text: str) -> bytes:
    """Parse a string from encode_public(); raise ValueError if malformed."""
    s = (text or "").strip()
    if not s.startswith(_PUB_PREFIX):
        raise ValueError("ไม่ใช่ public key ของโปรแกรมนี้ (ต้องขึ้นต้นด้วย DOCORGPK1:)")
    body = s[len(_PUB_PREFIX):]
    pad = "=" * (-len(body) % 4)
    try:
        raw = base64.urlsafe_b64decode(body + pad)
    except Exception as e:
        raise ValueError("public key เสียหาย (decode ไม่ได้)") from e
    if len(raw) != 36:
        raise ValueError("public key ความยาวไม่ถูกต้อง")
    pub, checksum = raw[:32], raw[32:]
    if hashlib.sha256(pub).digest()[:4] != checksum:
        raise ValueError("public key เสียหาย (checksum ไม่ตรง)")
    return pub


def fingerprint(public_raw: bytes) -> str:
    """Short human-readable id for confirming a key by eye (8 hex, grouped)."""
    h = hashlib.sha256(public_raw).hexdigest()[:8].upper()
    return f"{h[:4]}-{h[4:]}"


# --- sealed-box primitives ----------------------------------------------------
def seal(public_raw: bytes, payload: bytes) -> bytes:
    """Encrypt `payload` so only the holder of the matching private key can open
    it. Output: eph_pub(32) | nonce(12) | AES-256-GCM ciphertext+tag."""
    recipient_pub = X25519PublicKey.from_public_bytes(public_raw)
    eph = X25519PrivateKey.generate()
    eph_pub = eph.public_key().public_bytes(_RAW, _PUB_FMT)
    shared = eph.exchange(recipient_pub)
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
               info=_INFO + eph_pub + public_raw).derive(shared)
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, payload, None)
    return eph_pub + nonce + ct


def unseal(private_raw: bytes, blob: bytes) -> bytes:
    """Reverse seal() using our own private key. Raises on wrong key / tamper."""
    if len(blob) < 44:
        raise ValueError("sealed blob สั้นเกินไป")
    eph_pub, nonce, ct = blob[:32], blob[32:44], blob[44:]
    priv = X25519PrivateKey.from_private_bytes(private_raw)
    my_pub = priv.public_key().public_bytes(_RAW, _PUB_FMT)
    shared = priv.exchange(X25519PublicKey.from_public_bytes(eph_pub))
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
               info=_INFO + eph_pub + my_pub).derive(shared)
    return AESGCM(key).decrypt(nonce, ct, None)


# --- multi-recipient envelope for a data key ---------------------------------
# A file is encrypted once with a random data key; that data key is sealed to
# each recipient. On decrypt we try to unseal every entry with our private key
# and keep the first that works.
def wrap_data_key(data_key: bytes, recipient_pubs: list[bytes]) -> list[dict]:
    """Return a list of {'fp': fingerprint, 'blob': b64} — one per recipient."""
    entries = []
    for pub in recipient_pubs:
        sealed = seal(pub, data_key)
        entries.append({
            "fp": fingerprint(pub),
            "blob": base64.b64encode(sealed).decode("ascii"),
        })
    return entries


def unwrap_data_key(private_raw: bytes, entries: list[dict]) -> bytes:
    """Try each wrapped entry with our private key; return the data key or raise."""
    my_fp = fingerprint(public_from_private(private_raw))
    # try the entry addressed to us first (fast path), then the rest
    ordered = ([e for e in entries if e.get("fp") == my_fp] +
               [e for e in entries if e.get("fp") != my_fp])
    for e in ordered:
        try:
            blob = base64.b64decode(e["blob"])
            return unseal(private_raw, blob)
        except Exception:
            continue
    raise ValueError("ไฟล์นี้ไม่ได้ถูกเข้ารหัสถึงกุญแจของคุณ (ไม่มี entry ที่ถอดได้)")


# --- self-contained sealed blob (parallel to file_crypto.make_blob) ----------
# Layout:  SEALED_MAGIC(8) | header_len(4, big) | header_json | envelope
#   header_json = {"v":1, "entries":[{fp,blob}, ...]}   (wrapped data key, per recipient)
#   envelope    = crypto_vault.encrypt_file(data, name, data_key)  (same AES-GCM
#                 container used everywhere else; the name lives inside it)
# The data key is random and never derived from a password; only a recipient's
# private key can unwrap it. Distinguished from the password container by MAGIC.
SEALED_MAGIC = b"DOCORGR1"


def make_sealed_blob(data: bytes, original_name: str,
                     recipient_pubs: list[bytes]) -> bytes:
    if not recipient_pubs:
        raise ValueError("ต้องมี public key ของผู้รับอย่างน้อย 1 คน")
    from crypto_vault import encrypt_file
    import json as _json
    data_key = os.urandom(32)
    env = encrypt_file(data, original_name, data_key)
    header = _json.dumps({"v": 1, "entries": wrap_data_key(data_key, recipient_pubs)}
                         ).encode("utf-8")
    return SEALED_MAGIC + len(header).to_bytes(4, "big") + header + env


def is_sealed_blob(blob: bytes) -> bool:
    return bytes(blob[:len(SEALED_MAGIC)]) == SEALED_MAGIC


def read_sealed_blob(blob: bytes, private_raw: bytes) -> tuple[str, bytes]:
    """Reverse make_sealed_blob using our private key -> (original_name, data).
    Raises ValueError if not addressed to us / tampered."""
    from crypto_vault import decrypt_file
    import json as _json
    blob = bytes(blob)
    if not is_sealed_blob(blob):
        raise ValueError("ไม่ใช่ sealed container ของโปรแกรมนี้")
    hlen = int.from_bytes(blob[8:12], "big")
    header = _json.loads(blob[12:12 + hlen].decode("utf-8"))
    env = blob[12 + hlen:]
    data_key = unwrap_data_key(private_raw, header["entries"])
    return decrypt_file(env, data_key)


if __name__ == "__main__":
    # quick self-test
    a_priv, a_pub = generate_keypair()
    b_priv, b_pub = generate_keypair()
    enc = encode_public(a_pub)
    assert decode_public(enc) == a_pub
    dk = os.urandom(32)
    wrapped = wrap_data_key(dk, [a_pub, b_pub])
    assert unwrap_data_key(a_priv, wrapped) == dk
    assert unwrap_data_key(b_priv, wrapped) == dk
    c_priv, _ = generate_keypair()
    try:
        unwrap_data_key(c_priv, wrapped)
        raise SystemExit("FAIL: stranger could unwrap")
    except ValueError:
        pass

    # sealed-blob round-trip (reuses crypto_vault envelope)
    msg = "ข้อมูลลับ sealed ".encode() * 20
    sb = make_sealed_blob(msg, "secret.txt", [a_pub, b_pub])
    for p in (a_priv, b_priv):
        name, out = read_sealed_blob(sb, p)
        assert name == "secret.txt" and out == msg
    try:
        read_sealed_blob(sb, c_priv)
        raise SystemExit("FAIL: stranger opened sealed blob")
    except ValueError:
        pass
    print("recipient_crypto self-test OK  fp(a)=", fingerprint(a_pub))
