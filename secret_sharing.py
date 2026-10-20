"""
secret_sharing.py — Shamir's Secret Sharing over GF(2^8).

Splits a secret (e.g. the 32-byte master key from crypto_vault) into N shares
such that any K of them reconstruct it, and fewer than K reveal nothing. Each
byte of the secret is shared independently in the AES field GF(256), the same
construction used by established SSS libraries.

Use case here: distribute key shares across locations (local disk + NAS, etc.)
so no single seized location holds a usable key, yet the owner with K shares
can always rebuild it.

No external dependencies.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

# GF(2^8) with the AES irreducible polynomial x^8 + x^4 + x^3 + x + 1 (0x11b).
# Precompute exp/log tables using generator 0x03.
_EXP = [0] * 512
_LOG = [0] * 256


def _init_tables() -> None:
    x = 1
    for i in range(255):
        _EXP[i] = x
        _LOG[x] = i
        x ^= _xtime(x)  # multiply by generator 3 == x*2 ^ x
    for i in range(255, 512):
        _EXP[i] = _EXP[i - 255]


def _xtime(a: int) -> int:
    a <<= 1
    if a & 0x100:
        a ^= 0x11B
    return a & 0xFF


def _gmul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _gdiv(a: int, b: int) -> int:
    if b == 0:
        raise ZeroDivisionError("division by zero in GF(256)")
    if a == 0:
        return 0
    return _EXP[(_LOG[a] - _LOG[b]) % 255]


_init_tables()


def _eval_poly(coeffs: list[int], x: int) -> int:
    """Evaluate polynomial (coeffs[0] = secret byte) at x using Horner."""
    y = 0
    for c in reversed(coeffs):
        y = _gmul(y, x) ^ c
    return y


def _det_coef(seed: bytes, pos: int, c: int) -> int:
    """A reproducible 0..255 polynomial coefficient from a secret seed.
    Coefficients depend on the SEED (not on the secret), so threshold secrecy
    is preserved while the shares stay identical across calls for a given seed."""
    mac = hmac.new(seed, f"{pos}:{c}".encode(), hashlib.sha256).digest()
    return mac[0]


def split_secret(secret: bytes, k: int, n: int,
                 seed: bytes | None = None) -> list[tuple[int, bytes]]:
    """
    Split `secret` into `n` shares, any `k` of which can reconstruct it.
    Returns a list of (x_index, share_bytes). x_index is 1..n (never 0).

    If `seed` is given, the split is DETERMINISTIC: the same (secret, k, n, seed)
    always yields the same shares. Use a stored random seed so a vault's recovery
    keys never change (even when the password changes). Without a seed the split
    is randomised as before.
    """
    if not 2 <= k <= n <= 255:
        raise ValueError("require 2 <= k <= n <= 255")

    shares: list[list[int]] = [[] for _ in range(n)]
    for pos, byte in enumerate(secret):
        # degree-(k-1) polynomial with constant term = secret byte
        if seed is None:
            coeffs = [byte] + [secrets.randbelow(256) for _ in range(k - 1)]
        else:
            coeffs = [byte] + [_det_coef(seed, pos, c) for c in range(1, k)]
        for i in range(n):
            x = i + 1
            shares[i].append(_eval_poly(coeffs, x))

    return [(i + 1, bytes(shares[i])) for i in range(n)]


def recover_secret(shares: list[tuple[int, bytes]]) -> bytes:
    """
    Reconstruct the secret from >= k shares via Lagrange interpolation at x=0.
    Each share is (x_index, share_bytes).
    """
    if len(shares) < 2:
        raise ValueError("need at least k shares to recover")

    xs = [x for x, _ in shares]
    if len(set(xs)) != len(xs):
        raise ValueError("duplicate share indices")

    length = len(shares[0][1])
    secret = bytearray(length)

    for pos in range(length):
        acc = 0
        for xi, share_i in shares:
            yi = share_i[pos]
            # Lagrange basis L_i(0) = product over j!=i of (0 - xj)/(xi - xj)
            num, den = 1, 1
            for xj, _ in shares:
                if xj == xi:
                    continue
                num = _gmul(num, xj)          # (0 - xj) == xj in GF(2)
                den = _gmul(den, xi ^ xj)     # (xi - xj) == xi ^ xj
            acc ^= _gmul(yi, _gdiv(num, den))
        secret[pos] = acc

    return bytes(secret)


if __name__ == "__main__":
    master = secrets.token_bytes(32)          # the AES master key
    shares = split_secret(master, k=2, n=3)   # 3 pieces, any 2 reconstruct

    # recover from a subset
    assert recover_secret(shares[:2]) == master
    assert recover_secret([shares[0], shares[2]]) == master
    # a single share reveals nothing usable (would raise)
    print("secret_sharing self-test OK — 2-of-3 recovery verified")
