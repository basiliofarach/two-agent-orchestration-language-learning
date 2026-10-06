"""The tutor-action chain, the snapshot in the turn digest, and session views."""

import json
from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError
from tests.support.dashboard_stubs import SESSION_ID, SealedRecords
from tests.support.samples import Samples

from tutor_core.domain.audit.chain import ChainVerifier
from tutor_core.domain.audit.record_hash import ActionRecordHash, AuditRecordHash
from tutor_core.domain.models.audit import HumanAction
from tutor_core.domain.models.session import (
    LearnerSummary,
    SessionOpening,
    SessionSummary,
)
from tutor_core.domain.models.stream import TurnStreamEvent

WHEN = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


class ActionChain:
    """Build a sealed chain of actions on one turn."""

    def build(self, *kinds: str) -> tuple[HumanAction, ...]:
        hasher = ActionRecordHash()
        previous = ActionRecordHash.GENESIS
        built: list[HumanAction] = []
        for index, kind in enumerate(kinds):
            unsealed = (
                Samples()
                .human_action()
                .model_copy(
                    update={
                        "action": kind,
                        "session_id": SESSION_ID,
                        "action_index": index,
                        "previous_action_hash": previous,
                        "action_hash": "unsealed",
                    }
                )
            )
            sealed = unsealed.model_copy(
                update={"action_hash": hasher.digest(unsealed)}
            )
            built.append(sealed)
            previous = sealed.action_hash or ""
        return tuple(built)


class TestHumanActionChainFields:
    def test_a_partly_chained_action_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="all four fields"):
            HumanAction(
                turn_id=UUID(int=1),
                tutor_id="t",
                action="approve",
                acted_at=WHEN,
                session_id=SESSION_ID,
            )

    def test_a_legacy_action_carries_no_chain_fields(self) -> None:
        legacy = Samples().human_action()
        assert legacy.chained() is False

    def test_approve_edit_and_override_decide_and_stop_does_not(self) -> None:
        action = Samples().human_action()
        decided = {
            kind: action.model_copy(update={"action": kind}).decides()
            for kind in ("approve", "edit", "override", "stop")
        }
        assert decided == {
            "approve": True,
            "edit": True,
            "override": True,
            "stop": False,
        }

    def test_an_action_is_frozen(self) -> None:
        with pytest.raises(ValidationError):
            Samples().human_action().action = "stop"  # type: ignore[misc]


class TestActionRecordHash:
    def test_reattributing_an_approval_changes_its_digest(self) -> None:
        (approval,) = ActionChain().build("approve")
        forged = approval.model_copy(update={"tutor_id": "someone-else"})
        hasher = ActionRecordHash()
        assert hasher.digest(forged) != approval.action_hash

    def test_the_digest_excludes_only_its_own_field(self) -> None:
        (approval,) = ActionChain().build("approve")
        payload = json.loads(ActionRecordHash().canonical(approval))
        assert "action_hash" not in payload
        assert payload["previous_action_hash"] == ActionRecordHash.GENESIS


class TestActionChainVerifier:
    def verifier(self) -> ChainVerifier:
        return ChainVerifier(AuditRecordHash(), ActionRecordHash())

    def test_an_intact_chain_has_no_break(self) -> None:
        chain = ActionChain().build("approve", "stop")
        assert self.verifier().find_action_break(chain) is None

    def test_a_removed_action_is_excised(self) -> None:
        first, _, third = ActionChain().build("approve", "stop", "stop")
        found = self.verifier().find_action_break((first, third))
        assert found is not None
        assert found.reason == "excised"
        assert found.action_index == 1

    def test_a_back_dated_action_is_tampered(self) -> None:
        (approval,) = ActionChain().build("approve")
        changed = approval.model_copy(
            update={"acted_at": datetime(2020, 1, 1, tzinfo=UTC)}
        )
        found = self.verifier().find_action_break((changed,))
        assert found is not None
        assert found.reason == "tampered"

    def test_legacy_actions_are_skipped_not_reported(self) -> None:
        legacy = Samples().human_action()
        chain = ActionChain().build("approve")
        assert self.verifier().find_action_break((legacy, *chain)) is None


class TestHistorySnapshotDigest:
    def test_a_record_without_a_snapshot_keeps_its_historical_digest(self) -> None:
        record = SealedRecords().halted()
        payload = json.loads(AuditRecordHash().canonical(record))
        assert "history_snapshot" not in payload

    def test_a_recorded_snapshot_is_covered_by_the_digest(self) -> None:
        record = SealedRecords().generated()
        assert record.history_snapshot is not None
        changed = record.model_copy(
            update={
                "history_snapshot": record.history_snapshot.model_copy(
                    update={"proficiency_level": "C2"}
                )
            }
        )
        hasher = AuditRecordHash()
        assert hasher.digest(changed) != record.record_hash


class TestSessionModels:
    def test_open_and_stopped_at_cannot_disagree(self) -> None:
        with pytest.raises(ValidationError, match="open exactly when"):
            SessionSummary(
                session_id=UUID(int=1),
                learner_id=UUID(int=2),
                started_at=WHEN,
                stopped_at=WHEN,
                open=True,
            )

    def test_a_naive_start_time_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            SessionSummary(
                session_id=UUID(int=1),
                learner_id=UUID(int=2),
                started_at=datetime(2026, 10, 1, 9, 0),  # noqa: DTZ001 — the case
                open=True,
            )

    def test_an_opening_needs_a_tutor(self) -> None:
        with pytest.raises(ValidationError):
            SessionOpening(
                session_id=UUID(int=1),
                learner_id=UUID(int=2),
                tutor_id="",
                started_at=WHEN,
            )

    def test_a_learner_summary_has_no_pseudonym(self) -> None:
        with pytest.raises(ValidationError):
            LearnerSummary.model_validate(
                {"learner_id": str(UUID(int=2)), "retained": True, "pseudonym": "x"}
            )


class TestStreamEvent:
    def test_an_unknown_gate_name_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            TurnStreamEvent(
                event_id="e",
                kind="gate",
                turn_id=UUID(int=1),
                session_id=UUID(int=2),
                turn_index=0,
                gate_name="made_up_gate",  # type: ignore[arg-type]
            )

    def test_an_undeclared_field_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            TurnStreamEvent.model_validate(
                {
                    "event_id": "e",
                    "kind": "prompt",
                    "turn_id": str(UUID(int=1)),
                    "session_id": str(UUID(int=2)),
                    "turn_index": 0,
                    "learner_name": "x",
                }
            )
