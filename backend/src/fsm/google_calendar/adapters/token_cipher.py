"""FernetTokenCipher: symmetric token encryption via cryptography.fernet."""
from __future__ import annotations

from cryptography.fernet import Fernet


class FernetTokenCipher:
    """Encrypts and decrypts refresh tokens using Fernet symmetric encryption.

    The key must be a valid Fernet key string (32 url-safe base64-encoded bytes).
    Generate one with: cryptography.fernet.Fernet.generate_key().decode()

    Key rotation: rotating to a new key immediately invalidates all stored tokens
    because Fernet tokens are tied to the key that encrypted them (no key-id or
    multi-key envelope scheme). All stored tokens must be re-encrypted before
    switching keys or existing connections will fail to decrypt.
    """

    def __init__(self, key: str) -> None:
        self._fernet = Fernet(key.encode())

    def encrypt(self, plaintext: str) -> str:
        """Return a Fernet-encrypted ciphertext string."""
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, token: str) -> str:
        """Recover the original plaintext from a Fernet ciphertext string."""
        return self._fernet.decrypt(token.encode()).decode()
