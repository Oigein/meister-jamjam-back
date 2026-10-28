import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings


def _key() -> bytes:
    if settings.encryption_key:
        key = base64.b64decode(settings.encryption_key)
        if len(key) != 32:
            raise ValueError("ENCRYPTION_KEY는 base64로 인코딩한 32바이트여야 합니다.")
        return key
    return hashlib.sha256(settings.secret_key.encode()).digest()


def encrypt_bytes(data: bytes) -> bytes:
    nonce = os.urandom(12)
    return nonce + AESGCM(_key()).encrypt(nonce, data, None)


def decrypt_bytes(blob: bytes) -> bytes:
    return AESGCM(_key()).decrypt(blob[:12], blob[12:], None)


def encrypt_text(text: str) -> str:
    return base64.b64encode(encrypt_bytes(text.encode())).decode()


def decrypt_text(token: str) -> str:
    return decrypt_bytes(base64.b64decode(token)).decode()
