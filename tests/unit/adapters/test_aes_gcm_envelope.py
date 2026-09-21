"""AES-256-GCM envelope matches the CipherPort contract (DEC-0012)."""

from uuid import UUID

import pytest
from tests.contract.test_port_contracts import CipherPortContract

from tutor_api.adapters.persistence.aes_gcm_envelope import AesGcmEnvelope
from tutor_core.domain.ports.cipher import CipherPort

_KEY = bytes(range(32))
_KEY_ID = UUID("00000000-0000-4000-8000-0000000000aa")


class EnvelopeSamples:
    def cipher(self, key: bytes = _KEY) -> AesGcmEnvelope:
        return AesGcmEnvelope(key=key, key_id=_KEY_ID)


class TestAesGcmEnvelopeContract(CipherPortContract):
    def port(self) -> CipherPort:
        return EnvelopeSamples().cipher()


class TestAesGcmEnvelope:
    def test_empty_plaintext_meets_the_minimum_envelope(self) -> None:
        cipher = EnvelopeSamples().cipher()
        envelope = cipher.encrypt(b"")
        assert len(envelope) == 45
        assert envelope[0] == 1
        assert envelope[1:17] == _KEY_ID.bytes
        assert cipher.decrypt(envelope) == b""

    def test_key_must_be_32_bytes(self) -> None:
        with pytest.raises(ValueError, match="32 bytes"):
            AesGcmEnvelope(key=b"short", key_id=_KEY_ID)

    def test_short_envelope_fails_authentication(self) -> None:
        with pytest.raises(ValueError, match="authentication"):
            EnvelopeSamples().cipher().decrypt(b"")

    def test_wrong_version_fails_authentication(self) -> None:
        cipher = EnvelopeSamples().cipher()
        envelope = bytearray(cipher.encrypt(b"hola"))
        envelope[0] = 2
        with pytest.raises(ValueError, match="authentication"):
            cipher.decrypt(bytes(envelope))

    def test_wrong_key_id_fails_authentication(self) -> None:
        cipher = EnvelopeSamples().cipher()
        envelope = bytearray(cipher.encrypt(b"hola"))
        envelope[1] ^= 0xFF
        with pytest.raises(ValueError, match="authentication"):
            cipher.decrypt(bytes(envelope))

    def test_other_key_cannot_decrypt(self) -> None:
        envelope = EnvelopeSamples().cipher().encrypt(b"hola")
        other = AesGcmEnvelope(key=bytes(range(32, 64)), key_id=_KEY_ID)
        with pytest.raises(ValueError, match="authentication"):
            other.decrypt(envelope)

    def test_failure_does_not_reveal_the_key(self) -> None:
        cipher = EnvelopeSamples().cipher()
        with pytest.raises(ValueError) as caught:
            cipher.decrypt(b"nope")
        assert _KEY.hex() not in str(caught.value)
        assert "KEK" not in str(caught.value)
