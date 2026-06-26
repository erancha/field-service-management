"""TokenCipher port: outbound seam for symmetric token encryption."""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class TokenCipher(Protocol):
    """Symmetric encryption contract for refresh token storage.

    Implementations must guarantee that decrypt(encrypt(plaintext)) == plaintext
    for any non-empty string.
    """

    def encrypt(self, plaintext: str) -> str:
        """Return an opaque ciphertext string derived from plaintext."""
        ...

    def decrypt(self, token: str) -> str:
        """Recover the original plaintext from a ciphertext produced by encrypt."""
        ...
