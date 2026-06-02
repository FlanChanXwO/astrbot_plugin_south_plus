"""对称加密原语，用于持久化 cookie 等敏感字段。

实现是手写的 HMAC-SHA256 派生密钥流 + HMAC-SHA256 MAC，避免引入额外依赖。
密文格式为 ``base64url(b"v1:" + nonce[16] + mac[32] + body)``。
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os

_FERNET_PREFIX = b"v1:"


def _derive_key(key_material: str) -> bytes:
    return hashlib.sha256(key_material.encode("utf-8")).digest()


def encrypt_secret(plaintext: str, key_material: str) -> str:
    if not key_material:
        return plaintext
    key = _derive_key(key_material)
    nonce = os.urandom(16)
    keystream = _hkdf_stream(key, nonce, len(plaintext.encode("utf-8")))
    body = bytes(
        a ^ b for a, b in zip(plaintext.encode("utf-8"), keystream, strict=True)
    )
    mac = hmac.new(key, nonce + body, hashlib.sha256).digest()
    payload = _FERNET_PREFIX + nonce + mac + body
    return base64.urlsafe_b64encode(payload).decode("ascii")


def decrypt_secret(ciphertext: str, key_material: str) -> str:
    if not key_material:
        return ciphertext
    try:
        raw = base64.urlsafe_b64decode(ciphertext.encode("ascii"))
    except (ValueError, binascii.Error):
        # 兼容 key 启用前已写入的明文 cookie：非合法 base64 直接当作明文返回。
        return ciphertext
    if not raw.startswith(_FERNET_PREFIX):
        return ciphertext
    raw = raw[len(_FERNET_PREFIX) :]
    if len(raw) < 16 + 32:
        raise ValueError("Cookie 密文长度不合法")
    nonce, mac, body = raw[:16], raw[16:48], raw[48:]
    key = _derive_key(key_material)
    expected_mac = hmac.new(key, nonce + body, hashlib.sha256).digest()
    if not hmac.compare_digest(expected_mac, mac):
        raise ValueError("Cookie 密文 MAC 不匹配，可能加密 key 不一致")
    keystream = _hkdf_stream(key, nonce, len(body))
    return bytes(a ^ b for a, b in zip(body, keystream, strict=True)).decode("utf-8")


def _hkdf_stream(key: bytes, nonce: bytes, length: int) -> bytes:
    block = b""
    counter = 0
    out = bytearray()
    while len(out) < length:
        counter += 1
        block = hmac.new(
            key, block + nonce + counter.to_bytes(4, "big"), hashlib.sha256
        ).digest()
        out.extend(block)
    return bytes(out[:length])
