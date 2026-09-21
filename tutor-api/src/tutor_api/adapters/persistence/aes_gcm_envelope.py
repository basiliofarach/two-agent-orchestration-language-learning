"""AES-256-GCM envelope for CipherPort (DEC-0012)."""

import secrets
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from tutor_core.domain.ports.cipher import CipherPort


class AesGcmEnvelope(CipherPort):
    """Application-layer envelope. The database never sees the key.

    Layout (DEC-0012): version, key id, nonce, ciphertext, GCM tag.
    The version and key id are bound as additional authenticated data, so a
    swapped header fails authentication. A fresh nonce makes equal plaintexts
    unequal on disk.
    """

    _VERSION = 1
    _NONCE_LENGTH = 12
    _TAG_LENGTH = 16
    _HEADER_LENGTH = 17
    _MINIMUM_LENGTH = 45
    _KEY_LENGTH = 32

    def __init__(self, key: bytes, key_id: UUID) -> None:
        if len(key) != self._KEY_LENGTH:
            msg = "KEK must be 32 bytes"
            raise ValueError(msg)
        self._key = key
        self._key_id = key_id
        self._aes = AESGCM(key)

    def encrypt(self, plaintext: bytes) -> bytes:
        nonce = secrets.token_bytes(self._NONCE_LENGTH)
        header = self._header()
        sealed = self._aes.encrypt(nonce, plaintext, header)
        return header + nonce + sealed

    def decrypt(self, envelope: bytes) -> bytes:
        if not self._header_authentic(envelope):
            msg = "envelope failed authentication"
            raise ValueError(msg)
        nonce = envelope[self._HEADER_LENGTH : self._HEADER_LENGTH + self._NONCE_LENGTH]
        sealed = envelope[self._HEADER_LENGTH + self._NONCE_LENGTH :]
        try:
            return self._aes.decrypt(nonce, sealed, envelope[: self._HEADER_LENGTH])
        except InvalidTag:
            msg = "envelope failed authentication"
            raise ValueError(msg) from None

    def _header(self) -> bytes:
        return bytes([self._VERSION]) + self._key_id.bytes

    def _header_authentic(self, envelope: bytes) -> bool:
        if len(envelope) < self._MINIMUM_LENGTH or envelope[0] != self._VERSION:
            return False
        presented = UUID(bytes=envelope[1 : self._HEADER_LENGTH])
        return presented == self._key_id
