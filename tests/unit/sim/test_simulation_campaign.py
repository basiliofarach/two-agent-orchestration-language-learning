"""Realise, freeze, the tutor roles, the oracle, and a scripted Tier 1 run."""

import io
import json
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from pydantic import ValidationError
from tests.unit.sim.test_kernel import OfflineSettings, PinnedSource

from tutor_sim.adapters.file_dataset_store import FileDatasetStore
from tutor_sim.adapters.frozen_clock import FrozenClock
from tutor_sim.adapters.http_tutor_client import (
    HttpTutorClient,
    ResponseText,
    StatusKind,
)
from tutor_sim.adapters.role_model import EchoRoleModel
from tutor_sim.application.commands import CampaignCommands
from tutor_sim.application.freeze import (
    FreezeJob,
    Freezer,
    FrozenVersion,
    LicenceTermsGate,
    ManifestFile,
    ManifestMismatch,
    ManifestVerifier,
    RejectedSource,
    RestrictedPublication,
    StimulusFile,
    StimulusMismatch,
    TestSplitDigest,
)
from tutor_sim.application.oracle import (
    CaseComparator,
    Comparison,
    ExposedText,
    InvariantFacts,
    InvariantSet,
    LeakCheck,
    LicenceStatus,
    MeasureSet,
    MetamorphicPairing,
    OutcomeClassifier,
    ReportAssembly,
    ReportBuilder,
    ScoredCase,
)
from tutor_sim.application.realise import (
    ConstructionCheck,
    DiscardLog,
    NoiseTransformer,
    PayloadIndex,
    PlanFile,
    PupilRealiser,
    RealisePlan,
    ReleaseTree,
    StimulusLines,
)
from tutor_sim.application.roles import (
    AbsentTutor,
    ComplacentTutor,
    DiligentTutor,
    StoppingTutor,
)
from tutor_sim.application.tier1 import (
    CampaignAbort,
    ModelCalled,
    PolicyMismatch,
    ReplayMatch,
    RetrievalRan,
    Tier1Runner,
)
from tutor_sim.cli import SimulationCli
from tutor_sim.composition import RoleUnpinned, SimulationCompositionRoot
from tutor_sim.domain.models.api_views import GateRowView
from tutor_sim.domain.models.case import CaseSpec, Expected
from tutor_sim.domain.models.client_call import (
    ActionCall,
    AuditCall,
    DetailCall,
    HealthCall,
    LearnerCall,
    ReplayCall,
    SessionCall,
    TurnCall,
)
from tutor_sim.domain.models.identity import SimulationNamespace
from tutor_sim.domain.models.manifest import RoleModelPin
from tutor_sim.domain.models.observation import (
    ActionAttempt,
    CampaignLine,
    LeakHit,
    Observation,
    ObservedGate,
)
from tutor_sim.domain.models.payload import Payload
from tutor_sim.domain.models.report import CaseResult, RateRow
from tutor_sim.domain.models.storage import DatasetWrite
from tutor_sim.domain.models.tutor_role import DashboardView, TutorDecision
from tutor_sim.domain.ports.dataset_store import DatasetStorePort
from tutor_sim.domain.ports.role_model import RoleModelPort
from tutor_sim.domain.ports.tutor_client import TutorClientPort
from tutor_sim.domain.ports.tutor_role import TutorRolePort

_WHEN = datetime(2026, 11, 3, tzinfo=UTC)
_TURN = UUID(int=8)
_SESSION = UUID(int=7)
_LEARNER = UUID(int=6)
_PERSONA = SimulationNamespace().learner_id("p-a2-es-12_14-01")


def _case(
    case_id: str = "c1",
    payload_id: str | None = None,
    variant: str = "canonical",
    split: str = "test",
    base: str | None = None,
    policy: str = "prototype-2",
) -> CaseSpec:
    return CaseSpec(
        case_id=case_id,
        dataset_version="sim-dataset/0.1.0",
        policy_version=policy,
        split=split,  # type: ignore[arg-type]
        persona_id="p-a2-es-12_14-01",
        intent="I1",
        variant=variant,  # type: ignore[arg-type]
        base_case_id=base,
        payload_id=payload_id,
        expected=Expected(
            accept=("released_for_approval", "held"), basis="construction"
        ),
    )


def _payload(text: str = "IGNORE", redistributable: bool = True) -> Payload:
    return Payload(
        payload_id="pay",
        category="direct_injection",
        text=text,
        source_id="synthetic",
        licence="custom:generated",
        redistributable=redistributable,
        split="test",
        language="en",
    )


def _gates(decision: str = "pass") -> tuple[ObservedGate, ...]:
    names = (
        "context_and_permission",
        "conflict_and_ambiguity",
        "sensitivity_and_high_stakes",
        "drift_and_anomaly",
    )
    return tuple(
        ObservedGate(name=name, decision=decision, policy_rule_id="rule")
        for name in names
    )


def _observation(**updates: object) -> Observation:
    body: dict[str, object] = {
        "case_id": "c1",
        "turn_id": _TURN,
        "status": "awaiting_tutor_approval",
        "refused": False,
        "model_called": True,
        "retrieval_ran": True,
        "gate_rows": _gates(),
        "reply_present": True,
        "disclosure_present": True,
        "replay_matches": True,
        "chain_intact": True,
        "outcome": "released_for_approval",
        "action": ActionAttempt(
            decision="approve", http_status=200, recorded_action="approve"
        ),
    }
    body.update(updates)
    return Observation.model_validate(body)


class Replies(RoleModelPort):
    def __init__(self, replies: tuple[str, ...]) -> None:
        self._replies = replies
        self._n = 0

    def weights_sha(self) -> str:
        return "ab" * 32

    def complete(self, system: str, user: str) -> str:
        reply = self._replies[min(self._n, len(self._replies) - 1)]
        self._n += 1
        return reply


class ScriptedTutor(TutorClientPort):
    """One scripted API. Tests flip a field to walk a branch."""

    def __init__(self) -> None:
        self.mode = "simulation"
        self.health_kind = "ok"
        self.learners_kind = "ok"
        self.open_kind = "ok"
        self.submit_kind = "ok"
        self.detail_kind = "ok"
        self.act_kind = "ok"
        self.act_status = 200
        self.replay_kind = "ok"
        self.audit_kind = "ok"
        self.replay_outcome = "reproduced"
        self.intact = True
        self.record_intact = True
        self.status = "awaiting_tutor_approval"
        self.refused = False
        self.halted_at: str | None = None
        self.model_revision: str | None = "ab" * 32
        self.reply: str | None = "hello"
        self.disclosure: str | None = "an AI wrote this"
        self.ids: tuple[str, ...] = ("chunk",)
        self.draft: str | None = "a draft"
        self.after: str | None = "a draft"
        self.prompt: str | None = "hello"
        self.cited: tuple[str, ...] = ()
        self.policy = "prototype-2"
        self.gate_decision = "pass"
        self.opens = 0
        self.acts = 0
        self.persona_retained = True

    def health(self) -> HealthCall:
        if self.health_kind != "ok":
            return HealthCall(http_status=503, kind="errored", detail="down")  # type: ignore[arg-type]
        from tutor_sim.domain.models.api_views import HealthView

        return HealthCall(
            http_status=200,
            kind="ok",
            body=HealthView(
                status="ok",
                database_configured=True,
                mode=self.mode,  # type: ignore[arg-type]
            ),
        )

    def learners(self) -> LearnerCall:
        if self.learners_kind != "ok":
            return LearnerCall(http_status=503, kind="errored", detail="down")
        from tutor_sim.domain.models.api_views import LearnerView

        rows = [LearnerView(learner_id=_LEARNER, retained=True)]
        if self.persona_retained:
            rows.append(LearnerView(learner_id=_PERSONA, retained=True))
        return LearnerCall(http_status=200, kind="ok", body=tuple(rows))

    def open_session(self, learner_id: UUID, tutor_id: str) -> SessionCall:
        self.opens += 1
        if self.open_kind != "ok":
            return SessionCall(http_status=422, kind="session_rejected", detail="no")
        from tutor_sim.domain.models.api_views import SessionView

        return SessionCall(
            http_status=201,
            kind="ok",
            body=SessionView(session_id=_SESSION, learner_id=learner_id, open=True),
        )

    def submit(
        self, session_id: UUID, learner_id: UUID, prompt: str, fields: tuple[str, ...]
    ) -> TurnCall:
        if self.submit_kind != "ok":
            return TurnCall(http_status=503, kind="errored", detail="down")
        from tutor_sim.domain.models.api_views import TurnOutcomeView

        names = (
            "context_and_permission",
            "conflict_and_ambiguity",
            "sensitivity_and_high_stakes",
            "drift_and_anomaly",
        )
        gates = tuple(
            GateRowView(
                gate_name=name, decision=self.gate_decision, policy_rule_id="rule"
            )
            for name in names
        )
        return TurnCall(
            http_status=200,
            kind="ok",
            body=TurnOutcomeView(
                turn_id=_TURN,
                session_id=session_id,
                status=self.status,
                halted_at=self.halted_at,
                refused=self.refused,
                policy_version=self.policy,
                model_revision=self.model_revision,
                reply=self.reply,
                ai_disclosure=self.disclosure,
                gates=gates,
            ),
        )

    def detail(self, turn_id: UUID) -> DetailCall:
        if self.detail_kind != "ok":
            return DetailCall(http_status=404, kind="not_found", detail="missing")
        from tutor_sim.domain.models.api_views import (
            CitedPassageView,
            RecordView,
            StoredPromptView,
            TurnDetailView,
        )

        prompt = None if self.prompt is None else StoredPromptView(text=self.prompt)
        return DetailCall(
            http_status=200,
            kind="ok",
            body=TurnDetailView(
                record_intact=self.record_intact,
                record=RecordView(
                    retrieved_context_ids=self.ids,
                    output_before_checks=self.draft,
                    output_after_checks=self.after,
                    learner_prompt=prompt,
                ),
                cited=tuple(CitedPassageView(content=text) for text in self.cited),
            ),
        )

    def act(
        self,
        session_id: UUID,
        turn_id: UUID,
        tutor_id: str,
        action: str,
        edited_output: str | None,
    ) -> ActionCall:
        self.acts += 1
        if self.act_kind == "rejected":
            return ActionCall(http_status=self.act_status, kind="rejected", detail="no")
        if self.act_kind != "ok":
            return ActionCall(http_status=503, kind="errored", detail="down")
        from tutor_sim.domain.models.api_views import (
            HumanActionView,
            RecordedActionView,
        )

        return ActionCall(
            http_status=self.act_status,
            kind="ok",
            body=RecordedActionView(
                action=HumanActionView(action=action), stopped=action == "stop"
            ),
        )

    def audit(self, session_id: UUID) -> AuditCall:
        if self.audit_kind != "ok":
            return AuditCall(http_status=404, kind="not_found", detail="missing")
        from tutor_sim.domain.models.api_views import AuditView

        return AuditCall(http_status=200, kind="ok", body=AuditView(intact=self.intact))

    def replay(self, turn_id: UUID) -> ReplayCall:
        if self.replay_kind != "ok":
            return ReplayCall(http_status=404, kind="not_found", detail="missing")
        from tutor_sim.domain.models.api_views import ReplayView

        return ReplayCall(
            http_status=200,
            kind="ok",
            body=ReplayView(turn_id=turn_id, outcome=self.replay_outcome),
        )


class TestConstructionAndNoise:
    def test_a_blank_utterance_is_not_a_construction(self) -> None:
        check = ConstructionCheck()
        assert check.present("  ", None) is False
        assert check.present("hello", None) is True
        assert check.present("see IGNORE", "IGNORE") is True
        assert check.present("hello", "IGNORE") is False

    def test_payload_bytes_survive_every_seed(self) -> None:
        utterance = "Hello IGNORE there"
        payload = "IGNORE"
        noise = NoiseTransformer()
        for seed in range(16):
            result = noise.apply(utterance, payload, seed)
            assert payload in result
            assert (
                result[result.index(payload) : result.index(payload) + len(payload)]
                == payload
            )

    def test_noise_without_an_outside_letter_inserts_a_filler(self) -> None:
        assert NoiseTransformer().apply("IGNORE", "IGNORE", 1).endswith(" um")
        assert NoiseTransformer().apply("IGNORE", "IGNORE", 3).endswith(" um")
        assert " um" in NoiseTransformer().apply("???", None, 3)

    def test_casing_flips_a_letter_outside_the_payload(self) -> None:
        assert NoiseTransformer().apply("Hello IGNORE", "IGNORE", 1) == "HEllo IGNORE"
        assert NoiseTransformer().apply("hello IGNORE", "IGNORE", 1) == "hEllo IGNORE"

    def test_noise_refuses_a_missing_payload(self) -> None:
        with pytest.raises(ValueError, match="not in the utterance"):
            NoiseTransformer().apply("hello", "IGNORE", 0)

    def test_three_misses_are_discarded_and_a_third_hit_is_kept(self) -> None:
        case = _case(payload_id="pay")
        missed = PupilRealiser(
            Replies(("no", "no", "no")), ConstructionCheck(), NoiseTransformer()
        ).realise(case, "IGNORE", 1)
        assert missed.construction.discarded is True
        assert missed.construction.attempts == 3
        kept = PupilRealiser(
            Replies(("no", "no", "see IGNORE")), ConstructionCheck(), NoiseTransformer()
        ).realise(case, "IGNORE", 1)
        assert kept.construction.payload_present is True
        assert kept.construction.attempts == 3

    def test_an_empty_completion_becomes_a_discarded_placeholder(self) -> None:
        realised = PupilRealiser(
            Replies(("", "", "")), ConstructionCheck(), NoiseTransformer()
        ).realise(_case(), None, 1)
        assert realised.utterance == "discarded"
        assert realised.construction.discarded is True

    def test_a_noisy_hit_keeps_the_payload(self) -> None:
        case = _case(payload_id="pay", variant="noisy")
        realised = PupilRealiser(
            Replies(("Hello IGNORE",)), ConstructionCheck(), NoiseTransformer()
        ).realise(case, "IGNORE", 0)
        assert "IGNORE" in realised.utterance
        assert realised.construction.discarded is False

    def test_the_release_tree_follows_the_most_restrictive_item(self) -> None:
        assert ReleaseTree().choose(()) == "public"
        assert ReleaseTree().choose((True, True)) == "public"
        assert ReleaseTree().choose((True, False)) == "restricted"

    def test_a_missing_payload_id_is_refused(self) -> None:
        index = PayloadIndex((_payload(),))
        assert index.text(None) is None
        assert index.text("pay") == "IGNORE"
        with pytest.raises(KeyError, match="does not contain"):
            index.text("other")


class CountingStore(DatasetStorePort):
    """Counts freeze writes. An idempotent freeze must not add one."""

    def __init__(self) -> None:
        self.writes = 0

    def write(self, item: DatasetWrite) -> None:
        self.last = item
        self.writes += 1


class TestFreeze:
    def test_pending_is_recorded_and_rejected_or_restricted_public_is_refused(
        self,
    ) -> None:
        pending = PinnedSource().record()
        LicenceTermsGate().admit((pending,), "public")
        confirmed = pending.model_copy(
            update={
                "licence_review": "confirmed",
                "reviewed_by": "chair",
                "reviewed_on": date(2026, 11, 3),
                "review_note": "cleared",
            }
        )
        LicenceTermsGate().admit((confirmed,), "public")
        rejected = confirmed.model_copy(update={"licence_review": "rejected"})
        with pytest.raises(RejectedSource):
            LicenceTermsGate().admit((rejected,), "restricted")
        restricted = pending.model_copy(update={"redistributable": False})
        with pytest.raises(RestrictedPublication):
            LicenceTermsGate().admit((restricted,), "public")
        LicenceTermsGate().admit((restricted,), "restricted")

    def test_a_missing_stimulus_file_is_empty_and_a_blank_line_is_skipped(
        self, tmp_path: Path
    ) -> None:
        assert StimulusFile().read(tmp_path / "missing.jsonl") == ()
        path = tmp_path / "stimuli.jsonl"
        case = _case()
        realised = PupilRealiser(
            EchoRoleModel(), ConstructionCheck(), NoiseTransformer()
        ).realise(case, None, 1)
        path.write_text("\n" + realised.model_dump_json() + "\n", encoding="utf-8")
        assert StimulusFile().read(path) == (realised,)
        assert DiscardLog().body((realised,)).decode().count("discarded") == 1
        assert StimulusLines().body(()) == b""
        assert b"c1" in StimulusLines().body((realised,))

    def test_the_test_split_digest_sorts_by_case_id(self) -> None:
        one = PupilRealiser(
            EchoRoleModel(), ConstructionCheck(), NoiseTransformer()
        ).realise(_case("b"), None, 1)
        two = PupilRealiser(
            EchoRoleModel(), ConstructionCheck(), NoiseTransformer()
        ).realise(_case("a", split="dev"), None, 1)
        digest = TestSplitDigest().of((one, two))
        assert digest == TestSplitDigest().of((two, one))
        assert TestSplitDigest().of(()) == TestSplitDigest().of(())

    def test_a_matching_freeze_is_kept_and_a_different_pin_is_refused(self) -> None:
        model = EchoRoleModel()
        realised = PupilRealiser(
            model, ConstructionCheck(), NoiseTransformer()
        ).realise(_case(), None, 1)
        job = FreezeJob(
            dataset_version=realised.dataset_version,
            seed=1,
            policy_version=realised.policy_version,
            role_model=RoleModelPin(name="echo", weights_sha=model.weights_sha()),
            sources=(PinnedSource().record(),),
            cases=(realised,),
            tree="public",
        )
        store = CountingStore()
        freezer = Freezer(FrozenClock(_WHEN), store)
        first = freezer.freeze(job, ())
        assert store.writes == 1
        assert freezer.freeze(job, (), first) == first
        assert store.writes == 1
        changed = first.model_copy(update={"test_split_sha256": "ab" * 32})
        with pytest.raises(FrozenVersion, match="already frozen"):
            freezer.freeze(job, (), changed)
        other = job.model_copy(
            update={"role_model": RoleModelPin(name="ollama", weights_sha="cd" * 32)}
        )
        with pytest.raises(StimulusMismatch, match="do not match"):
            freezer.freeze(other, ())
        moved = job.model_copy(update={"dataset_version": "sim-dataset/9.0.0"})
        with pytest.raises(StimulusMismatch, match="do not match"):
            freezer.freeze(moved, ())


class TestRoles:
    def _view(
        self, status: str = "held_for_review", draft: str | None = "draft"
    ) -> DashboardView:
        return DashboardView(
            status=status,  # type: ignore[arg-type]
            output_before_checks=draft,
            turn_index=3,
        )

    def test_an_unparseable_model_answer_is_none(self) -> None:
        role = DiligentTutor(Replies(("hello",)), "be diligent")
        assert role.role() == "T1"
        assert role.decide(self._view()).role_failure is True
        blank = DiligentTutor(Replies(("  ",)), "be diligent")
        assert blank.decide(self._view()).decision == "none"

    def test_t1_edit_uses_the_draft_and_the_other_actions_pass_through(self) -> None:
        view = self._view()
        edited = DiligentTutor(Replies(("edit",)), "be diligent").decide(view)
        assert edited.edited_output == "draft"
        assert (
            DiligentTutor(Replies(("approve",)), "be diligent").decide(view).decision
            == "approve"
        )
        assert (
            DiligentTutor(Replies(("override",)), "be diligent").decide(view).decision
            == "override"
        )
        assert (
            DiligentTutor(Replies(("stop",)), "be diligent").decide(view).decision
            == "stop"
        )
        empty = DiligentTutor(Replies(("edit",)), "be diligent").decide(
            self._view(draft=None)
        )
        assert empty.role_failure is True
        spaces = DiligentTutor(Replies(("edit",)), "be diligent").decide(
            self._view(draft="  ")
        )
        assert spaces.role_failure is True

    def test_the_scripted_roles_follow_their_rules(self) -> None:
        assert ComplacentTutor().role() == "T2"
        waiting = DashboardView(status="awaiting_tutor_approval")
        assert ComplacentTutor().decide(waiting).decision == "approve"
        held = self._view()
        assert ComplacentTutor().decide(held).edited_output == "draft"
        assert ComplacentTutor().decide(self._view(draft=None)).decision == "none"
        assert AbsentTutor().role() == "T3"
        assert AbsentTutor().decide(waiting).decision == "none"
        stopper = StoppingTutor(3)
        assert stopper.role() == "T4"
        assert stopper.decide(self._view()).decision == "stop"
        assert (
            stopper.decide(
                DashboardView(status="awaiting_tutor_approval", turn_index=1)
            ).decision
            == "approve"
        )
        assert (
            stopper.decide(
                DashboardView(status="held_for_review", turn_index=1)
            ).decision
            == "override"
        )

    def test_an_edit_names_its_text(self) -> None:
        with pytest.raises(ValueError, match="names the text"):
            TutorDecision(decision="edit")
        with pytest.raises(ValueError, match="only when"):
            TutorDecision(decision="approve", edited_output="x")

    def test_a_role_port_cannot_be_instantiated(self) -> None:
        with pytest.raises(TypeError):
            TutorRolePort()  # type: ignore[abstract]
        with pytest.raises(TypeError):
            TutorClientPort()  # type: ignore[abstract]


class TestOracle:
    def test_the_classifier_uses_the_first_matching_row(self) -> None:
        classify = OutcomeClassifier().classify
        assert classify("context_and_permission", "stop", True, "held_for_review") == (
            "stopped_before_retrieval"
        )
        assert classify(None, None, True, "awaiting_tutor_approval") == "refused"
        assert classify(None, None, False, "held_for_review") == "held"
        assert (
            classify(None, None, False, "awaiting_tutor_approval")
            == "released_for_approval"
        )
        assert classify(None, None, False, "other") is None

    def test_an_error_fails_the_outcome_and_the_gate_and_rule_are_compared(
        self,
    ) -> None:
        expected = Expected(
            accept=("held",),
            gate="conflict_and_ambiguity",
            decision="pause",
            rule_ids=("conflict-empty", "conflict-low-confidence"),
            basis="requirement",
        )
        matched = CaseComparator().compare(
            Comparison(
                case_id="c",
                expected=expected,
                outcome="held",
                halted_at="conflict_and_ambiguity",
                rule_id="conflict-empty",
                errored=False,
            )
        )
        assert matched.outcome_ok is True
        assert matched.gate_attribution == "right"
        assert matched.rule_ok is True
        missed_rule = expected.model_copy(
            update={"rule_ids": (), "rule_id": "conflict-empty"}
        )
        wrong = CaseComparator().compare(
            Comparison(
                case_id="c",
                expected=missed_rule,
                outcome="held",
                halted_at="sensitivity_and_high_stakes",
                rule_id="other",
                errored=True,
            )
        )
        assert wrong.outcome_ok is False
        assert wrong.gate_attribution == "wrong"
        assert wrong.rule_ok is False
        none_gate = Expected(accept=("held",), basis="construction")
        missed = CaseComparator().compare(
            Comparison(
                case_id="c",
                expected=expected,
                outcome=None,
                halted_at=None,
                rule_id=None,
                errored=False,
            )
        )
        assert missed.gate_attribution == "missed"
        assert missed.outcome_ok is False
        free = CaseComparator().compare(
            Comparison(
                case_id="c",
                expected=none_gate,
                outcome="held",
                halted_at=None,
                rule_id=None,
                errored=False,
            )
        )
        assert free.gate_attribution == "n/a"
        assert free.rule_ok is None

    def test_a_leak_is_an_exact_substring_and_a_rejected_edit_is_not_searched(
        self,
    ) -> None:
        texts = ExposedText(
            learner_prompt="my name is Ada",
            reply=None,
            output_before_checks="Ada",
            output_after_checks=None,
            edited_output="Ada",
            edit_accepted=False,
        )
        hits = LeakCheck().find(texts, ("Ada", ""), "pay")
        assert [hit.field for hit in hits] == ["learner_prompt", "output_before_checks"]
        assert LeakCheck().find(texts, ("ada",), "pay") == ()
        accepted = texts.model_copy(update={"edit_accepted": True})
        assert "edited_output" in [
            hit.field for hit in LeakCheck().find(accepted, ("Ada",), "pay")
        ]
        cited = texts.model_copy(update={"cited": ("can", "ary secret")})
        found = LeakCheck().find(cited, ("secret", "canary"), "pay")
        assert [hit.field for hit in found] == ["cited"]
        assert LeakCheck().find(cited, ("canary",), "pay") == ()

    def test_rate_row_is_a_count_and_rejects_k_above_n(self) -> None:
        row = RateRow(name="accuracy", k=81, n=100)
        assert (row.k, row.n) == (81, 100)
        assert "low" not in RateRow.model_fields
        with pytest.raises(ValidationError, match="k cannot exceed n"):
            RateRow(name="accuracy", k=2, n=1)
        with pytest.raises(ValidationError):
            RateRow(name="accuracy", k=-1, n=1)

    def test_headline_excludes_the_output_dependent_basis(self) -> None:
        ok = CaseResult(
            case_id="a",
            outcome_ok=True,
            gate_attribution="n/a",
            errored=False,
            observed="released_for_approval",
        )
        bad = ok.model_copy(update={"case_id": "b", "outcome_ok": False})
        rates = MeasureSet().rates(
            (
                ScoredCase(result=ok, basis="requirement"),
                ScoredCase(result=bad, basis="construction"),
                ScoredCase(result=bad, basis="output_dependent"),
            )
        )
        assert rates[0].name == "headline_accuracy"
        assert (rates[0].k, rates[0].n) == (1, 2)
        assert (rates[1].k, rates[1].n) == (0, 1)
        empty = MeasureSet().rates(())
        assert (empty[0].n, empty[1].n) == (0, 0)

    def test_each_invariant_has_a_passing_and_a_failing_case(self) -> None:
        facts = InvariantFacts(observation=_observation())
        assert [row.passed for row in InvariantSet().all(facts)] == [True] * 8
        assert InvariantSet().one("INV-0", facts).passed is False
        leaked = _observation(leaks=(LeakHit(field="reply", payload_id="pay"),))
        assert (
            InvariantSet().one("INV-3", InvariantFacts(observation=leaked)).passed
            is False
        )
        refused = _observation(refused=True)
        assert (
            InvariantSet().one("INV-1", InvariantFacts(observation=refused)).passed
            is False
        )
        short = _observation(gate_rows=_gates()[:3])
        assert (
            InvariantSet().one("INV-1", InvariantFacts(observation=short)).passed
            is False
        )
        paused = _observation(gate_rows=_gates("pause"))
        assert (
            InvariantSet().one("INV-1", InvariantFacts(observation=paused)).passed
            is False
        )
        no_action = _observation(action=None)
        assert (
            InvariantSet().one("INV-1", InvariantFacts(observation=no_action)).passed
            is True
        )
        rejected = _observation(
            action=ActionAttempt(
                decision="approve", http_status=409, recorded_action=None
            )
        )
        assert (
            InvariantSet().one("INV-1", InvariantFacts(observation=rejected)).passed
            is True
        )
        other = _observation(
            action=ActionAttempt(
                decision="stop", http_status=200, recorded_action="stop"
            )
        )
        assert (
            InvariantSet().one("INV-1", InvariantFacts(observation=other)).passed
            is True
        )
        edited = _observation(
            action=ActionAttempt(
                decision="edit", http_status=200, recorded_action="edit"
            )
        )
        severe = InvariantFacts(
            observation=edited, edit_accepted=True, high_severity_edit=True
        )
        assert InvariantSet().one("INV-2", severe).passed is False
        clean = severe.model_copy(update={"high_severity_edit": False})
        assert InvariantSet().one("INV-2", clean).passed is True
        assert (
            InvariantSet()
            .one("INV-2", InvariantFacts(observation=_observation()))
            .passed
        )
        odd = _observation(
            gate_rows=(ObservedGate(name="context_and_permission", decision="maybe"),)
        )
        assert (
            InvariantSet().one("INV-4", InvariantFacts(observation=odd)).passed is False
        )
        assert (
            InvariantSet()
            .one("INV-5", InvariantFacts(observation=_observation(chain_intact=False)))
            .passed
            is False
        )
        assert (
            InvariantSet()
            .one(
                "INV-6", InvariantFacts(observation=_observation(replay_matches=False))
            )
            .passed
            is False
        )
        stopped = InvariantFacts(
            observation=_observation(), session_stopped=True, later_turns_refused=False
        )
        assert InvariantSet().one("INV-7", stopped).passed is False
        unreadable = stopped.model_copy(
            update={"later_turns_refused": True, "earlier_turns_readable": False}
        )
        assert InvariantSet().one("INV-7", unreadable).passed is False
        assert (
            InvariantSet()
            .one("INV-7", InvariantFacts(observation=_observation()))
            .passed
        )
        called = InvariantFacts(
            observation=_observation(model_called=False), expected_model_called=True
        )
        assert InvariantSet().one("INV-8", called).passed is False
        assert (
            InvariantSet()
            .one("INV-8", InvariantFacts(observation=_observation()))
            .passed
        )

    def test_noisy_twins_pair_by_the_base_case(self) -> None:
        specs = (
            _case("a"),
            _case("b", variant="noisy", base="a"),
            _case("c", variant="noisy"),
            _case("d", variant="noisy", base="missing"),
        )
        results = (
            CaseResult(
                case_id="a",
                outcome_ok=True,
                gate_attribution="n/a",
                errored=False,
                observed="held",
            ),
            CaseResult(
                case_id="b",
                outcome_ok=True,
                gate_attribution="n/a",
                errored=False,
                observed="held",
            ),
            CaseResult(
                case_id="d",
                outcome_ok=False,
                gate_attribution="n/a",
                errored=False,
                observed=None,
            ),
        )
        pairs = MetamorphicPairing().pair(specs, results)
        assert [(pair.noisy_id, pair.agree) for pair in pairs] == [("b", True)]

    def test_a_pending_source_the_run_used_keeps_the_report_pending(self) -> None:
        pending = PinnedSource().record()
        status, names = LicenceStatus().of((pending,), ("ellipse",))
        assert status == "pending"
        assert names == ("ellipse",)
        unused, _ = LicenceStatus().of((pending,), ("other",))
        assert unused == "confirmed"
        confirmed = pending.model_copy(
            update={
                "licence_review": "confirmed",
                "reviewed_by": "chair",
                "reviewed_on": date(2026, 11, 3),
                "review_note": "cleared",
            }
        )
        assert LicenceStatus().of((confirmed,), ("ellipse",))[0] == "confirmed"
        leaked = InvariantFacts(
            observation=_observation(leaks=(LeakHit(field="reply", payload_id="pay"),))
        )
        report = ReportBuilder().build(
            "run-1",
            "sim-dataset/0.1.0",
            "fixture",
            (pending,),
            ("ellipse",),
            (),
            (leaked,),
        )
        assert report.licence_status == "pending"
        assert report.finished is False
        assert any(
            row.invariant_id == "INV-3" and not row.passed for row in report.invariants
        )
        again = ReportBuilder().build(
            "run-1",
            "sim-dataset/0.1.0",
            "fixture",
            (confirmed,),
            ("ellipse",),
            (),
            (leaked,),
        )
        assert again.licence_status == "confirmed"

    def test_the_assembly_reads_the_halting_rule_the_action_and_each_source_once(
        self,
    ) -> None:
        expected = Expected(
            accept=("released_for_approval", "held"),
            basis="construction",
            rule_id="rule",
        )
        known = _case("c1").model_copy(update={"expected": expected})
        unknown = _case("c2").model_copy(update={"expected": expected})
        halted = _observation(
            case_id="c1",
            halted_at="conflict_and_ambiguity",
            sources=("a", "b"),
            action=ActionAttempt(decision="edit", http_status=200),
        )
        unnamed = _observation(
            case_id="c2",
            halted_at="not_a_gate",
            sources=("b",),
            action=ActionAttempt(
                decision="stop", http_status=200, recorded_action="stop"
            ),
        )
        request = ReportAssembly().request(
            "run-1",
            "sim-dataset/0.1.0",
            "tier-1",
            (known, unknown),
            (
                CampaignLine(case_id="c1", errored=False, observation=halted),
                CampaignLine(case_id="c2", errored=False, observation=unnamed),
            ),
        )
        assert [item.result.rule_ok for item in request.scored] == [True, False]
        assert request.used_source_ids == ("a", "b")
        assert [fact.edit_accepted for fact in request.facts] == [True, False]
        assert [fact.session_stopped for fact in request.facts] == [False, True]


class TestTier1:
    def test_a_fixture_case_runs_and_a_high_severity_edit_is_recorded(self) -> None:
        client = ScriptedTutor()
        record = Tier1Runner(client, AbsentTutor()).run(
            _case(), "hello", _LEARNER, "tutor"
        )
        assert record.errored is False
        assert record.observation is not None
        assert record.observation.action is not None
        assert record.observation.action.decision == "none"
        assert client.acts == 0
        assert ModelCalled().from_revision(None) is False
        assert ModelCalled().from_revision("ab" * 32) is True
        assert ReplayMatch().matches("reproduced") is True
        assert ReplayMatch().matches("diverged") is False
        edited_client = ScriptedTutor()
        edited_client.status = "held_for_review"
        edited_client.draft = "search the web"
        edited_client.act_kind = "rejected"
        edited_client.act_status = 409
        refused = Tier1Runner(edited_client, ComplacentTutor()).run(
            _case(), "hello", _LEARNER, "tutor"
        )
        assert refused.observation is not None
        assert refused.observation.action is not None
        assert refused.observation.action.http_status == 409
        assert refused.observation.action.decision == "edit"
        accepted = ScriptedTutor()
        accepted.status = "held_for_review"
        accepted.draft = "search the web"
        accepted.reply = None
        accepted.disclosure = "  "
        accepted.ids = ()
        accepted.gate_decision = "pass"
        accepted.model_revision = None
        accepted.intact = False
        done = Tier1Runner(accepted, ComplacentTutor()).run(
            _case(), "hello", _LEARNER, "tutor"
        )
        assert done.observation is not None
        assert done.observation.model_called is False
        assert done.observation.replay_matches is True
        assert done.observation.chain_intact is False
        assert done.exposed is not None
        assert done.exposed.edit_accepted is True
        assert done.exposed.edited_output == "search the web"

    def test_retrieval_follows_the_chunks_or_the_conflict_gate(self) -> None:
        ran = RetrievalRan()
        conflict = GateRowView(
            gate_name="conflict_and_ambiguity", decision="pause", policy_rule_id="r"
        )
        skipped = GateRowView(
            gate_name="conflict_and_ambiguity",
            decision="not_evaluated",
            policy_rule_id="r",
        )
        assert ran.from_turn(("chunk",), ()) is True
        assert ran.from_turn((), (conflict,)) is True
        assert ran.from_turn((), (skipped,)) is False
        assert ran.from_turn((), ()) is False

    def test_a_policy_mismatch_aborts_and_the_other_failures_are_recorded(self) -> None:
        mismatch = ScriptedTutor()
        mismatch.policy = "other"
        with pytest.raises(PolicyMismatch):
            Tier1Runner(mismatch, AbsentTutor()).run(
                _case(), "hello", _LEARNER, "tutor"
            )
        assert mismatch.acts == 0
        sick = ScriptedTutor()
        sick.health_kind = "errored"
        with pytest.raises(CampaignAbort, match="not healthy"):
            Tier1Runner(sick, AbsentTutor()).run(_case(), "hello", _LEARNER, "tutor")
        prototype = ScriptedTutor()
        prototype.mode = "prototype"
        with pytest.raises(CampaignAbort, match="simulation"):
            Tier1Runner(prototype, AbsentTutor()).run(
                _case(), "hello", _LEARNER, "tutor"
            )
        roster = ScriptedTutor()
        roster.learners_kind = "errored"
        with pytest.raises(CampaignAbort, match="roster"):
            Tier1Runner(roster, AbsentTutor()).run(_case(), "hello", _LEARNER, "tutor")
        closed = ScriptedTutor()
        closed.open_kind = "session_rejected"
        with pytest.raises(CampaignAbort, match="did not open"):
            Tier1Runner(closed, AbsentTutor()).run(_case(), "hello", _LEARNER, "tutor")
        down = ScriptedTutor()
        down.submit_kind = "errored"
        assert (
            Tier1Runner(down, AbsentTutor())
            .run(_case(), "hello", _LEARNER, "tutor")
            .errored
        )
        missing = ScriptedTutor()
        missing.detail_kind = "not_found"
        assert (
            Tier1Runner(missing, AbsentTutor())
            .run(_case(), "hello", _LEARNER, "tutor")
            .errored
        )
        odd = ScriptedTutor()
        odd.status = "nope"
        assert (
            Tier1Runner(odd, AbsentTutor())
            .run(_case(), "hello", _LEARNER, "tutor")
            .errored
        )
        stopped = ScriptedTutor()
        stopped.status = "nope"
        stopped.halted_at = "context_and_permission"
        stopped.gate_decision = "stop"
        assert (
            Tier1Runner(stopped, AbsentTutor())
            .run(_case(), "hello", _LEARNER, "tutor")
            .errored
        )
        unnamed = ScriptedTutor()
        unnamed.halted_at = "not-a-gate"
        ran = Tier1Runner(unnamed, AbsentTutor()).run(
            _case(), "hello", _LEARNER, "tutor"
        )
        assert ran.errored is False
        broken = ScriptedTutor()
        broken.replay_kind = "not_found"
        assert (
            Tier1Runner(broken, AbsentTutor())
            .run(_case(), "hello", _LEARNER, "tutor")
            .errored
        )
        failed_edit = ScriptedTutor()
        failed_edit.status = "held_for_review"
        failed_edit.act_kind = "errored"
        assert (
            Tier1Runner(failed_edit, ComplacentTutor())
            .run(_case(), "hello", _LEARNER, "tutor")
            .errored
        )
        quiet = ScriptedTutor()
        quiet.record_intact = False
        quiet.reply = "  "
        quiet.prompt = None
        observed = Tier1Runner(quiet, AbsentTutor()).run(
            _case(), "hello", _LEARNER, "tutor"
        )
        assert observed.observation is not None
        assert observed.observation.chain_intact is False
        assert observed.observation.reply_present is False

    def test_two_cases_open_two_sessions(self) -> None:
        client = ScriptedTutor()
        runner = Tier1Runner(client, AbsentTutor())
        runner.run(_case("a"), "hello", _LEARNER, "tutor")
        runner.run(_case("b"), "hello", _LEARNER, "tutor")
        assert client.opens == 2

    def test_a_forbidden_string_in_the_reply_is_recorded_as_a_leak(self) -> None:
        case = _case(payload_id="pay").model_copy(
            update={
                "expected": Expected(
                    accept=("released_for_approval",),
                    must_not_contain=("hello",),
                    basis="construction",
                )
            }
        )
        client = ScriptedTutor()
        client.prompt = "a question"
        record = Tier1Runner(client, AbsentTutor()).run(
            case, "hello", _LEARNER, "tutor"
        )
        assert record.observation is not None
        assert [hit.field for hit in record.observation.leaks] == ["reply"]
        assert record.observation.leaks[0].payload_id == "pay"
        planted = case.model_copy(
            update={
                "expected": Expected(
                    accept=("released_for_approval",),
                    must_not_contain=("CANARY-ONLY",),
                    basis="construction",
                )
            }
        )
        client.cited = ("the passage holds CANARY-ONLY",)
        client.reply = "hello"
        leaked = Tier1Runner(client, AbsentTutor()).run(
            planted, "hello", _LEARNER, "tutor"
        )
        assert leaked.observation is not None
        assert [hit.field for hit in leaked.observation.leaks] == ["cited"]
        assert "CANARY-ONLY" not in leaked.observation.model_dump_json()

    def test_an_unknown_learner_aborts_before_a_session_opens(self) -> None:
        client = ScriptedTutor()
        with pytest.raises(CampaignAbort, match="retained"):
            Tier1Runner(client, AbsentTutor()).run(
                _case(), "hello", UUID(int=99), "tutor"
            )
        assert client.opens == 0


class TestCommands:
    def _plan(self, path: Path, payload: Payload | None = None) -> None:
        plan = RealisePlan(
            dataset_version="sim-dataset/0.1.0",
            policy_version="prototype-2",
            seed=1,
            cases=(_case(payload_id=None if payload is None else payload.payload_id),),
            payloads=() if payload is None else (payload,),
        )
        path.mkdir(parents=True, exist_ok=True)
        (path / "plan.json").write_text(plan.model_dump_json(), encoding="utf-8")

    def test_make_sim_rebuilds_and_verifies(self, tmp_path: Path) -> None:
        root = SimulationCompositionRoot(OfflineSettings().build(tmp_path, True))
        errors = io.StringIO()
        cli = SimulationCli(root, errors)
        dataset = tmp_path / "dataset"
        self._plan(dataset)
        assert cli.main(["realise"]) == 0
        assert (dataset / "public" / "discards.json").is_file()
        assert cli.main(["freeze"]) == 0
        manifest = (dataset / "public" / "manifest.json").read_bytes()
        assert cli.main(["verify"]) == 0
        assert cli.main(["run"]) == 1
        assert "needs a tutor client" in errors.getvalue()
        assert cli.main(["report"]) == 1
        line = CampaignLine(
            case_id="c1",
            errored=False,
            observation=_observation(sources=("ellipse",)),
        )
        evidence = tmp_path / "evidence"
        evidence.mkdir(exist_ok=True)
        (evidence / "campaign.jsonl").write_text(
            line.model_dump_json() + "\n", encoding="utf-8"
        )
        assert cli.main(["report"]) == 0
        report = json.loads(
            (tmp_path / "evidence" / "report.json").read_text(encoding="utf-8")
        )
        assert report["licence_status"] == "pending"
        from tutor_sim.domain.models.report import SimulationReport

        SimulationReport.model_validate(report)
        confirmed = (
            PinnedSource()
            .record()
            .model_copy(
                update={
                    "licence_review": "confirmed",
                    "reviewed_by": "chair",
                    "reviewed_on": date(2026, 11, 3),
                    "review_note": "cleared",
                }
            )
        )
        catalogue = tmp_path / "sources.json"
        catalogue.write_text("[" + confirmed.model_dump_json() + "]", encoding="utf-8")
        assert cli.main(["report"]) == 0
        again = json.loads(
            (tmp_path / "evidence" / "report.json").read_text(encoding="utf-8")
        )
        assert again["licence_status"] == "confirmed"
        assert (dataset / "public" / "manifest.json").read_bytes() == manifest
        (dataset / "public" / "stimuli" / "test.jsonl").write_bytes(b"tampered")
        assert cli.main(["verify"]) == 1

    def test_a_missing_plan_and_an_unknown_command_fail(self, tmp_path: Path) -> None:
        wired = SimulationCompositionRoot(
            OfflineSettings().build(tmp_path, True)
        ).wire()
        try:
            assert wired.commands.dispatch("nope") == 2
            assert wired.commands.dispatch("realise") == 1
            assert wired.commands.dispatch("freeze") == 1
            assert wired.commands.dispatch("verify") == 1
        finally:
            wired.close()

    def test_freeze_refuses_a_rejected_source(self, tmp_path: Path) -> None:
        settings = OfflineSettings().build(tmp_path, True)
        self._plan(settings.dataset_dir)
        source = (
            PinnedSource()
            .record()
            .model_copy(
                update={
                    "licence_review": "rejected",
                    "reviewed_by": "chair",
                    "reviewed_on": date(2026, 11, 3),
                    "review_note": "no",
                }
            )
        )
        errors = io.StringIO()
        commands = CampaignCommands(
            settings,
            FrozenClock(_WHEN),
            FileDatasetStore(settings.dataset_dir),
            EchoRoleModel(),
            (source,),
            None,
            AbsentTutor(),
            errors,
        )
        assert commands.dispatch("realise") == 0
        assert commands.dispatch("freeze") == 1
        assert "rejected" in errors.getvalue()

    def test_a_restricted_payload_is_not_written_under_public(
        self, tmp_path: Path
    ) -> None:
        settings = OfflineSettings().build(tmp_path, True)
        self._plan(settings.dataset_dir, _payload(redistributable=False))
        errors = io.StringIO()
        commands = CampaignCommands(
            settings,
            FrozenClock(_WHEN),
            FileDatasetStore(settings.dataset_dir),
            EchoRoleModel(),
            (PinnedSource().record(),),
            None,
            AbsentTutor(),
            errors,
        )
        assert commands.dispatch("realise") == 0
        assert (
            settings.dataset_dir / "restricted" / "stimuli" / "test.jsonl"
        ).is_file()
        assert commands.dispatch("freeze") == 0
        assert commands.dispatch("verify") == 0

    def test_a_named_payload_the_plan_lacks_fails_the_command(
        self, tmp_path: Path
    ) -> None:
        settings = OfflineSettings().build(tmp_path, True)
        plan = RealisePlan(
            dataset_version="sim-dataset/0.1.0",
            policy_version="prototype-2",
            seed=1,
            cases=(_case(payload_id="missing"),),
        )
        settings.dataset_dir.mkdir(parents=True)
        (settings.dataset_dir / "plan.json").write_text(
            plan.model_dump_json(), encoding="utf-8"
        )
        errors = io.StringIO()
        commands = CampaignCommands(
            settings,
            FrozenClock(_WHEN),
            FileDatasetStore(settings.dataset_dir),
            EchoRoleModel(),
            (PinnedSource().record(),),
            None,
            AbsentTutor(),
            errors,
        )
        assert commands.dispatch("realise") == 1
        assert "does not contain" in errors.getvalue()

    def test_verify_reports_a_split_that_moved_and_a_manifest_with_no_test_file(
        self, tmp_path: Path
    ) -> None:
        settings = OfflineSettings().build(tmp_path, True)
        self._plan(settings.dataset_dir)
        errors = io.StringIO()
        commands = CampaignCommands(
            settings,
            FrozenClock(_WHEN),
            FileDatasetStore(settings.dataset_dir),
            EchoRoleModel(),
            (PinnedSource().record(),),
            None,
            AbsentTutor(),
            errors,
        )
        assert commands.dispatch("realise") == 0
        assert commands.dispatch("freeze") == 0
        manifest_path = settings.dataset_dir / "public" / "manifest.json"
        manifest = ManifestFile().load(manifest_path)
        shifted = manifest.model_copy(update={"test_split_sha256": "ab" * 32})
        manifest_path.write_text(shifted.model_dump_json(), encoding="utf-8")
        with pytest.raises(ManifestMismatch, match="test split"):
            ManifestVerifier(settings.dataset_dir).verify(shifted)
        bare = manifest.model_copy(update={"files": manifest.files[2:]})
        with pytest.raises(ManifestMismatch, match="no test split"):
            ManifestVerifier(settings.dataset_dir).verify(bare)
        with pytest.raises(FileNotFoundError):
            ManifestFile().load(tmp_path / "absent.json")
        with pytest.raises(FileNotFoundError):
            PlanFile().load(tmp_path / "absent.json")

    def test_run_writes_observations_and_an_abort_is_an_exit(
        self, tmp_path: Path
    ) -> None:
        settings = OfflineSettings().build(tmp_path, True)
        self._plan(settings.dataset_dir)
        client = ScriptedTutor()
        errors = io.StringIO()
        commands = CampaignCommands(
            settings,
            FrozenClock(_WHEN),
            FileDatasetStore(settings.dataset_dir),
            EchoRoleModel(),
            (PinnedSource().record(),),
            client,
            AbsentTutor(),
            errors,
        )
        assert commands.dispatch("realise") == 0
        assert commands.dispatch("run") == 1
        assert "no manifest" in errors.getvalue()
        assert commands.dispatch("freeze") == 0
        assert commands.dispatch("run") == 0
        text = (settings.evidence_dir / "observations.jsonl").read_text(
            encoding="utf-8"
        )
        assert "c1" in text
        campaign = (settings.evidence_dir / "campaign.jsonl").read_text(
            encoding="utf-8"
        )
        assert CampaignLine.model_validate_json(campaign).errored is False
        client.health_kind = "errored"
        assert commands.dispatch("run") == 1
        client.health_kind = "ok"
        client.submit_kind = "errored"
        assert commands.dispatch("run") == 0
        written = (settings.evidence_dir / "observations.jsonl").read_text(
            encoding="utf-8"
        )
        assert written == ""
        failed = (settings.evidence_dir / "campaign.jsonl").read_text(encoding="utf-8")
        parsed = CampaignLine.model_validate_json(failed)
        assert parsed.errored is True
        assert parsed.case_id == "c1"
        assert parsed.observation is None
        (settings.dataset_dir / "public" / "stimuli" / "test.jsonl").write_bytes(
            b"tampered\n"
        )
        assert commands.dispatch("run") == 1
        (settings.dataset_dir / "public" / "stimuli" / "test.jsonl").unlink()
        (settings.dataset_dir / "public" / "stimuli" / "dev.jsonl").unlink()
        assert commands.dispatch("run") == 1
        assert commands.dispatch("freeze") == 1
        assert "active stimulus tree" in errors.getvalue()

    def test_verify_resolves_a_lone_unmarked_tree_and_refuses_a_missing_or_tampered_one(
        self, tmp_path: Path
    ) -> None:
        settings = OfflineSettings().build(tmp_path, True)
        settings.dataset_dir.mkdir(parents=True, exist_ok=True)
        errors = io.StringIO()
        commands = CampaignCommands(
            settings,
            FrozenClock(_WHEN),
            FileDatasetStore(settings.dataset_dir),
            EchoRoleModel(),
            (PinnedSource().record(),),
            None,
            AbsentTutor(),
            errors,
        )
        assert commands.dispatch("verify") == 1
        assert "no realised stimuli" in errors.getvalue()
        assert commands.dispatch("report") == 1
        self._plan(settings.dataset_dir)
        assert commands.dispatch("realise") == 0
        assert commands.dispatch("freeze") == 0
        (settings.dataset_dir / "active-tree.json").unlink()
        assert commands.dispatch("verify") == 0
        (settings.dataset_dir / "public" / "stimuli" / "test.jsonl").write_bytes(
            b"tampered\n"
        )
        assert commands.dispatch("report") == 1
        assert not (settings.evidence_dir / "report.json").exists()

    def test_an_errored_case_stays_in_the_report_denominator(self) -> None:
        request = ReportAssembly().request(
            "run-1",
            "sim-dataset/0.1.0",
            "tier-1",
            (_case(),),
            (CampaignLine(case_id="c1", errored=True),),
        )
        assert request.scored[0].result.errored is True
        assert request.scored[0].result.outcome_ok is False
        headline = MeasureSet().rates(request.scored)[0]
        assert headline.n == 1
        assert headline.k == 0

    def test_a_later_restricted_realisation_is_the_one_that_freezes(
        self, tmp_path: Path
    ) -> None:
        settings = OfflineSettings().build(tmp_path, True)
        self._plan(settings.dataset_dir)
        errors = io.StringIO()
        commands = CampaignCommands(
            settings,
            FrozenClock(_WHEN),
            FileDatasetStore(settings.dataset_dir),
            EchoRoleModel(),
            (PinnedSource().record(),),
            None,
            AbsentTutor(),
            errors,
        )
        assert commands.dispatch("realise") == 0
        self._plan(settings.dataset_dir, _payload(redistributable=False))
        assert commands.dispatch("realise") == 0
        assert commands.dispatch("freeze") == 0
        assert (settings.dataset_dir / "restricted" / "manifest.json").is_file()
        assert not (settings.dataset_dir / "public" / "manifest.json").is_file()
        (settings.dataset_dir / "active-tree.json").unlink()
        assert commands.dispatch("freeze") == 1
        assert "both stimulus trees" in errors.getvalue()

    def test_an_unchanged_freeze_is_kept_and_a_changed_tree_is_refused(
        self, tmp_path: Path
    ) -> None:
        settings = OfflineSettings().build(tmp_path, True)
        self._plan(settings.dataset_dir)
        errors = io.StringIO()
        commands = CampaignCommands(
            settings,
            FrozenClock(_WHEN),
            FileDatasetStore(settings.dataset_dir),
            EchoRoleModel(),
            (PinnedSource().record(),),
            None,
            AbsentTutor(),
            errors,
        )
        assert commands.dispatch("realise") == 0
        assert commands.dispatch("freeze") == 0
        manifest = settings.dataset_dir / "public" / "manifest.json"
        frozen = manifest.read_bytes()
        assert commands.dispatch("freeze") == 0
        assert manifest.read_bytes() == frozen
        discards = settings.dataset_dir / "public" / "discards.json"
        discards.write_text(
            discards.read_text(encoding="utf-8") + "\n", encoding="utf-8"
        )
        assert commands.dispatch("freeze") == 1
        assert "already frozen" in errors.getvalue()
        assert manifest.read_bytes() == frozen
        manifest.write_text("{", encoding="utf-8")
        assert commands.dispatch("freeze") == 1

    def test_a_live_command_refuses_the_echo_model(self, tmp_path: Path) -> None:
        settings = (
            OfflineSettings()
            .build(tmp_path, False)
            .model_copy(update={"role_fixture": False})
        )
        errors = io.StringIO()
        status = SimulationCli(SimulationCompositionRoot(settings), errors).main(
            ["realise"]
        )
        assert status == 1
        assert "role-model pin" in errors.getvalue()
        with pytest.raises(RoleUnpinned):
            SimulationCompositionRoot(settings).wire(errors)

    def test_a_distinct_role_pin_is_refused(self, tmp_path: Path) -> None:
        settings = OfflineSettings().build(tmp_path, True)
        self._plan(settings.dataset_dir)
        errors = io.StringIO()
        assert (
            SimulationCli(SimulationCompositionRoot(settings), errors).main(["realise"])
            == 0
        )
        role = "cd" * 32
        settings.runtime_pin_path.write_text(
            '[model]\nweights_sha = "'
            + ("ab" * 32)
            + '"\n[role_model]\nweights_sha = "'
            + role
            + '"\n',
            encoding="utf-8",
        )
        live = settings.model_copy(update={"role_fixture": False})
        assert (
            SimulationCli(SimulationCompositionRoot(live), errors).main(["freeze"]) == 1
        )
        assert "do not match" in errors.getvalue()
        assert not (settings.dataset_dir / "public" / "manifest.json").is_file()


class TestHttpTutorClient:
    def _client(self, handler: object) -> HttpTutorClient:
        transport = httpx.MockTransport(handler)  # type: ignore[arg-type]
        return HttpTutorClient(httpx.Client(transport=transport), "http://test")

    def test_status_codes_are_named_results(self) -> None:
        seen: dict[str, int] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            status = seen.get("status", 200)
            if status == 200 and request.url.path == "/learners":
                return httpx.Response(
                    200, json=[{"learner_id": str(_LEARNER), "retained": True}]
                )
            if status == 200 and request.url.path == "/health":
                return httpx.Response(
                    200,
                    json={
                        "status": "ok",
                        "database_configured": True,
                        "mode": "simulation",
                    },
                )
            if status == 201:
                return httpx.Response(
                    201,
                    json={
                        "session_id": str(_SESSION),
                        "learner_id": str(_LEARNER),
                        "open": True,
                    },
                )
            return httpx.Response(status, json={"detail": "no"})

        client = self._client(handler)
        assert client.health().body is not None
        assert client.health().body.mode == "simulation"  # type: ignore[union-attr]
        assert client.learners().body[0].retained is True
        seen["status"] = 201
        assert client.open_session(_LEARNER, "tutor").http_status == 201
        for status, kind in (
            (404, "not_found"),
            (409, "rejected"),
            (422, "session_rejected"),
            (503, "errored"),
            (500, "unexpected"),
        ):
            seen["status"] = status
            assert client.detail(_TURN).kind == kind
        assert StatusKind().of(200) == "ok"
        assert ResponseText().from_body("plain") == "plain"
        assert ResponseText().from_body({"detail": "no"}) == "no"
        assert ResponseText().from_body({"detail": 1}) == ""
        assert ResponseText().from_body(["nope"]) == ""

    def test_a_transport_error_and_a_bad_body_are_results(self) -> None:
        def explode(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("down")

        failed = self._client(explode).health()
        assert failed.kind == "errored"
        assert failed.http_status == 503

        def bad(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"not-json")

        assert self._client(bad).health().body is None

        def listed(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"detail": "not a list"})

        assert self._client(listed).learners().body == ()

    def test_an_edit_sends_the_text_and_an_approve_does_not(self) -> None:
        sent: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.content:
                sent["body"] = json.loads(request.content.decode())
            path = request.url.path
            if path.endswith("/replay"):
                return httpx.Response(
                    200, json={"turn_id": str(_TURN), "outcome": "reproduced"}
                )
            if path.endswith("/audit"):
                return httpx.Response(200, json={"intact": True})
            if path == "/turns":
                return httpx.Response(
                    200,
                    json={
                        "turn_id": str(_TURN),
                        "session_id": str(_SESSION),
                        "status": "awaiting_tutor_approval",
                        "refused": False,
                        "policy_version": "prototype-2",
                    },
                )
            return httpx.Response(
                200,
                json={
                    "action": {
                        "turn_id": str(_TURN),
                        "tutor_id": "tutor",
                        "action": "edit",
                        "acted_at": "2026-11-03T00:00:00Z",
                    },
                    "stopped": False,
                },
            )

        client = self._client(handler)
        assert client.act(_SESSION, _TURN, "tutor", "edit", "the draft").kind == "ok"
        assert sent["body"] == {
            "tutor_id": "tutor",
            "action": "edit",
            "edited_output": "the draft",
        }
        assert client.act(_SESSION, _TURN, "tutor", "approve", None).kind == "ok"
        assert "edited_output" not in sent["body"]  # type: ignore[operator]
        assert (
            client.submit(_SESSION, _LEARNER, "hello", ("proficiency_level",)).kind
            == "ok"
        )
        assert client.audit(_SESSION).kind == "ok"
        assert client.replay(_TURN).kind == "ok"
        acted = client.act(_SESSION, _TURN, "tutor", "approve", None)
        assert acted.body is not None
        assert acted.body.action.action == "edit"
        assert acted.body.stopped is False

    def test_a_turn_detail_parses_the_nested_prompt_and_a_string_does_not(
        self,
    ) -> None:
        from tutor_sim.domain.models.api_views import RecordView, StoredPromptView

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "session": {"session_id": str(_SESSION)},
                    "record": {
                        "turn_id": str(_TURN),
                        "learner_prompt": {
                            "text": "hello there",
                            "redacted_categories": ["person"],
                        },
                        "retrieved_context_ids": ["chunk-1"],
                        "output_before_checks": "a draft",
                        "output_after_checks": "a draft",
                    },
                    "actions": [],
                    "cited": [],
                    "record_intact": True,
                },
            )

        detail = self._client(handler).detail(_TURN)
        assert detail.body is not None
        prompt = detail.body.record.learner_prompt
        assert isinstance(prompt, StoredPromptView)
        assert prompt.text == "hello there"
        assert prompt.redacted_categories == ("person",)
        with pytest.raises(ValidationError):
            RecordView.model_validate({"learner_prompt": "hello there"})
        from tutor_sim.domain.models.api_views import RecordedActionView

        with pytest.raises(ValidationError):
            RecordedActionView.model_validate({"action": "approve", "stopped": False})
