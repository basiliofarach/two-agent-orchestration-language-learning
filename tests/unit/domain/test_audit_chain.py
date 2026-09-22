"""The digest covers every audited field, and the verifier names a break."""

from datetime import UTC, datetime
from uuid import UUID

from tests.support.samples import Samples
from tests.support.sealed_turn import SealedTurn

from tutor_core.domain.audit.chain import ChainVerifier
from tutor_core.domain.audit.record_hash import AuditRecordHash
from tutor_core.domain.models.safety import DecodingParams, SourceSupportReport


class AuditedFieldChanges:
    """One different value for each field the turn hash covers."""

    def updates(self) -> tuple[tuple[str, object], ...]:
        support = Samples().support()
        return (
            ("turn_id", UUID("00000000-0000-4000-8000-000000000099")),
            ("session_id", UUID("00000000-0000-4000-8000-000000000098")),
            ("turn_index", 1),
            ("learner_prompt_redacted", "niño"),
            ("redacted_categories", ("name",)),
            ("retrieved_context_ids", ()),
            ("model_revision", "c" * 40),
            ("template_version", "tpl-2"),
            (
                "decoding_params",
                DecodingParams(temperature=0.2, top_p=1.0, max_tokens=64),
            ),
            ("output_before_checks", "before"),
            ("output_after_checks", "after"),
            ("ai_disclosure", "other disclosure"),
            ("refused", True),
            ("safety_flags", ()),
            (
                "source_support",
                SourceSupportReport(
                    supported=support.supported,
                    unsupported=support.unsupported,
                    support_ratio=0.0,
                ),
            ),
            ("policy_version", "policy-2"),
            ("previous_record_hash", "e" * 64),
            (
                "recorded_at",
                datetime(2026, 9, 21, 13, 0, tzinfo=UTC),
            ),
        )


class TestAuditRecordHash:
    def test_record_hash_changes_when_any_audited_field_changes(self) -> None:
        hasher = AuditRecordHash()
        record = Samples().audit_record()
        original = hasher.digest(record)
        for name, value in AuditedFieldChanges().updates():
            changed = record.model_copy(update={name: value})
            assert hasher.digest(changed) != original
        same = record.model_copy(update={"record_hash": "f" * 64})
        assert hasher.digest(same) == original

    def test_absent_generation_fields_stay_in_the_digest(self) -> None:
        canonical = AuditRecordHash().canonical(Samples().stopped_audit_record())
        for field in (
            "model_revision",
            "template_version",
            "decoding_params",
            "output_before_checks",
            "output_after_checks",
            "ai_disclosure",
            "refused",
            "safety_flags",
            "source_support",
        ):
            assert f'"{field}":null' in canonical
        assert "tutor_id" not in canonical
        assert "edited_output" not in canonical
        assert '"learner_prompt_redacted":"niño"' in AuditRecordHash().canonical(
            Samples()
            .stopped_audit_record()
            .model_copy(update={"learner_prompt_redacted": "niño"})
        )


class TestChainVerifier:
    def test_chain_verifier_reports_tampered_record(self) -> None:
        hasher = AuditRecordHash()
        sealed = SealedTurn(hasher).at(
            Samples().stopped_audit_record(), AuditRecordHash.GENESIS
        )
        tampered = sealed.model_copy(update={"learner_prompt_redacted": "changed"})
        found = ChainVerifier(hasher).find_break((tampered,))
        assert found is not None
        assert found.reason == "tampered"
        assert found.turn_id == tampered.turn_id

    def test_chain_verifier_reports_excised_record(self) -> None:
        hasher = AuditRecordHash()
        sealer = SealedTurn(hasher)
        first = sealer.at(Samples().stopped_audit_record(), AuditRecordHash.GENESIS)
        second = sealer.at(
            Samples()
            .stopped_audit_record()
            .model_copy(
                update={
                    "turn_id": UUID("00000000-0000-4000-8000-000000000013"),
                    "turn_index": 1,
                }
            ),
            first.record_hash,
        )
        found = ChainVerifier(hasher).find_break((second,))
        assert found is not None
        assert found.reason == "excised"
        assert found.turn_id == second.turn_id
        assert ChainVerifier(hasher).find_break((first, second)) is None
        assert ChainVerifier(hasher).find_break(()) is None
