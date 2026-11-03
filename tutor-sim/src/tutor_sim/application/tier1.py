"""One fresh session per Tier 1 case, then the oracle's observation."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from tutor_sim.application.oracle import ExposedText, LeakCheck, OutcomeClassifier
from tutor_sim.domain.models.api_views import (
    GateRowView,
    LearnerView,
    TurnDetailView,
    TurnOutcomeView,
)
from tutor_sim.domain.models.case import CaseSpec, OutcomeClass
from tutor_sim.domain.models.client_call import HealthCall
from tutor_sim.domain.models.observation import (
    ActionAttempt,
    Observation,
    ObservedGate,
)
from tutor_sim.domain.models.tutor_role import DashboardView, TutorDecision
from tutor_sim.domain.ports.tutor_client import TutorClientPort
from tutor_sim.domain.ports.tutor_role import TutorRolePort


class CampaignAbort(Exception):
    """The run cannot continue. One case's 503 is not this."""


class PolicyMismatch(Exception):
    """The API's policy version is not the one the dataset was built for."""


class ModeGuard:
    """Tier 1 runs only against a tutor API in simulation mode."""

    def check(self, health: HealthCall) -> None:
        """Abort when health failed or the process is still the prototype."""
        if health.kind != "ok" or health.body is None:
            msg = "the tutor API is not healthy"
            raise CampaignAbort(msg)
        if health.body.mode != "simulation":
            msg = "the tutor API is not in simulation mode"
            raise CampaignAbort(msg)


class PolicyVersionGuard:
    """Abort the run when the observed card is not the expected card."""

    def check(self, observed: str, expected: str) -> None:
        """The two versions are compared as text."""
        if observed != expected:
            msg = f"policy version {observed} != {expected}"
            raise PolicyMismatch(msg)


class RetainedLearner:
    """A case runs only for a persona the seed enrolled and still retains."""

    def require(self, learner_id: UUID, roster: tuple[LearnerView, ...]) -> None:
        """Abort before a session opens for anyone else."""
        for row in roster:
            if row.learner_id == learner_id and row.retained:
                return
        msg = "the learner is not a retained persona"
        raise CampaignAbort(msg)


class SessionPool:
    """A new session for every case. Cases do not share one."""

    def __init__(self, client: TutorClientPort) -> None:
        self._client = client

    def open(self, learner_id: UUID, tutor_id: str) -> UUID:
        """The session id, or an abort when the API refused the open."""
        result = self._client.open_session(learner_id, tutor_id)
        if result.kind != "ok" or result.body is None:
            msg = "the session did not open"
            raise CampaignAbort(msg)
        return result.body.session_id


class ModelCalled:
    """``model_revision is not None``. A refusal with no revision is no call.

    REQ-EVAL case 8 is a refusal under a stub and records no model call, so
    a missing revision is false.
    """

    def from_revision(self, model_revision: str | None) -> bool:
        """Whether the turn reached the model."""
        return model_revision is not None


class RetrievalRan:
    """Retrieval ran when chunks came back, or the conflict gate was reached."""

    def from_turn(self, ids: tuple[str, ...], gates: tuple[GateRowView, ...]) -> bool:
        """Either signal is enough."""
        if ids:
            return True
        return any(
            gate.gate_name == "conflict_and_ambiguity"
            and gate.decision != "not_evaluated"
            for gate in gates
        )


class ReplayMatch:
    """The observation stores a bool. The API stores the outcome word."""

    def matches(self, outcome: str) -> bool:
        """True only for ``reproduced``."""
        return outcome == "reproduced"


class CaseRecord(BaseModel):
    """One Tier 1 case. An errored case has no observation to score."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str = Field(min_length=1)
    errored: bool
    observation: Observation | None = None
    exposed: ExposedText | None = None


class Tier1Runner:
    """Submit the utterance, let the role act, and record what came back."""

    def __init__(self, client: TutorClientPort, role: TutorRolePort) -> None:
        self._client = client
        self._role = role
        self._mode = ModeGuard()
        self._policy = PolicyVersionGuard()
        self._sessions = SessionPool(client)
        self._called = ModelCalled()
        self._retrieval = RetrievalRan()
        self._replay = ReplayMatch()
        self._class = OutcomeClassifier()
        self._roster = RetainedLearner()
        self._leaks = LeakCheck()

    def run(
        self,
        case: CaseSpec,
        utterance: str,
        learner_id: UUID,
        tutor_id: str,
    ) -> CaseRecord:
        """503 and 422 fail the case. A policy mismatch aborts the run."""
        self._mode.check(self._client.health())
        listed = self._client.learners()
        if listed.kind != "ok":
            msg = "the learner roster could not be read"
            raise CampaignAbort(msg)
        self._roster.require(learner_id, listed.body)
        session_id = self._sessions.open(learner_id, tutor_id)
        submitted = self._client.submit(
            session_id, learner_id, utterance, case.requested_history_fields
        )
        if submitted.kind != "ok" or submitted.body is None:
            return CaseRecord(case_id=case.case_id, errored=True)
        body = submitted.body
        self._policy.check(body.policy_version, case.policy_version)
        detail = self._client.detail(body.turn_id)
        if detail.kind != "ok" or detail.body is None:
            return CaseRecord(case_id=case.case_id, errored=True)
        outcome = self._class.classify(
            body.halted_at, self._halted(body), body.refused, body.status
        )
        view = self._view(body, detail.body)
        if outcome is None or view is None:
            return CaseRecord(case_id=case.case_id, errored=True)
        decision = self._role.decide(view)
        attempt = self._attempt(session_id, body.turn_id, tutor_id, decision)
        if attempt is None:
            return CaseRecord(case_id=case.case_id, errored=True)
        replay = self._client.replay(body.turn_id)
        audit = self._client.audit(session_id)
        if (
            replay.kind != "ok"
            or replay.body is None
            or audit.kind != "ok"
            or audit.body is None
        ):
            return CaseRecord(case_id=case.case_id, errored=True)
        return self._record(
            case,
            body,
            detail.body,
            attempt,
            decision,
            replay.body.outcome,
            audit.body.intact,
            outcome,
        )

    def _attempt(
        self,
        session_id: UUID,
        turn_id: UUID,
        tutor_id: str,
        decision: TutorDecision,
    ) -> ActionAttempt | None:
        if decision.decision == "none":
            return ActionAttempt(decision="none", http_status=0, recorded_action=None)
        result = self._client.act(
            session_id,
            turn_id,
            tutor_id,
            decision.decision,
            decision.edited_output,
        )
        if result.kind == "rejected":
            return ActionAttempt(
                decision=decision.decision,
                http_status=result.http_status,
                recorded_action=None,
            )
        if result.kind != "ok" or result.body is None:
            return None
        return ActionAttempt(
            decision=decision.decision,
            http_status=result.http_status,
            recorded_action=result.body.action.action,
        )

    def _view(
        self, body: TurnOutcomeView, detail: TurnDetailView
    ) -> DashboardView | None:
        draft = detail.record.output_before_checks
        if body.status == "awaiting_tutor_approval":
            return DashboardView(
                status="awaiting_tutor_approval",
                output_before_checks=draft,
                policy_version=body.policy_version,
            )
        if body.status == "held_for_review":
            return DashboardView(
                status="held_for_review",
                output_before_checks=draft,
                policy_version=body.policy_version,
            )
        return None

    def _record(
        self,
        case: CaseSpec,
        body: TurnOutcomeView,
        page: TurnDetailView,
        attempt: ActionAttempt,
        decision: TutorDecision,
        replay_outcome: str,
        intact: bool,
        outcome: OutcomeClass,
    ) -> CaseRecord:
        record = page.record
        prompt = record.learner_prompt
        accepted = attempt.decision == "edit" and 200 <= attempt.http_status < 300
        exposed = ExposedText(
            learner_prompt="" if prompt is None else prompt.text,
            reply=body.reply,
            output_before_checks=record.output_before_checks,
            output_after_checks=record.output_after_checks,
            edited_output=decision.edited_output if accepted else None,
            edit_accepted=accepted,
        )
        payload_id = case.payload_id if case.payload_id is not None else case.case_id
        observation = Observation(
            case_id=case.case_id,
            turn_id=body.turn_id,
            status=body.status,
            halted_at=body.halted_at,
            refused=body.refused,
            sources=body.sources,
            model_called=self._called.from_revision(body.model_revision),
            retrieval_ran=self._retrieval.from_turn(
                record.retrieved_context_ids, body.gates
            ),
            gate_rows=tuple(
                ObservedGate(
                    name=gate.gate_name,
                    decision=gate.decision,
                    policy_rule_id=gate.policy_rule_id,
                )
                for gate in body.gates
            ),
            reply_present=bool(body.reply and body.reply.strip()),
            disclosure_present=bool(body.ai_disclosure and body.ai_disclosure.strip()),
            action=attempt,
            replay_matches=self._replay.matches(replay_outcome),
            chain_intact=intact and page.record_intact,
            leaks=self._leaks.find(exposed, case.expected.must_not_contain, payload_id),
            outcome=outcome,
        )
        return CaseRecord(
            case_id=case.case_id,
            errored=False,
            observation=observation,
            exposed=exposed,
        )

    def _halted(self, body: TurnOutcomeView) -> str | None:
        if body.halted_at is None:
            return None
        for gate in body.gates:
            if gate.gate_name == body.halted_at:
                return gate.decision
        return None
