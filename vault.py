"""
vault.py — Personal encrypted vault engine (envelope-encryption design).

Key hierarchy (industry-standard "key wrapping"):

    password --Argon2id(salt)--> KEK (key-encryption key)
    KEK --AES-256-GCM--> wraps --> DK (random per-vault data key)
    DK --AES-256-GCM--> encrypts the file index and every file blob

Why this matters:
  - The password never touches file data directly. Changing the password only
    re-wraps the DK; you don't re-encrypt gigabytes of files.
  - Plausible deniability: several password "slots" live side by side. The
    entered password is tried against each slot; the one whose GCM auth tag
    verifies unwraps that slot's DK and opens its vault. A wrong password
    unwraps nothing. A decoy slot opens a real, separate vault you fill with
    genuine innocuous files.
  - Recovery: the DK can additionally be split with Shamir's Secret Sharing
    (secret_sharing.py) and distributed (disk / NAS / USB). Gathering k shares
    rebuilds the DK independently of the password.

HONEST LIMITATION: true VeraCrypt-style hidden-volume deniability (where an
examiner cannot even prove a second volume exists) requires full-disk
encryption with a hidden container. On an ordinary filesystem the slot count
and blob directories are visible. Pair this with BitLocker/VeraCrypt FDE for a
serious threat model. See README notes.

Dependencies: pip install cryptography argon2-cffi
"""

from __future__ import annotations

import json
import os
import secrets
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from crypto_vault import derive_key, encrypt_file, decrypt_file
from secret_sharing import split_secret, recover_secret

CONFIG_NAME = "vault.json"
_DK_LEN = 32


# --- low-level wrap/unwrap --------------------------------------------------

def _seal(key: bytes, plaintext: bytes) -> str:
    """AES-256-GCM encrypt -> hex(nonce || ciphertext)."""
    nonce = secrets.token_bytes(12)
    ct = AESGCM(key).encrypt(nonce, plaintext, None)
    return (nonce + ct).hex()


def _open(key: bytes, blob_hex: str) -> bytes:
    """Reverse _seal. Raises InvalidTag if key is wrong or data tampered."""
    raw = bytes.fromhex(blob_hex)
    return AESGCM(key).decrypt(raw[:12], raw[12:], None)


# --- data classes -----------------------------------------------------------

@dataclass
class OpenVault:
    store: "VaultStore"
    vault_id: str
    dk: bytes

    # Convenience pass-throughs ------------------------------------------
    def list_files(self) -> list[dict]:
        return self.store.list_files(self)

    def add_file(self, path: str | os.PathLike) -> str:
        return self.store.add_file(self, path)

    def extract_file(self, file_id: str, out_dir: str | os.PathLike) -> Path:
        return self.store.extract_file(self, file_id, out_dir)

    def remove_file(self, file_id: str) -> None:
        return self.store.remove_file(self, file_id)

    def export_recovery_shares(self, k: int, n: int) -> list[tuple[int, bytes]]:
        # Deterministic split from a stored per-vault seed, so Backup key always
        # yields the SAME keys and they survive password changes.
        seed = self.store.recovery_seed(self.vault_id)
        return split_secret(self.dk, k, n, seed=seed)

    # Recipient-key identity (public-key / "sealed box" mode) -----------
    def identity(self) -> tuple[bytes, bytes]:
        """This vault's (private_raw, public_raw) X25519 keypair, created and
        stored (encrypted in the index) on first use."""
        return self.store.get_identity(self)

    def my_public_key(self) -> bytes:
        return self.identity()[1]


# --- the store --------------------------------------------------------------

class VaultStore:
    def __init__(self, root: str | os.PathLike):
        self.root = Path(root)
        self.config_path = self.root / CONFIG_NAME

    # ---- setup --------------------------------------------------------
    def init(self) -> None:
        """Create an empty store if none exists."""
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.config_path.exists():
            self._write_config({"version": 1, "slots": []})

    def _read_config(self) -> dict:
        return json.loads(self.config_path.read_text("utf-8"))

    def _write_config(self, cfg: dict) -> None:
        # atomic-ish write
        tmp = self.config_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), "utf-8")
        tmp.replace(self.config_path)

    # ---- node-locking (optional machine binding) ----------------------
    @staticmethod
    def _bind(password: str, node_lock: bool) -> str:
        """Mix the machine DNA into the password when a slot is node-locked, so
        the KEK only derives on the authorised machine (fail-closed). No data is
        ever destroyed — a wrong machine just can't unwrap the DK."""
        if not node_lock:
            return password
        import machine_id
        return f"{password}\x00{machine_id.machine_dna()}"

    # ---- creating a vault / password slot -----------------------------
    def create_vault(self, password: str, node_lock: bool = False) -> OpenVault:
        """
        Create a new vault with a fresh random DK and a password slot that
        wraps it. Returns it opened. Slots carry no 'real'/'decoy' label on
        disk — only the password decides which opens.
        """
        self.init()
        cfg = self._read_config()

        vault_id = uuid.uuid4().hex
        dk = secrets.token_bytes(_DK_LEN)
        salt = secrets.token_bytes(16)
        kek = derive_key(self._bind(password, node_lock), salt)

        slot = {
            "vault_id": vault_id,
            "salt": salt.hex(),
            "wrapped_dk": _seal(kek, dk),
            "node": bool(node_lock),
        }
        cfg["slots"].append(slot)
        self._write_config(cfg)

        # vault directories + empty encrypted index
        (self._blob_dir(vault_id)).mkdir(parents=True, exist_ok=True)
        self.recovery_seed(vault_id)        # create the stable recovery seed now
        ov = OpenVault(self, vault_id, dk)
        self._save_index(ov, {"files": {}})
        return ov

    def add_password(self, existing: OpenVault, new_password: str,
                     node_lock: bool = False) -> None:
        """Add another password slot that opens the SAME vault (optional)."""
        cfg = self._read_config()
        salt = secrets.token_bytes(16)
        kek = derive_key(self._bind(new_password, node_lock), salt)
        cfg["slots"].append({
            "vault_id": existing.vault_id,
            "salt": salt.hex(),
            "wrapped_dk": _seal(kek, existing.dk),
            "node": bool(node_lock),
        })
        self._write_config(cfg)

    # ---- unlocking ----------------------------------------------------
    def unlock(self, password: str) -> OpenVault | None:
        """Try the password against every slot; return the vault it opens.
        A node-locked slot only opens on its authorised machine."""
        cfg = self._read_config()
        for slot in cfg["slots"]:
            kek = derive_key(self._bind(password, slot.get("node", False)),
                             bytes.fromhex(slot["salt"]))
            try:
                dk = _open(kek, slot["wrapped_dk"])
            except InvalidTag:
                continue  # not this slot (wrong password, or wrong machine)
            return OpenVault(self, slot["vault_id"], dk)
        return None

    def node_locked_for(self, password: str):
        """Return True/False if a slot opens with `password` (on this machine),
        telling whether it is node-locked; None if no slot opens."""
        cfg = self._read_config()
        for slot in cfg["slots"]:
            node = slot.get("node", False)
            kek = derive_key(self._bind(password, node), bytes.fromhex(slot["salt"]))
            try:
                _open(kek, slot["wrapped_dk"])
            except InvalidTag:
                continue
            return node
        return None

    def set_node_lock(self, password: str, enable: bool) -> bool:
        """Re-wrap the slot that `password` opens so it is (or isn't) bound to
        THIS machine. Returns True if a slot was updated. Only changes the key
        wrapping — the data and its DK are untouched."""
        cfg = self._read_config()
        for slot in cfg["slots"]:
            salt = bytes.fromhex(slot["salt"])
            cur = slot.get("node", False)
            # find the matching slot by trying its current binding (then the other)
            dk = None
            for node_try in (cur, not cur):
                try:
                    dk = _open(derive_key(self._bind(password, node_try), salt),
                               slot["wrapped_dk"])
                    break
                except InvalidTag:
                    continue
            if dk is None:
                continue
            new_salt = secrets.token_bytes(16)
            new_kek = derive_key(self._bind(password, enable), new_salt)
            slot["salt"] = new_salt.hex()
            slot["wrapped_dk"] = _seal(new_kek, dk)
            slot["node"] = bool(enable)
            self._write_config(cfg)
            return True
        return False

    def unlock_with_shares(self, vault_id: str,
                           shares: list[tuple[int, bytes]]) -> OpenVault:
        """Recovery path: rebuild DK from Shamir shares (no password)."""
        dk = recover_secret(shares)
        ov = OpenVault(self, vault_id, dk)
        self._load_index(ov)  # raises InvalidTag if DK is wrong
        return ov

    # ---- paths --------------------------------------------------------
    def _vault_dir(self, vault_id: str) -> Path:
        return self.root / "vaults" / vault_id

    def _blob_dir(self, vault_id: str) -> Path:
        return self._vault_dir(vault_id) / "blobs"

    def _index_path(self, vault_id: str) -> Path:
        return self._vault_dir(vault_id) / "index.enc"

    def _seed_path(self, vault_id: str) -> Path:
        return self._vault_dir(vault_id) / "recovery.seed"

    def recovery_seed(self, vault_id: str) -> bytes:
        """Return the vault's stable recovery seed, creating it once if absent.
        It is not password-sensitive on its own (it only makes the Shamir split
        reproducible); it lives with the vault so recovery keys stay constant."""
        p = self._seed_path(vault_id)
        if p.exists():
            return bytes.fromhex(p.read_text("utf-8").strip())
        p.parent.mkdir(parents=True, exist_ok=True)
        seed = secrets.token_bytes(32)
        p.write_text(seed.hex(), "utf-8")
        return seed

    # ---- encrypted index ---------------------------------------------
    def _save_index(self, ov: OpenVault, index: dict) -> None:
        self._index_path(ov.vault_id).parent.mkdir(parents=True, exist_ok=True)
        blob = _seal(ov.dk, json.dumps(index, ensure_ascii=False).encode("utf-8"))
        self._index_path(ov.vault_id).write_text(blob, "utf-8")

    def _load_index(self, ov: OpenVault) -> dict:
        blob = self._index_path(ov.vault_id).read_text("utf-8")
        return json.loads(_open(ov.dk, blob).decode("utf-8"))

    # ---- recipient-key identity --------------------------------------
    def get_identity(self, ov: OpenVault) -> tuple[bytes, bytes]:
        """Return (private_raw, public_raw) for this vault, creating the keypair
        on first use and storing it inside the ENCRYPTED index (so the private
        key is protected by the DK / login, never written in the clear)."""
        from recipient_crypto import generate_keypair, public_from_private
        index = self._load_index(ov)
        ident = index.get("_identity")
        if ident and ident.get("priv"):
            priv = bytes.fromhex(ident["priv"])
            return priv, public_from_private(priv)
        priv, pub = generate_keypair()
        index["_identity"] = {"priv": priv.hex(), "pub": pub.hex()}
        self._save_index(ov, index)
        return priv, pub

    # ---- file operations ---------------------------------------------
    def add_file(self, ov: OpenVault, path: str | os.PathLike) -> str:
        path = Path(path)
        data = path.read_bytes()
        file_id = uuid.uuid4().hex

        blob = encrypt_file(data, path.name, ov.dk)
        self._blob_dir(ov.vault_id).mkdir(parents=True, exist_ok=True)
        (self._blob_dir(ov.vault_id) / f"{file_id}.enc").write_bytes(blob)

        index = self._load_index(ov)
        index["files"][file_id] = {
            "name": path.name,
            "size": len(data),
            "added": int(time.time()),
        }
        self._save_index(ov, index)
        return file_id

    def list_files(self, ov: OpenVault) -> list[dict]:
        index = self._load_index(ov)
        return [{"id": fid, **meta} for fid, meta in index["files"].items()]

    def extract_file(self, ov: OpenVault, file_id: str,
                     out_dir: str | os.PathLike) -> Path:
        blob = (self._blob_dir(ov.vault_id) / f"{file_id}.enc").read_bytes()
        name, data = decrypt_file(blob, ov.dk)
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / name
        out_path.write_bytes(data)
        return out_path

    def remove_file(self, ov: OpenVault, file_id: str) -> None:
        blob_path = self._blob_dir(ov.vault_id) / f"{file_id}.enc"
        if blob_path.exists():
            blob_path.unlink()
        index = self._load_index(ov)
        index["files"].pop(file_id, None)
        self._save_index(ov, index)


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        store = VaultStore(Path(d) / "store")
        store.init()

        real = store.create_vault("real-master-password")
        decoy = store.create_vault("decoy-password")

        # add a secret to the real vault
        secret_file = Path(d) / "secret.txt"
        secret_file.write_bytes(b"the real confidential content " * 10)
        real.add_file(secret_file)

        # unlock routing
        assert store.unlock("real-master-password").vault_id == real.vault_id
        assert store.unlock("decoy-password").vault_id == decoy.vault_id
        assert store.unlock("wrong-password") is None
        assert real.vault_id != decoy.vault_id

        # decoy sees no real files
        assert len(store.unlock("decoy-password").list_files()) == 0
        assert len(store.unlock("real-master-password").list_files()) == 1

        # round-trip extract
        ov = store.unlock("real-master-password")
        fid = ov.list_files()[0]["id"]
        out = ov.extract_file(fid, Path(d) / "out")
        assert out.read_bytes() == secret_file.read_bytes()

        # Shamir recovery without the password
        shares = ov.export_recovery_shares(k=2, n=3)
        rec = store.unlock_with_shares(ov.vault_id, [shares[0], shares[2]])
        assert len(rec.list_files()) == 1

        print("vault.py end-to-end self-test OK")
        print("  - real/decoy routing verified")
        print("  - wrong password rejected")
        print("  - file encrypt/extract round-trip verified")
        print("  - Shamir 2-of-3 recovery verified")
