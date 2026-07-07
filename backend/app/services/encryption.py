from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings

_settings = get_settings()


def _get_fernet() -> Fernet:
    key = _settings.token_encryption_key
    if not key:
        raise ValueError("TOKEN_ENCRYPTION_KEY is not configured")
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_token(plaintext: str | None) -> str | None:
    if not plaintext:
        return None
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str | None) -> str | None:
    if not ciphertext:
        return None
    try:
        return _get_fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        # Legacy unencrypted token — return as-is during migration
        return ciphertext
