"""Encrypt bytes on the way into the store and decrypt them on the way out."""

from abc import ABC, abstractmethod


class CipherPort(ABC):
    """Encrypt and decrypt at the persistence boundary (REQ-MINOR, DEC-0012).

    Scope boundary: bytes in, bytes out. This port holds no connection, no
    session and no domain type, so a collaborator holding it can protect a
    value but cannot reach the store, a learner record, or the audit log.
    The key never crosses this interface; it lives behind the implementation
    and is injected there, so no caller can log it or pass it onward.

    The database performs no cryptography and holds no key (DEC-0012):
    ``pgcrypto`` would place key material in the statement text, where it
    reaches ``pg_stat_activity`` and the server log.
    """

    @abstractmethod
    def encrypt(self, plaintext: bytes) -> bytes:
        """Return a self-describing envelope: version, key id, nonce, tag.

        Non-deterministic: a fresh nonce per call, so equal plaintexts do
        not produce equal envelopes and equality is not leaked.
        """
        raise NotImplementedError  # pragma: no cover

    @abstractmethod
    def decrypt(self, envelope: bytes) -> bytes:
        """Return the plaintext, raising if authentication fails.

        A tampered or truncated envelope is an error, never a partial read.
        """
        raise NotImplementedError  # pragma: no cover
