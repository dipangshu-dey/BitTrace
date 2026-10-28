"""
BitTrace v2 - core/validation.py

Bitcoin address validation (checksum-verified) so malformed or hostile input
is rejected before it reaches the network layer or the database.
Supports Base58Check (P2PKH / P2SH) and Bech32 / Bech32m (SegWit / Taproot).
"""

import hashlib

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_BECH = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _base58check_ok(addr: str) -> bool:
    n = 0
    for ch in addr:
        idx = _B58.find(ch)
        if idx < 0:
            return False
        n = n * 58 + idx
    raw = n.to_bytes(25, "big") if n < 1 << 200 else b""
    pad = len(addr) - len(addr.lstrip("1"))
    raw = b"\x00" * pad + n.to_bytes((n.bit_length() + 7) // 8, "big")
    if len(raw) != 25 or raw[0] not in (0x00, 0x05):
        return False
    return hashlib.sha256(hashlib.sha256(raw[:-4]).digest()).digest()[:4] == raw[-4:]


def _polymod(values):
    gen = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
    chk = 1
    for v in values:
        b = chk >> 25
        chk = (chk & 0x1FFFFFF) << 5 ^ v
        for i in range(5):
            chk ^= gen[i] if (b >> i) & 1 else 0
    return chk


def _bech32_ok(addr: str) -> bool:
    if addr != addr.lower() and addr != addr.upper():
        return False
    addr = addr.lower()
    if not addr.startswith("bc1") or not 14 <= len(addr) <= 74:
        return False
    data = addr[3:]
    if any(c not in _BECH for c in data):
        return False
    values = [_BECH.find(c) for c in data]
    hrp = [ord(c) >> 5 for c in "bc"] + [0] + [ord(c) & 31 for c in "bc"]
    const = _polymod(hrp + values)
    witness_version = values[0]
    return const == (1 if witness_version == 0 else 0x2BC830A3)


def is_valid_btc_address(addr: str) -> bool:
    if not isinstance(addr, str):
        return False
    addr = addr.strip()
    if not 26 <= len(addr) <= 74 or not addr.isascii() or " " in addr:
        return False
    if addr[0] in "13":
        return _base58check_ok(addr)
    return _bech32_ok(addr)
