"""Run one episode of at most eight turns (DEC-0015)."""

from uuid import UUID

from tutor_sim.application.tier1 import CampaignAbort, ModeGuard
from tutor_sim.domain.models.case import EpisodeSpec
from tutor_sim.domain.models.episode import EpisodeTranscript, EpisodeTurn
from tutor_sim.domain.models.tutor_role import DashboardView, TutorDecision
from tutor_sim.domain.ports.role_model import RoleModelPort
from tutor_sim.domain.ports.tutor_client import TutorClientPort
from tutor_sim.domain.ports.tutor_role import TutorRolePort


class EpisodeRunner:
    """The pupil replies to what was released. A stop submits nothing further.

    ``approve`` releases the draft and ``edit`` releases the tutor's text,
    as the API does. ``override`` sets the draft aside and T3 records
    ``none``; neither releases anything. S1 records a drift halt on the
    planned turn. S2 records the stop and leaves the later turns out.
    """

    def __init__(
        self,
        client: TutorClientPort,
        role: TutorRolePort,
        pupil: RoleModelPort,
        mode: ModeGuard,
    ) -> None:
        self._client = client
        self._role = role
        self._pupil = pupil
        self._mode = mode

    def run(
        self,
        spec: EpisodeSpec,
        learner_id: UUID,
        tutor_id: str,
        persona: str,
    ) -> EpisodeTranscript:
        """Submit up to ``spec.max_turns`` and return the transcript."""
        self._mode.check(self._client.health())
        opened = self._client.open_session(learner_id, tutor_id)
        if opened.kind != "ok" or opened.body is None:
            msg = "the episode session did not open"
            raise CampaignAbort(msg)
        session_id = opened.body.session_id
        released: str | None = None
        turns: list[EpisodeTurn] = []
        stopped = False
        for index in range(spec.max_turns):
            prompt = self._pupil.complete(persona, released or "Begin the lesson.")
            submitted = self._client.submit(session_id, learner_id, prompt, ())
            if submitted.kind != "ok" or submitted.body is None:
                msg = "a turn in the episode was not accepted"
                raise CampaignAbort(msg)
            body = submitted.body
            view = DashboardView(
                status=(
                    "held_for_review"
                    if body.halted_at is not None or body.refused
                    else "awaiting_tutor_approval"
                ),
                output_before_checks=body.reply,
                turn_index=index,
                policy_version=body.policy_version,
            )
            decision = self._role.decide(view)
            self._act(session_id, body.turn_id, tutor_id, decision)
            released = self._released(body.reply, decision)
            turns.append(
                EpisodeTurn(
                    turn_index=index,
                    prompt=prompt,
                    released=released,
                    halted_at=body.halted_at,
                    decision=decision.decision,
                )
            )
            if decision.decision == "stop":
                stopped = True
                break
            if (
                spec.script == "S1_drift"
                and index == spec.stop_at_turn
                and body.halted_at != "drift_and_anomaly"
            ):
                msg = "S1 did not pause at drift on the planned turn"
                raise CampaignAbort(msg)
        return EpisodeTranscript(
            episode_id=spec.episode_id, turns=tuple(turns), stopped=stopped
        )

    def _released(self, reply: str | None, decision: TutorDecision) -> str | None:
        if decision.decision == "approve":
            return reply
        if decision.decision == "edit":
            return decision.edited_output
        return None

    def _act(
        self,
        session_id: UUID,
        turn_id: UUID,
        tutor_id: str,
        decision: TutorDecision,
    ) -> None:
        if decision.decision == "none":
            return
        acted = self._client.act(
            session_id,
            turn_id,
            tutor_id,
            decision.decision,
            decision.edited_output,
        )
        if acted.kind != "ok":
            msg = "the tutor action was not recorded"
            raise CampaignAbort(msg)
