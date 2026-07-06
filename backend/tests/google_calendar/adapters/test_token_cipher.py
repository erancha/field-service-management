"""Unit tests for the Fernet token cipher adapter."""
from __future__ import annotations

import pytest
from cryptography.fernet import Fernet, InvalidToken

from fsm.google_calendar.adapters.token_cipher import FernetTokenCipher


class TestFernetTokenCipher:
    def _make_cipher(self) -> FernetTokenCipher:
        key = Fernet.generate_key().decode()
        return FernetTokenCipher(key)

    def test_encrypt_decrypt_round_trip(self):
        cipher = self._make_cipher()
        original = "my-secret-refresh-token"
        assert cipher.decrypt(cipher.encrypt(original)) == original

    def test_ciphertext_differs_from_plaintext(self):
        cipher = self._make_cipher()
        plaintext = "my-secret-refresh-token"
        assert cipher.encrypt(plaintext) != plaintext

    def test_decrypt_with_wrong_key_raises_invalid_token(self):
        """A token encrypted with one key cannot be decrypted with a different key.

        Fernet tokens carry no key-id, so rotating to a new key invalidates all stored
        tokens; all stored tokens must be re-encrypted before switching keys.
        """
        cipher_a = self._make_cipher()
        cipher_b = self._make_cipher()
        ciphertext = cipher_a.encrypt("secret-token")
        with pytest.raises(InvalidToken):
            cipher_b.decrypt(ciphertext)
