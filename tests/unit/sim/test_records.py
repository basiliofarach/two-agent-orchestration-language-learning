"""Every dataset record rejects undeclared fields and stays frozen."""

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import BaseModel, ValidationError

from tutor_sim.domain.models.case import (
    CaseSpec,
    Construction,
    EpisodeSpec,
    Expected,
    GeneratorStamp,
    StimulusCase,
)
from tutor_sim.domain.models.expectation import ExpectationRow, ExpectationTable
from tutor_sim.domain.models.kb import KbDocumentRecord
from tutor_sim.domain.models.learner import HistoryEventRecord, PersonaLearnerRecord
from tutor_sim.domain.models.manifest import (
    FileDigest,
    Manifest,
    RoleModelPin,
    SourceRef,
)
from tutor_sim.domain.models.observation import (
    ActionAttempt,
    LeakHit,
    Observation,
    ObservedGate,
)
from tutor_sim.domain.models.payload import Payload
from tutor_sim.domain.models.persona import ErrorRate, FewShotTurn, PersonaCard, Traits
from tutor_sim.domain.models.report import (
    CaseResult,
    InvariantRow,
    RateRow,
    SimulationReport,
)
from tutor_sim.domain.models.source import SourceRecord
from tutor_sim.domain.models.storage import DatasetWrite
from tutor_sim.domain.models.tutor_role import TutorRoleCard

_SHA = "ab" * 32
_ID = UUID("00000000-0000-4000-8000-0000000000a1")
_WHEN = datetime(2026, 11, 3, 12, tzinfo=UTC)


class Records:
    def source(self, **updates: object) -> SourceRecord:
        payload: dict[str, object] = {
            "source_id": "clear-corpus",
            "title": "CLEAR",
            "url": "https://example.invalid/clear",
            "revision": "2026-11-03",
            "sha256": _SHA,
            "licence": "custom:public-domain-excerpts",
            "licence_url": "https://example.invalid/licence",
            "redistributable": True,
            "use": "kb",
            "attribution": "Crossley et al. 2023",
        }
        payload.update(updates)
        return SourceRecord.model_validate(payload)

    def document(self, **updates: object) -> KbDocumentRecord:
        payload: dict[str, object] = {
            "document_id": _ID,
            "source_uri": "kb://clear-corpus/item",
            "version": "2026-11-03",
            "review_status": "approved",
            "licence": "custom:public-domain-excerpts",
            "cefr_level": "A2",
            "level_method": "cefr-j-1.6-coverage-95",
            "partition": "default",
            "topic_id": "greetings",
            "content": "Hola means hello.",
            "content_sha256": _SHA,
        }
        payload.update(updates)
        return KbDocumentRecord.model_validate(payload)

    def learner(self, **updates: object) -> PersonaLearnerRecord:
        payload: dict[str, object] = {
            "persona_id": "p-a2-es-12_14-01",
            "learner_id": _ID,
            "pseudonym": "p-a2-es-12_14-01",
            "proficiency_level": "A2",
            "history": (
                {"item_id": "greet-1", "correct": True, "days_before_seed": 1},
            ),
        }
        payload.update(updates)
        return PersonaLearnerRecord.model_validate(payload)

    def persona(self, **updates: object) -> PersonaCard:
        payload: dict[str, object] = {
            "persona_id": "p-a2-es-12_14-01",
            "card_version": "1",
            "age": 13,
            "age_band": "12-14",
            "cefr_level": "A2",
            "l1": "es",
            "traits": {
                "verbosity": "low",
                "help_seeking": "mid",
                "off_task": "low",
                "code_switching": "low",
            },
            "interests": ("greetings", "school"),
            "error_profile": ({"error_type": "R:SPELL", "rate": 0.2},),
            "system_prompt": "You are a pupil.",
            "few_shot": tuple(
                {
                    "role": "learner",
                    "text": f"turn {index}",
                    "source_id": "ellipse",
                    "licence": "CC-BY-4.0",
                }
                for index in range(3)
            ),
            "grounding": ("ellipse",),
        }
        payload.update(updates)
        return PersonaCard.model_validate(payload)

    def tutor(self, **updates: object) -> TutorRoleCard:
        payload: dict[str, object] = {
            "role": "T1",
            "driver": "model",
            "system_prompt": "Relay the draft.",
            "few_shot": ("Approve when every gate passed.",),
        }
        payload.update(updates)
        return TutorRoleCard.model_validate(payload)

    def payload(self, **updates: object) -> Payload:
        payload: dict[str, object] = {
            "payload_id": "pii-1",
            "category": "pii",
            "text": "me llamo Ada",
            "source_id": "synthetic-pii",
            "licence": "custom:generated",
            "redistributable": True,
            "split": "test",
            "language": "es",
            "pii_kind": "name",
            "pii_value": "Ada",
        }
        payload.update(updates)
        return Payload.model_validate(payload)

    def expected(self) -> Expected:
        return Expected(accept=("released_for_approval",), basis="construction")

    def case(self) -> CaseSpec:
        return CaseSpec(
            case_id="c-000001",
            dataset_version="sim-dataset/0.1.0",
            policy_version="prototype-2",
            split="test",
            persona_id="p-a2-es-12_14-01",
            intent="I1",
            variant="canonical",
            expected=self.expected(),
        )

    def stimulus(self) -> StimulusCase:
        case = self.case()
        return StimulusCase(
            **case.model_dump(),
            utterance="Hola, where is the library?",
            construction=Construction(
                payload_present=True, attempts=1, discarded=False
            ),
            generator=GeneratorStamp(
                weights_sha=_SHA,
                seed=1,
                temperature=0.0,
                template_version="1",
                card_version="1",
            ),
        )

    def manifest(self, frozen_at: datetime = _WHEN) -> Manifest:
        return Manifest(
            dataset_version="sim-dataset/0.1.0",
            seed=1,
            policy_version="prototype-2",
            role_model=RoleModelPin(name="mistral", weights_sha=_SHA),
            sources=(
                SourceRef(
                    source_id="clear-corpus",
                    revision="2026-11-03",
                    sha256=_SHA,
                    licence="custom:public-domain-excerpts",
                    licence_review="pending",
                ),
            ),
            files=(
                FileDigest(path="sources.json", tree="public", sha256=_SHA, bytes=10),
            ),
            test_split_sha256=_SHA,
            frozen_at=frozen_at,
        )

    def observation(self) -> Observation:
        return Observation(
            case_id="c-000001",
            turn_id=_ID,
            status="held",
            refused=False,
            model_called=True,
            retrieval_ran=True,
            gate_rows=(ObservedGate(name="sensitivity", decision="pause"),),
            reply_present=True,
            disclosure_present=True,
            action=ActionAttempt(decision="none", http_status=200),
            replay_matches=True,
            chain_intact=True,
            leaks=(LeakHit(field="reply", payload_id="pii-1"),),
            outcome="held",
        )

    def report(self) -> SimulationReport:
        return SimulationReport(
            run_id="run-1",
            dataset_version="sim-dataset/0.1.0",
            label="simulated:sim-dataset/0.1.0",
            licence_status="pending",
            pending_sources=("fce",),
            rates=(RateRow(name="accuracy", basis="construction", k=1, n=2),),
            invariants=(InvariantRow(invariant_id="chain", passed=True),),
            finished=True,
        )

    def all(self) -> tuple[BaseModel, ...]:
        return (
            self.source(),
            DatasetWrite(
                relative_path="a.txt", body=b"a", redistributable=True, tree="public"
            ),
            self.document(),
            HistoryEventRecord(item_id="greet-1", correct=True, days_before_seed=0),
            self.learner(),
            Traits(
                verbosity="low",
                help_seeking="mid",
                off_task="low",
                code_switching="low",
            ),
            ErrorRate(error_type="R:SPELL", rate=0.2),
            FewShotTurn(
                role="learner", text="hola", source_id="ellipse", licence="CC-BY-4.0"
            ),
            self.persona(),
            self.tutor(),
            TutorRoleCard(role="T2", driver="script"),
            TutorRoleCard(role="T4", driver="script", stop_at_turn=2),
            self.payload(),
            self.expected(),
            self.case(),
            Construction(payload_present=False, attempts=3, discarded=True),
            GeneratorStamp(
                weights_sha=_SHA,
                seed=1,
                temperature=0.0,
                template_version="1",
                card_version="1",
            ),
            self.stimulus(),
            EpisodeSpec(
                episode_id="e-1",
                persona_id="p-a2-es-12_14-01",
                tutor_role="T1",
                max_turns=8,
                script="open",
                planned_intents=("I1",),
            ),
            ExpectationRow(intent="I1", variant="canonical", expected=self.expected()),
            ExpectationTable(policy_version="prototype-2", rows=()),
            RoleModelPin(name="mistral", weights_sha=_SHA),
            SourceRef(
                source_id="clear-corpus",
                revision="2026-11-03",
                sha256=_SHA,
                licence="custom:public-domain-excerpts",
                licence_review="pending",
            ),
            FileDigest(path="sources.json", tree="public", sha256=_SHA, bytes=0),
            self.manifest(),
            ObservedGate(name="sensitivity", decision="pass"),
            ActionAttempt(
                decision="approve", http_status=200, recorded_action="approve"
            ),
            LeakHit(field="reply", payload_id="pii-1"),
            self.observation(),
            CaseResult(
                case_id="c-000001",
                outcome_ok=True,
                gate_attribution="n/a",
                rule_ok=None,
                errored=False,
                observed="released_for_approval",
            ),
            RateRow(name="accuracy", k=0, n=0),
            InvariantRow(invariant_id="chain", passed=False),
            self.report(),
        )


class TestRecords:
    def test_every_record_rejects_an_undeclared_field_and_assignment(self) -> None:
        for record in Records().all():
            payload = record.model_dump()
            payload["nope"] = 1
            with pytest.raises(ValidationError):
                type(record).model_validate(payload)
            field = next(iter(type(record).model_fields))
            with pytest.raises(ValidationError):
                setattr(record, field, getattr(record, field))

    def test_a_floating_revision_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="pinned"):
            Records().source(revision="latest")

    def test_a_pending_review_has_no_reviewer(self) -> None:
        with pytest.raises(ValidationError, match="pending"):
            Records().source(reviewed_by="author")

    def test_a_decided_review_names_the_reviewer(self) -> None:
        with pytest.raises(ValidationError, match="reviewer"):
            Records().source(licence_review="confirmed")
        decided = Records().source(
            licence_review="confirmed",
            reviewed_by="author",
            reviewed_on="2026-11-03",
            review_note="The terms allow redistribution.",
        )
        assert decided.licence_review == "confirmed"

    def test_whitespace_is_not_a_document(self) -> None:
        with pytest.raises(ValidationError, match="no passages"):
            Records().document(content="  ")

    def test_the_default_partition_has_no_fault(self) -> None:
        with pytest.raises(ValidationError, match="no fault"):
            Records().document(fault_kind="contradiction")

    def test_a_fault_names_its_kind(self) -> None:
        with pytest.raises(ValidationError, match="names its kind"):
            Records().document(partition="faults")
        poisoned = Records().document(
            partition="faults",
            fault_kind="poisoned_approved",
            review_status="approved",
            canary="CANARY-7F3",
        )
        assert poisoned.canary == "CANARY-7F3"

    def test_a_canary_belongs_only_to_poison(self) -> None:
        with pytest.raises(ValidationError, match="canary"):
            Records().document(canary="CANARY-7F3")
        with pytest.raises(ValidationError, match="canary"):
            Records().document(
                partition="faults", fault_kind="poisoned_unreviewed", canary=None
            )

    def test_the_pseudonym_is_the_persona_id(self) -> None:
        with pytest.raises(ValidationError, match="pseudonym"):
            Records().learner(pseudonym="Ada")

    def test_proficiency_stops_at_b2(self) -> None:
        with pytest.raises(ValidationError):
            Records().learner(proficiency_level="C1")

    def test_the_age_band_matches_the_age(self) -> None:
        with pytest.raises(ValidationError, match="age band"):
            Records().persona(age=16, age_band="12-14")
        older = Records().persona(age=16, age_band="15-17")
        assert older.age_band == "15-17"

    def test_error_rates_cannot_sum_past_one(self) -> None:
        with pytest.raises(ValidationError, match="sum past one"):
            Records().persona(
                error_profile=(
                    {"error_type": "R:SPELL", "rate": 0.6},
                    {"error_type": "R:VERB", "rate": 0.6},
                )
            )

    def test_scripted_roles_have_no_prompt(self) -> None:
        with pytest.raises(ValidationError, match="T1"):
            Records().tutor(driver="script")
        with pytest.raises(ValidationError, match="T1"):
            Records().tutor(system_prompt=None)
        with pytest.raises(ValidationError, match="T1"):
            Records().tutor(stop_at_turn=1)
        with pytest.raises(ValidationError, match="scripted"):
            Records().tutor(role="T2", driver="model")
        with pytest.raises(ValidationError, match="scripted"):
            Records().tutor(role="T2", driver="script", system_prompt="no")
        with pytest.raises(ValidationError, match="scripted"):
            Records().tutor(
                role="T2", driver="script", system_prompt=None, few_shot=("no",)
            )
        with pytest.raises(ValidationError, match="T4"):
            Records().tutor(role="T4", driver="script", system_prompt=None, few_shot=())
        with pytest.raises(ValidationError, match="only T4"):
            Records().tutor(
                role="T2",
                driver="script",
                system_prompt=None,
                few_shot=(),
                stop_at_turn=1,
            )

    def test_only_pii_is_spanish_or_named(self) -> None:
        with pytest.raises(ValidationError, match="PII"):
            Records().payload(pii_kind=None)
        with pytest.raises(ValidationError, match="PII"):
            Records().payload(
                category="open_web", language="en", pii_kind="email", pii_value=None
            )
        with pytest.raises(ValidationError, match="PII"):
            Records().payload(
                category="open_web", language="es", pii_kind=None, pii_value=None
            )
        with pytest.raises(ValidationError, match="PII"):
            Records().payload(
                category="open_web", language="en", pii_kind=None, pii_value="Ada"
            )
        english = Records().payload(
            category="open_web",
            language="en",
            pii_kind=None,
            pii_value=None,
            text="search the web",
        )
        assert english.language == "en"

    def test_a_pii_payload_names_the_value_it_plants(self) -> None:
        with pytest.raises(ValidationError, match="names its value"):
            Records().payload(pii_value=None)
        with pytest.raises(ValidationError, match="planted"):
            Records().payload(pii_value="Grace")
        assert Records().payload().pii_value == "Ada"

    def test_an_episode_stops_at_eight_turns(self) -> None:
        with pytest.raises(ValidationError):
            EpisodeSpec(
                episode_id="e-1",
                persona_id="p-a2-es-12_14-01",
                tutor_role="T1",
                max_turns=9,
                script="open",
                planned_intents=("I1",),
            )

    def test_a_recorded_instant_is_utc(self) -> None:
        with pytest.raises(ValidationError, match="timezone-aware"):
            Records().manifest(datetime(2026, 11, 3, 12))
        shifted = datetime(2026, 11, 3, 12, tzinfo=timezone(timedelta(hours=2)))
        assert Records().manifest(shifted).frozen_at == datetime(
            2026, 11, 3, 10, tzinfo=UTC
        )
