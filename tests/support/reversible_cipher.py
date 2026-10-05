"""A cipher whose plaintext is visible to a unit test."""

from tutor_core.domain.ports.cipher import CipherPort


class ReversibleCipher(CipherPort):
    """Prefix the plaintext. Not production cryptography."""

    def encrypt(self, plaintext: bytes) -> bytes:
        return b"sealed:" + plaintext

    def decrypt(self, envelope: bytes) -> bytes:
        if not envelope.startswith(b"sealed:"):
            msg = "envelope failed authentication"
            raise ValueError(msg)
        return envelope.removeprefix(b"sealed:")
