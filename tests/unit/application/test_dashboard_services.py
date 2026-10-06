"""Dashboard use cases with every collaborator stubbed (rule 7, DEC-0011)."""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError
from tests.support.dashboard_stubs import (
    LEARNER_ID,
    SESSION_ID,
    ImmediateUnit,
    MemoryActions,
    MemoryAuditQuery,
    MemoryCohort,
    MemoryDirectory,
    SealedRecords,
)
from tests.support.samples import Samples
from tests.support.turn_stubs import Agents, RecordingModel

from tutor_api.adapters.frozen_clock import FrozenClock
from tutor_core.application.services.read_audit import (
    AuditCommand,
    ExecuteAudit,
    ExecuteTurnRead,
    FinaliseAudit,
    FinaliseTurnRead,
    PrepareAudit,
    PrepareTurnRead,
    ReadAudit,
    ReadTurn,
    TurnAuditCommand,
)
from tutor_core.application.services.record_human_action import (
    ActionRules,
    ExecuteAction,
    FinaliseAction,
    HumanActionBody,
    HumanActionCommand,
    PrepareAction,
    RecordHumanAction,
)
from tutor_core.application.services.replay_turn import (
    DraftComparison,
    ExecuteReplay,
    FinaliseReplay,
    PrepareReplay,
    ReplayCommand,
    ReplayTurn,
)
from tutor_core.application.services.report_cohort import (
    CohortCommand,
    ExecuteCohort,
    FinaliseCohort,
    PrepareCohort,
    ReportCohort,
)
from tutor_core.application.services.session_surface import (
    ExecuteLearnerList,
    ExecuteOpenSession,
    ExecuteSession,
    FinaliseLearnerList,
    FinaliseSession,
    LearnerListCommand,
    ListLearners,
    OpenSession,
    OpenSessionCommand,
    PrepareLearnerList,
    PrepareOpenSession,
    PrepareSession,
    ReadSession,
    SessionCommand,
)
from tutor_core.domain.audit.chain import ChainVerifier
from tutor_core.domain.audit.record_hash import ActionRecordHash, AuditRecordHash
from tutor_core.domain.ports.audit_query import TurnNotFound
from tutor_core.domain.ports.human_action import ActionRejected
from tutor_core.domain.ports.session_directory import (
    SessionNotFound,
    SessionOpenRejected,
)

ACTED = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)


class ActionHarness:
    """A tutor-action service over memory stubs."""

    def __init__(self, *records: object) -> None:
        self.query = MemoryAuditQuery(records)  # type: ignore[arg-type]
        self.directory = MemoryDirectory()
        self.actions = MemoryActions(self.query, self.directory)
        self.unit = ImmediateUnit()
        self.service = RecordHumanAction(
            PrepareAction(),
            ExecuteAction(
                self.unit,
                self.query,
                self.directory,
                self.actions,
                FrozenClock(ACTED),
                ActionRecordHash(),
                ActionRules(),
            ),
            FinaliseAction(),
        )

    async def act(
        self,
        action: str,
        turn_id: UUID,
        session_id: UUID = SESSION_ID,
        edited_output: str | None = None,
    ):  # noqa: ANN201 — a RecordedAction
        body = HumanActionBody(
            tutor_id="tutor-1", action=action, edited_output=edited_output
        )
        command = HumanActionCommand(session_id=session_id, turn_id=turn_id, body=body)
        return (await self.service.prepare(command).execute()).finalise()


class TestRecordHumanAction:
    async def test_an_approval_is_sealed_into_the_action_chain(self) -> None:
        record = SealedRecords().generated()
        harness = ActionHarness(record)
        recorded = await harness.act("approve", record.turn_id)
        action = recorded.action
        assert action.session_id == SESSION_ID
        assert action.action_index == 0
        assert action.previous_action_hash == ActionRecordHash.GENESIS
        assert action.action_hash == ActionRecordHash().digest(action)
        assert action.acted_at == ACTED
        assert recorded.stopped is False

    async def test_a_second_action_links_to_the_first(self) -> None:
        record = SealedRecords().generated()
        harness = ActionHarness(record)
        first = (await harness.act("approve", record.turn_id)).action
        second = (await harness.act("stop", record.turn_id)).action
        assert second.action_index == 1
        assert second.previous_action_hash == first.action_hash

    async def test_a_second_decision_on_one_turn_is_rejected(self) -> None:
        record = SealedRecords().generated()
        harness = ActionHarness(record)
        await harness.act("approve", record.turn_id)
        with pytest.raises(ActionRejected, match="already has a tutor decision"):
            await harness.act("override", record.turn_id)
        assert harness.unit.rolled_back == 1

    async def test_a_stop_may_follow_a_decision(self) -> None:
        record = SealedRecords().generated()
        harness = ActionHarness(record)
        await harness.act("edit", record.turn_id, edited_output="Hola is hello.")
        stopped = await harness.act("stop", record.turn_id)
        assert stopped.stopped is True

    async def test_any_action_after_a_stop_is_rejected(self) -> None:
        record = SealedRecords().generated()
        harness = ActionHarness(record)
        await harness.act("stop", record.turn_id)
        with pytest.raises(ActionRejected, match="session is stopped"):
            await harness.act("approve", record.turn_id)

    async def test_approving_a_turn_the_model_never_ran_on_is_rejected(self) -> None:
        record = SealedRecords().halted()
        harness = ActionHarness(record)
        with pytest.raises(ActionRejected, match="no draft to release"):
            await harness.act("approve", record.turn_id)

    async def test_overriding_a_halted_turn_is_accepted(self) -> None:
        record = SealedRecords().halted()
        harness = ActionHarness(record)
        recorded = await harness.act("override", record.turn_id)
        assert recorded.action.action == "override"

    async def test_an_unknown_turn_is_not_found(self) -> None:
        harness = ActionHarness(SealedRecords().generated())
        with pytest.raises(TurnNotFound):
            await harness.act("approve", UUID(int=999))

    async def test_a_turn_from_another_session_is_not_found(self) -> None:
        record = SealedRecords().generated()
        other = UUID(int=555)
        harness = ActionHarness(record)
        harness.directory.sessions.append(
            harness.directory.sessions[0].model_copy(update={"session_id": other})
        )
        with pytest.raises(TurnNotFound, match="not in this session"):
            await harness.act("approve", record.turn_id, session_id=other)

    async def test_an_unknown_session_is_not_found(self) -> None:
        record = SealedRecords().generated()
        harness = ActionHarness(record)
        with pytest.raises(SessionNotFound):
            await harness.act("approve", record.turn_id, session_id=UUID(int=777))


class TestHumanActionBody:
    def test_an_edit_without_text_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="edited_output is required"):
            HumanActionBody(tutor_id="t", action="edit")

    def test_text_on_an_approval_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="only when the tutor edits"):
            HumanActionBody(tutor_id="t", action="approve", edited_output="x")

    def test_an_undeclared_field_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            HumanActionBody.model_validate(
                {"tutor_id": "t", "action": "approve", "turn_id": "x"}
            )


def audit_service(query: MemoryAuditQuery, directory: MemoryDirectory) -> ReadAudit:
    return ReadAudit(
        PrepareAudit(),
        ExecuteAudit(
            ImmediateUnit(),
            query,
            directory,
            ChainVerifier(AuditRecordHash(), ActionRecordHash()),
        ),
        FinaliseAudit(),
    )


class TestReadAudit:
    async def test_an_intact_session_reports_both_chains_intact(self) -> None:
        first = SealedRecords().generated(0)
        second = SealedRecords().generated(1, first.record_hash)
        query = MemoryAuditQuery((first, second))
        harness_actions = MemoryActions(query)
        head = await harness_actions.head(SESSION_ID)
        action = (
            Samples()
            .human_action()
            .model_copy(
                update={
                    "turn_id": first.turn_id,
                    "session_id": SESSION_ID,
                    "action_index": head.action_index,
                    "previous_action_hash": head.previous_action_hash,
                    "action_hash": "x",
                }
            )
        )
        action = action.model_copy(
            update={"action_hash": ActionRecordHash().digest(action)}
        )
        await harness_actions.append(action)
        service = audit_service(query, MemoryDirectory())
        view = (
            await service.prepare(AuditCommand(session_id=SESSION_ID)).execute()
        ).finalise()
        assert view.intact is True
        assert len(view.records) == 2
        assert len(view.actions) == 1
        assert view.unchained_actions == 0

    async def test_a_tampered_action_breaks_the_view(self) -> None:
        record = SealedRecords().generated()
        forged = (
            Samples()
            .human_action()
            .model_copy(
                update={
                    "turn_id": record.turn_id,
                    "session_id": SESSION_ID,
                    "action_index": 0,
                    "previous_action_hash": ActionRecordHash.GENESIS,
                    "action_hash": "f" * 64,
                }
            )
        )
        query = MemoryAuditQuery((record,), (forged,))
        view = (
            await audit_service(query, MemoryDirectory())
            .prepare(AuditCommand(session_id=SESSION_ID))
            .execute()
        ).finalise()
        assert view.intact is False
        assert view.break_reason == "tampered"
        assert view.action_break_index == 0

    async def test_an_unreadable_record_is_a_break_not_a_server_error(self) -> None:
        record = SealedRecords().generated()
        query = MemoryAuditQuery((record,), unreadable=record.turn_id)
        view = (
            await audit_service(query, MemoryDirectory())
            .prepare(AuditCommand(session_id=SESSION_ID))
            .execute()
        ).finalise()
        assert view.intact is False
        assert view.break_reason == "unreadable"
        assert view.break_turn_id == record.turn_id

    async def test_legacy_actions_are_counted_as_unchained(self) -> None:
        record = SealedRecords().generated()
        legacy = Samples().human_action().model_copy(update={"turn_id": record.turn_id})
        query = MemoryAuditQuery((record,), (legacy,))
        view = (
            await audit_service(query, MemoryDirectory())
            .prepare(AuditCommand(session_id=SESSION_ID))
            .execute()
        ).finalise()
        assert view.intact is True
        assert view.unchained_actions == 1

    async def test_an_unknown_session_is_not_found(self) -> None:
        service = audit_service(MemoryAuditQuery(), MemoryDirectory())
        with pytest.raises(SessionNotFound):
            await service.prepare(AuditCommand(session_id=UUID(int=1))).execute()


class TestReadTurn:
    def service(self, query: MemoryAuditQuery) -> ReadTurn:
        return ReadTurn(
            PrepareTurnRead(),
            ExecuteTurnRead(
                ImmediateUnit(), query, MemoryDirectory(), AuditRecordHash()
            ),
            FinaliseTurnRead(),
        )

    async def test_a_turn_comes_with_its_session_and_cited_text(self) -> None:
        record = SealedRecords().generated()
        query = MemoryAuditQuery((record,), cited=(Samples().snippet(),))
        detail = (
            await self.service(query)
            .prepare(TurnAuditCommand(turn_id=record.turn_id))
            .execute()
        ).finalise()
        assert detail.session.session_id == SESSION_ID
        assert detail.cited[0].content == Samples().snippet().content
        assert detail.record_intact is True

    async def test_a_record_with_a_wrong_digest_is_not_intact(self) -> None:
        record = (
            SealedRecords().generated().model_copy(update={"record_hash": "0" * 64})
        )
        detail = (
            await self.service(MemoryAuditQuery((record,)))
            .prepare(TurnAuditCommand(turn_id=record.turn_id))
            .execute()
        ).finalise()
        assert detail.record_intact is False

    async def test_an_unknown_turn_is_not_found(self) -> None:
        with pytest.raises(TurnNotFound):
            await (
                self.service(MemoryAuditQuery())
                .prepare(TurnAuditCommand(turn_id=UUID(int=1)))
                .execute()
            )


class TestSessions:
    async def test_opening_a_session_stamps_the_injected_clock(self) -> None:
        directory = MemoryDirectory()
        service = OpenSession(
            PrepareOpenSession(),
            ExecuteOpenSession(ImmediateUnit(), directory, FrozenClock(ACTED)),
            FinaliseSession(),
        )
        command = OpenSessionCommand(learner_id=LEARNER_ID, tutor_id="tutor-1")
        session = (await service.prepare(command).execute()).finalise()
        assert session.started_at == ACTED
        assert session.open is True
        assert directory.opened[0].tutor_id == "tutor-1"

    async def test_a_purged_learner_cannot_be_given_a_session(self) -> None:
        directory = MemoryDirectory(learners=())
        service = OpenSession(
            PrepareOpenSession(),
            ExecuteOpenSession(ImmediateUnit(), directory, FrozenClock(ACTED)),
            FinaliseSession(),
        )
        command = OpenSessionCommand(learner_id=LEARNER_ID, tutor_id="tutor-1")
        with pytest.raises(SessionOpenRejected):
            await service.prepare(command).execute()

    async def test_reading_an_unknown_session_is_not_found(self) -> None:
        service = ReadSession(
            PrepareSession(),
            ExecuteSession(ImmediateUnit(), MemoryDirectory()),
            FinaliseSession(),
        )
        with pytest.raises(SessionNotFound):
            await service.prepare(SessionCommand(session_id=UUID(int=3))).execute()

    async def test_learners_are_listed_by_id_only(self) -> None:
        service = ListLearners(
            PrepareLearnerList(),
            ExecuteLearnerList(ImmediateUnit(), MemoryDirectory()),
            FinaliseLearnerList(),
        )
        learners = (await service.prepare(LearnerListCommand()).execute()).finalise()
        assert set(learners[0].model_dump()) == {"learner_id", "retained"}


class TestReplayTurn:
    def service(self, query: MemoryAuditQuery, text: str) -> ReplayTurn:
        return ReplayTurn(
            PrepareReplay(),
            ExecuteReplay(
                ImmediateUnit(),
                query,
                Agents().generation(model=RecordingModel(text)),
                AuditRecordHash(),
                DraftComparison(),
            ),
            FinaliseReplay(),
        )

    async def recorded(self, text: str) -> MemoryAuditQuery:
        """A record whose generation fields came from the same stub agent."""
        snippet = Samples().snippet()
        history = Samples().history()
        draft = (
            await Agents()
            .generation(model=RecordingModel(text))
            .generate(
                Samples().stored_prompt().text,
                Samples().retrieval(),
                history,
            )
        )
        record = (
            SealedRecords()
            .generated()
            .model_copy(
                update={
                    "model_revision": draft.model_revision,
                    "template_version": draft.template_version,
                    "decoding_params": draft.decoding_params,
                    "output_before_checks": draft.unit.output_before_checks,
                    "output_after_checks": draft.unit.output_after_checks,
                    "ai_disclosure": draft.unit.ai_disclosure,
                    "refused": draft.unit.refused,
                    "safety_flags": draft.safety_flags,
                    "source_support": draft.unit.support,
                    "history_snapshot": history,
                }
            )
        )
        record = SealedRecords()._seal(record)  # noqa: SLF001 — test helper
        return MemoryAuditQuery((record,), cited=(snippet,))

    async def test_a_recorded_turn_reproduces_its_output(self) -> None:
        query = await self.recorded("Hola means hello.")
        report = (
            await self.service(query, "Hola means hello.")
            .prepare(ReplayCommand(turn_id=query.records[0].turn_id))
            .execute()
        ).finalise()
        assert report.outcome == "reproduced", report.differences
        assert report.checkpoint_id == query.records[0].record_hash

    async def test_a_different_completion_is_reported_as_diverged(self) -> None:
        query = await self.recorded("Hola means hello.")
        report = (
            await self.service(query, "Hola means goodbye.")
            .prepare(ReplayCommand(turn_id=query.records[0].turn_id))
            .execute()
        ).finalise()
        assert report.outcome == "diverged"
        assert "output_before_checks" in report.differences

    async def test_a_turn_the_model_never_ran_on_has_nothing_to_replay(self) -> None:
        record = SealedRecords().halted()
        report = (
            await self.service(MemoryAuditQuery((record,)), "x")
            .prepare(ReplayCommand(turn_id=record.turn_id))
            .execute()
        ).finalise()
        assert report.outcome == "not_generated"

    async def test_a_turn_without_its_history_cannot_be_replayed(self) -> None:
        record = SealedRecords()._seal(  # noqa: SLF001 — test helper
            SealedRecords().generated().model_copy(update={"history_snapshot": None})
        )
        report = (
            await self.service(MemoryAuditQuery((record,)), "x")
            .prepare(ReplayCommand(turn_id=record.turn_id))
            .execute()
        ).finalise()
        assert report.outcome == "history_not_recorded"

    async def test_a_tampered_record_is_not_replayed(self) -> None:
        record = (
            SealedRecords().generated().model_copy(update={"record_hash": "e" * 64})
        )
        model = RecordingModel("x")
        service = ReplayTurn(
            PrepareReplay(),
            ExecuteReplay(
                ImmediateUnit(),
                MemoryAuditQuery((record,)),
                Agents().generation(model=model),
                AuditRecordHash(),
                DraftComparison(),
            ),
            FinaliseReplay(),
        )
        report = (
            await service.prepare(ReplayCommand(turn_id=record.turn_id)).execute()
        ).finalise()
        assert report.outcome == "record_tampered"
        assert model.calls == 0


class TestReportCohort:
    async def test_the_counts_carry_no_verdict(self) -> None:
        service = ReportCohort(
            PrepareCohort(),
            ExecuteCohort(ImmediateUnit(), MemoryCohort()),
            FinaliseCohort(),
        )
        report = (await service.prepare(CohortCommand()).execute()).finalise()
        assert report.turns == 1
        assert "verdict" not in type(report).model_fields


class TestTypestate:
    """DEC-0011: each holder exposes exactly one public method."""

    @pytest.mark.parametrize(
        "service_type",
        [ReadTurn, ReplayTurn, ReportCohort, OpenSession, ReadSession, ListLearners],
    )
    def test_a_service_exposes_only_prepare(self, service_type: type) -> None:
        public = {
            name
            for name in dir(service_type)
            if not name.startswith("_") and callable(getattr(service_type, name))
        }
        assert public == {"prepare"}
