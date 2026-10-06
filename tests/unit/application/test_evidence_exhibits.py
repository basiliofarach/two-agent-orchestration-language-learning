"""Excerpts and the read that fills them. The pack copies neither history nor PII."""

from pathlib import Path
from uuid import UUID

import pytest
from tests.support.dashboard_stubs import SESSION_ID, MemoryAuditQuery, SealedRecords
from tests.support.samples import Samples

from tutor_api.evidence.catalogue import ExhibitRead, ExhibitResult, PackRead
from tutor_api.evidence.project import ExcerptProjector
from tutor_api.evidence.rubric_file import RubricScores
from tutor_api.evidence.survey import ChainSurvey, ChainSurveyResult
from tutor_core.domain.audit.chain import ChainVerifier
from tutor_core.domain.audit.record_hash import ActionRecordHash, AuditRecordHash
from tutor_core.domain.models.safety import RedactedText, SafetyFlag
from tutor_core.domain.ports.pii_redaction import PiiRedactionPort
from tutor_core.domain.ports.unit_of_work import TransactionConnection


class ReplacingRedactor(PiiRedactionPort):
    """Replace one address. Everything else is left as it arrived."""

    def redact(self, text: str) -> RedactedText:
        """Return the text with the address removed."""
        address = "ada@example.com"
        if address not in text:
            return RedactedText(text=text, redacted_categories=(), redaction_count=0)
        return RedactedText(
            text=text.replace(address, "[REDACTED:email]"),
            redacted_categories=("email",),
            redaction_count=1,
        )


class SequencedConnection(TransactionConnection):
    """Return a different batch for each fetch, and record the statements."""

    def __init__(self, batches: tuple[tuple[tuple[object, ...], ...], ...]) -> None:
        self.statements: list[str] = []
        self._batches = list(batches)

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def execute(self, statement: str, parameters: object = None) -> None:
        self.statements.append(statement)

    async def fetch_one(
        self, statement: str, parameters: object
    ) -> tuple[object, ...] | None:
        self.statements.append(statement)
        return None

    async def fetch_all(
        self, statement: str, parameters: object
    ) -> tuple[tuple[object, ...], ...]:
        self.statements.append(statement)
        return self._batches.pop(0)


class TestExcerptProjector:
    def test_history_and_flag_messages_stay_out_and_an_address_is_removed(self) -> None:
        record = (
            SealedRecords()
            .generated()
            .model_copy(
                update={
                    "output_after_checks": "Write to ada@example.com.",
                    "safety_flags": (
                        SafetyFlag(
                            category="contact",
                            message="the learner said ada@example.com",
                            severity="high",
                        ),
                    ),
                }
            )
        )
        action = (
            Samples()
            .human_action()
            .model_copy(
                update={
                    "turn_id": record.turn_id,
                    "action": "edit",
                    "edited_output": "Send it to ada@example.com",
                }
            )
        )
        found = ExhibitResult(records=(record,), actions=(action,))
        body = ExcerptProjector(ReplacingRedactor()).project(found, ())
        dumped = body.model_dump(mode="json")
        text = str(dumped)
        assert "ada@example.com" not in text
        assert "[REDACTED:email]" in body.turns[0].output_after_checks
        assert body.turns[0].safety_flag_categories == ("contact",)
        assert "history_snapshot" not in dumped["turns"][0]
        assert body.actions[0].edited_output_redacted == "Send it to [REDACTED:email]"
        assert body.rubric_label == "synthetic-only"
        assert body.field_comparison == "not_in_this_pack"

    def test_a_second_pass_adds_a_category_once(self) -> None:
        record = SealedRecords().generated()
        fresh = record.learner_prompt.model_copy(
            update={"text": "ada@example.com", "redacted_categories": ()}
        )
        already = record.learner_prompt.model_copy(
            update={"text": "ada@example.com", "redacted_categories": ("email",)}
        )
        projector = ExcerptProjector(ReplacingRedactor())
        added_record = record.model_copy(update={"learner_prompt": fresh})
        kept_record = record.model_copy(update={"learner_prompt": already})
        added = projector.project(ExhibitResult(records=(added_record,)), ())
        kept = projector.project(ExhibitResult(records=(kept_record,)), ())
        assert added.turns[0].redacted_categories == ("email",)
        assert kept.turns[0].redacted_categories == ("email",)

    def test_an_unwritten_draft_copies_nothing_the_model_did_not_produce(self) -> None:
        record = SealedRecords().halted()
        body = ExcerptProjector(ReplacingRedactor()).project(
            ExhibitResult(records=(record,)), ()
        )
        turn = body.turns[0]
        assert turn.output_before_checks is None
        assert turn.decoding_params is None
        assert turn.unsupported_claims == 0
        assert turn.safety_flag_categories == ()

    def test_a_stored_gate_time_is_copied(self) -> None:
        record = SealedRecords().generated()
        body = ExcerptProjector(ReplacingRedactor()).project(
            ExhibitResult(records=(record,)), ()
        )
        assert (
            body.turns[0].gates[0].evaluated_at
            == record.gate_evaluations[0].evaluated_at.isoformat()
        )


class TestExhibitRead:
    async def test_selects_documents_and_skips_an_unreadable_session(self) -> None:
        connection = SequencedConnection(
            (
                (("kb://spanish/greetings", "1", "approved"),),
                ((SESSION_ID,),),
            )
        )
        result = ExhibitResult()
        await ExhibitRead(MemoryAuditQuery(unreadable=UUID(int=1)), result).run(
            connection
        )
        assert result.documents[0].source_uri == "kb://spanish/greetings"
        assert result.documents[0].review_status == "approved"
        assert result.records == ()
        assert result.unreadable_sessions == (SESSION_ID,)
        joined = "\n".join(connection.statements).lower()
        assert "insert" not in joined
        assert "update" not in joined
        assert "delete" not in joined
        assert "reviewed_by" not in joined

    async def test_a_readable_session_is_copied_from_a_string_id(self) -> None:
        record = SealedRecords().generated()
        action = Samples().human_action().model_copy(update={"turn_id": record.turn_id})
        connection = SequencedConnection(((), ((str(SESSION_ID),),)))
        result = ExhibitResult()
        await ExhibitRead(
            MemoryAuditQuery(records=(record,), actions=(action,)), result
        ).run(connection)
        assert result.records == (record,)
        assert result.actions == (action,)

    async def test_the_pack_read_runs_the_survey_and_the_exhibits(self) -> None:
        connection = SequencedConnection(((), (), ()))
        survey = ChainSurveyResult()
        exhibits = ExhibitResult()
        await PackRead(
            ChainSurvey(
                MemoryAuditQuery(),
                ChainVerifier(AuditRecordHash(), ActionRecordHash()),
                survey,
            ),
            ExhibitRead(MemoryAuditQuery(), exhibits),
        ).run(connection)
        assert survey.sessions == 0
        assert survey.chain_status() == "intact"
        assert exhibits.documents == ()

    async def test_pending_and_rejected_are_copied(self) -> None:
        connection = SequencedConnection(
            (
                (
                    ("kb://a", "1", "pending"),
                    ("kb://b", "2", "rejected"),
                ),
                (),
            )
        )
        result = ExhibitResult()
        await ExhibitRead(MemoryAuditQuery(), result).run(connection)
        assert result.documents[0].review_status == "pending"
        assert result.documents[1].review_status == "rejected"
        assert result.records == ()

    async def test_a_short_document_row_fails_closed(self) -> None:
        connection = SequencedConnection(((("kb://a", "1"),),))
        with pytest.raises(ValueError, match="source, version, and status"):
            await ExhibitRead(MemoryAuditQuery(), ExhibitResult()).run(connection)

    async def test_an_unknown_review_status_fails_closed(self) -> None:
        connection = SequencedConnection(
            ((("kb://spanish/greetings", "1", "secret"),),)
        )
        with pytest.raises(ValueError, match="review_status"):
            await ExhibitRead(MemoryAuditQuery(), ExhibitResult()).run(connection)


class TestRubricScores:
    def test_a_missing_file_supplies_nothing(self, tmp_path: Path) -> None:
        assert RubricScores(tmp_path / "missing.jsonl").lines() == ()

    def test_lines_are_canonical_and_a_list_is_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "rubric-scores.jsonl"
        path.write_text('{"b": 1, "a": 2}\n', encoding="utf-8")
        assert RubricScores(path).lines() == ('{"a":2,"b":1}',)
        path.write_text("[1]\n", encoding="utf-8")
        with pytest.raises(ValueError, match="JSON object"):
            RubricScores(path).lines()

    def test_a_blank_line_is_skipped_and_broken_json_fails(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "rubric-scores.jsonl"
        path.write_text('\n{"a": 1}\n', encoding="utf-8")
        assert RubricScores(path).lines() == ('{"a":1}',)
        path.write_text("not-json\n", encoding="utf-8")
        with pytest.raises(ValueError, match="not JSON"):
            RubricScores(path).lines()
