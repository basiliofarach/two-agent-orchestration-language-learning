"""The exemption set is the DEC-0012 list, and the SQL holds no key."""

from pathlib import Path

from tutor_api.adapters.persistence.encryption_at_rest import EncryptionAtRestSchema


class TestEncryptionAtRestCatalogue:
    def test_protected_tables_cover_learner_session_and_audit(self) -> None:
        assert EncryptionAtRestSchema().protected_tables() == (
            "turn_audit",
            "gate_evaluation",
            "learner",
            "learner_history",
            "learner_history_event",
            "tutoring_session",
        )

    def test_exemptions_are_the_decision_set(self) -> None:
        pairs = {
            (row.table_name, row.column_name)
            for row in EncryptionAtRestSchema().exemptions()
        }
        assert pairs == {
            ("kb_chunk", "embedding"),
            ("turn_audit", "record_hash"),
            ("turn_audit", "previous_record_hash"),
            ("learner", "learner_id"),
            ("learner_history", "learner_id"),
            ("learner_history_event", "learner_id"),
            ("kb_document", "source_uri"),
            ("kb_document", "version"),
            ("kb_document", "review_status"),
            ("turn_audit", "policy_version"),
            ("turn_audit", "model_revision"),
            ("turn_audit", "recorded_at"),
            ("turn_audit", "turn_id"),
        }
        for row in EncryptionAtRestSchema().exemptions():
            assert row.decision_ref == "DEC-0012"
            assert row.reason.strip()

    def test_statements_do_not_call_pgcrypto(self) -> None:
        sql = "\n".join(EncryptionAtRestSchema().statements()).lower()
        assert "pgcrypto" not in sql
        assert "pgp_sym_encrypt" not in sql

    def test_compose_does_not_log_statements_or_bind_parameters(self) -> None:
        root = Path(__file__).resolve().parents[3]
        compose = (root / "tutor-api" / "docker-compose.yml").read_text(
            encoding="utf-8"
        )
        assert "log_statement=none" in compose
        assert "log_parameter_max_length=0" in compose
