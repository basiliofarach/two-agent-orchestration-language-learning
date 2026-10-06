"""Open and seal the ciphertext columns an adapter is allowed to touch."""

import json

from tutor_core.domain.ports.cipher import CipherPort


class SealedValue:
    """Bytes in, bytes out, through the injected cipher (DEC-0012).

    Registered once in the container and injected into each adapter that
    reads or writes a ``ciphertext`` column, so no adapter constructs its
    own (rule 3). The database never sees the key. Equal plaintexts do not
    need to seal to equal envelopes; the cipher's nonce does that.
    """

    def __init__(self, cipher: CipherPort) -> None:
        self._cipher = cipher

    def seal_text(self, value: str) -> bytes:
        """Seal one string."""
        return self._cipher.encrypt(value.encode("utf-8"))

    def seal_optional_text(self, value: str | None) -> bytes | None:
        """Seal a string, or keep the column null."""
        if value is None:
            return None
        return self.seal_text(value)

    def open_text(self, value: object) -> str:
        """Open one envelope to text."""
        return self._cipher.decrypt(self._envelope(value)).decode("utf-8")

    def open_optional_text(self, value: object) -> str | None:
        """Open an envelope, or return ``None`` when the column is null."""
        if value is None:
            return None
        return self.open_text(value)

    def open_json(self, value: object) -> object:
        """Open an envelope and parse the JSON it holds."""
        return json.loads(self.open_text(value))

    def open_optional_json(self, value: object) -> object:
        """Open a JSON envelope, or return ``None`` when the column is null."""
        if value is None:
            return None
        return self.open_json(value)

    def _envelope(self, value: object) -> bytes:
        # The driver returns ``bytes`` or a memory view. Both are envelopes.
        if isinstance(value, bytes):
            return value
        if isinstance(value, bytearray | memoryview):
            return bytes(value)
        msg = "ciphertext column is not bytes"
        raise ValueError(msg)
