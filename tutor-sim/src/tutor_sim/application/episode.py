"""Run one Tier 2 episode of at most eight turns (DEC-0015, SIMULATION §8.3)."""

from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from tutor_sim.application.oracle import InvariantFacts, OutcomeClassifier
from tutor_sim.application.tier1 import (
    CampaignAbort,
    HaltedDecision,
    ModeGuard,
    RetainedLearner,
    TurnObservation,
    TutorAction,
)
from tutor_sim.domain.models.api_views import TurnOutcomeView
from tutor_sim.domain.models.case import EpisodeSpec
from tutor_sim.domain.models.episode import EpisodeTranscript, EpisodeTurn
from tutor_sim.domain.models.observation import ActionAttempt, Observation
from tutor_sim.domain.models.tutor_role import DashboardView, TutorDecision
from tutor_sim.domain.ports.role_model import RoleModelPort
from tutor_sim.domain.ports.tutor_client import TutorClientPort
from tutor_sim.domain.ports.tutor_role import TutorRolePort


class EpisodePlanFile:
    """``episodes/plan.jsonl`` in the frozen tree. One ``EpisodeSpec`` per line."""

    def body(self, specs: tuple[EpisodeSpec, ...]) -> bytes:
        """The bytes ``realise`` writes. No episodes is an empty file."""
        if not specs:
            return b""
        return ("\n".join(spec.model_dump_json() for spec in specs) + "\n").encode(
            "utf-8"
        )

    def read(self, path: Path) -> tuple[EpisodeSpec, ...]:
        """Parse every non-blank line. A missing file is a command error."""
        if not path.is_file():
            msg = "no episode plan"
            raise FileNotFoundError(msg)
        return tuple(
            EpisodeSpec.model_validate_json(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line
        )


class TranscriptFile:
    """``runs/<run_id>/transcripts/<episode_id>.jsonl``, one turn per line.

    Written by atomic rename, as ``RunDirectory`` writes the report, so a
    reader never sees half a transcript.
    """

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def write(self, transcript: EpisodeTranscript) -> Path:
        """Replace this episode's transcript and return its path."""
        self._directory.mkdir(parents=True, exist_ok=True)
        path = self._directory / f"{transcript.episode_id}.jsonl"
        partial = path.with_name(f".{path.name}.partial")
        body = "".join(turn.model_dump_json() + "\n" for turn in transcript.turns)
        partial.write_text(body, encoding="utf-8")
        partial.replace(path)
        return path


class EpisodeRecord(BaseModel):
    """The transcript, and one set of invariant facts per submitted turn."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    transcript: EpisodeTranscript
    facts: tuple[InvariantFacts, ...]


class StopCheck(BaseModel):
    """What INV-7 reads after a recorded stop."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    later_turns_refused: bool
    earlier_turns_readable: bool


class EpisodeRunner:
    """The pupil replies to what was released. A stop submits nothing further.

    ``approve`` releases the draft and ``edit`` releases the tutor's text,
    as the API does. ``override`` sets the draft aside and T3 records
    ``none``; neither releases anything. Every turn is read, replayed and
    audited, so Tier 2 records the same observation Tier 1 does.

    S1 must pause at drift on the planned turn, or the campaign aborts.
    S2 records the stop, then checks INV-7: one more ``POST /turns`` must
    be refused, and every turn up to the stop must still read and replay.
    A failure there is an invariant fact, not an abort: it fails the run
    in the report instead of hiding it.
    """

    def __init__(
        self,
        client: TutorClientPort,
        role: TutorRolePort,
        pupil: RoleModelPort,
        mode: ModeGuard,
        transcripts: TranscriptFile,
    ) -> None:
        self._client = client
        self._role = role
        self._pupil = pupil
        self._mode = mode
        self._transcripts = transcripts
        self._roster = RetainedLearner()
        self._action = TutorAction(client)
        self._observe = TurnObservation()
        self._class = OutcomeClassifier()
        self._halted = HaltedDecision()

    def run(
        self,
        spec: EpisodeSpec,
        learner_id: UUID,
        tutor_id: str,
        persona: str,
    ) -> EpisodeRecord:
        """Submit up to ``spec.max_turns``, write the transcript, return both."""
        self._mode.check(self._client.health())
        listed = self._client.learners()
        if listed.kind != "ok":
            msg = "the learner roster could not be read"
            raise CampaignAbort(msg)
        self._roster.require(learner_id, listed.body)
        opened = self._client.open_session(learner_id, tutor_id)
        if opened.kind != "ok" or opened.body is None:
            msg = "the episode session did not open"
            raise CampaignAbort(msg)
        session_id = opened.body.session_id
        released: str | None = None
        turns: list[EpisodeTurn] = []
        observations: list[Observation] = []
        stop: ActionAttempt | None = None
        prompt = ""
        for index in range(spec.max_turns):
            prompt = self._pupil.complete(persona, released or "Begin the lesson.")
            submitted = self._client.submit(session_id, learner_id, prompt, ())
            if submitted.kind != "ok" or submitted.body is None:
                msg = "a turn in the episode was not accepted"
                raise CampaignAbort(msg)
            body = submitted.body
            decision = self._role.decide(self._view(body, index))
            attempt = self._action.attempt(session_id, body.turn_id, tutor_id, decision)
            if attempt is None:
                msg = "the tutor action was not recorded"
                raise CampaignAbort(msg)
            observation, replay = self._observation(
                spec, index, session_id, body, attempt
            )
            observations.append(observation)
            released = self._released(body.reply, decision)
            turns.append(
                EpisodeTurn(
                    turn_id=body.turn_id,
                    turn_index=index,
                    prompt=prompt,
                    released=released,
                    halted_at=body.halted_at,
                    decision=decision.decision,
                    replay_outcome=replay,
                )
            )
            if decision.decision == "stop":
                stop = attempt
                break
            if (
                spec.script == "S1_drift"
                and index == spec.stop_at_turn
                and body.halted_at != "drift_and_anomaly"
            ):
                msg = "S1 did not pause at drift on the planned turn"
                raise CampaignAbort(msg)
        transcript = EpisodeTranscript(
            episode_id=spec.episode_id, turns=tuple(turns), stopped=stop is not None
        )
        self._transcripts.write(transcript)
        check = None
        if stop is not None and self._recorded(stop):
            check = self._after_stop(session_id, learner_id, prompt, tuple(turns))
        return EpisodeRecord(
            transcript=transcript,
            facts=self._facts(tuple(observations), check),
        )

    def _view(self, body: TurnOutcomeView, index: int) -> DashboardView:
        return DashboardView(
            status=(
                "held_for_review"
                if body.halted_at is not None or body.refused
                else "awaiting_tutor_approval"
            ),
            output_before_checks=body.reply,
            turn_index=index,
            policy_version=body.policy_version,
        )

    def _observation(
        self,
        spec: EpisodeSpec,
        index: int,
        session_id: UUID,
        body: TurnOutcomeView,
        attempt: ActionAttempt,
    ) -> tuple[Observation, str]:
        """Read, replay and audit the turn just acted on."""
        detail = self._client.detail(body.turn_id)
        if detail.kind != "ok" or detail.body is None:
            msg = "a turn in the episode could not be read"
            raise CampaignAbort(msg)
        replay = self._client.replay(body.turn_id)
        if replay.kind != "ok" or replay.body is None:
            msg = "a turn in the episode could not be replayed"
            raise CampaignAbort(msg)
        audit = self._client.audit(session_id)
        if audit.kind != "ok" or audit.body is None:
            msg = "the episode audit could not be read"
            raise CampaignAbort(msg)
        outcome = self._class.classify(
            body.halted_at, self._halted.of(body), body.refused, body.status
        )
        if outcome is None:
            msg = f"a turn in the episode returned status {body.status}"
            raise CampaignAbort(msg)
        observation = self._observe.build(
            f"{spec.episode_id}#{index}",
            body,
            detail.body,
            attempt,
            replay.body.outcome,
            audit.body.intact,
            outcome,
            (),
        )
        return observation, replay.body.outcome

    def _after_stop(
        self,
        session_id: UUID,
        learner_id: UUID,
        prompt: str,
        turns: tuple[EpisodeTurn, ...],
    ) -> StopCheck:
        """INV-7. The probe is the last prompt again; it must not be recorded."""
        probe = self._client.submit(session_id, learner_id, prompt, ())
        readable = True
        for turn in turns:
            detail = self._client.detail(turn.turn_id)
            replay = self._client.replay(turn.turn_id)
            if detail.kind != "ok" or replay.kind != "ok":
                readable = False
        return StopCheck(
            later_turns_refused=probe.kind == "session_rejected",
            earlier_turns_readable=readable,
        )

    def _facts(
        self, observations: tuple[Observation, ...], check: StopCheck | None
    ) -> tuple[InvariantFacts, ...]:
        """The stop facts sit on the turn that recorded the stop."""
        facts: list[InvariantFacts] = []
        for observation in observations:
            stopped = check is not None and self._is_stop(observation)
            facts.append(
                InvariantFacts(
                    observation=observation,
                    edit_accepted=self._accepted_edit(observation),
                    session_stopped=stopped,
                    later_turns_refused=(
                        check.later_turns_refused if check and stopped else True
                    ),
                    earlier_turns_readable=(
                        check.earlier_turns_readable if check and stopped else True
                    ),
                )
            )
        return tuple(facts)

    def _recorded(self, attempt: ActionAttempt) -> bool:
        return attempt.recorded_action == "stop" and 200 <= attempt.http_status < 300

    def _is_stop(self, observation: Observation) -> bool:
        return observation.action is not None and self._recorded(observation.action)

    def _accepted_edit(self, observation: Observation) -> bool:
        action = observation.action
        if action is None or action.decision != "edit":
            return False
        return 200 <= action.http_status < 300

    def _released(self, reply: str | None, decision: TutorDecision) -> str | None:
        if decision.decision == "approve":
            return reply
        if decision.decision == "edit":
            return decision.edited_output
        return None
