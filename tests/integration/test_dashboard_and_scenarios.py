"""Dashboard routes, scripted cases, replay, retention and evidence, on Postgres.

Real container, real gates, real database with every migration applied and
the restricted application login. Only the model is stubbed, for
determinism (rule 7).
"""

import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from tests.integration.test_turn_router import Served
from tests.support.migrated_database import MigratedDatabase, PostgresUrl
from tests.support.turn_app import TurnApp
from tests.support.turn_stubs import RecordingModel

from tutor_api.adapters.persistence.audit_query import (
    AuditRecordDecoder,
    PostgresAuditQuery,
)
from tutor_api.adapters.persistence.database import DatabaseEngine
from tutor_api.adapters.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tutor_api.evidence.__main__ import EvidenceMain, ModelPin, PackPaths
from tutor_api.evidence.survey import ChainSurvey, ChainSurveyResult
from tutor_api.retention.__main__ import RetentionMain
from tutor_api.retention.purge import PurgeLog, RetentionPurge
from tutor_core.application.evaluation.rubric import (
    Rubric,
    RubricScore,
    ScenarioCase,
    ScenarioCatalogue,
    ScenarioObservation,
    ScenarioObserver,
)
from tutor_core.domain.audit.chain import ChainVerifier
from tutor_core.domain.models.conduct import TurnOutcome
from tutor_core.domain.ports.cipher import CipherPort
from tutor_core.domain.ports.clock import ClockPort

QUESTION = "What does hola mean in Spanish?"


@pytest.fixture
async def served(fresh_database: str) -> Served:
    served = Served(fresh_database, RecordingModel("Hola means hello in Spanish."))
    await served.install()
    return served


class Dashboard:
    """Requests a tutor's dashboard makes, over one client."""

    def __init__(self, served: Served, client: TestClient) -> None:
        self.served = served
        self.client = client

    @property
    def session_id(self) -> str:
        assert self.served.plan is not None
        return str(self.served.plan.session_id)

    def turn(self, prompt: str = QUESTION) -> dict[str, object]:
        response = self.client.post("/turns", json=self.served.body(prompt))
        assert response.status_code == 200, response.text
        return cast(dict[str, object], response.json())

    def act(
        self,
        turn: dict[str, object],
        action: str,
        edited_output: str | None = None,
        session_id: str | None = None,
    ):  # noqa: ANN201 — an httpx response
        body: dict[str, object] = {"tutor_id": "tutor-demo", "action": action}
        if edited_output is not None:
            body["edited_output"] = edited_output
        session = session_id or str(turn["session_id"])
        return self.client.post(
            f"/sessions/{session}/turns/{turn['turn_id']}/actions", json=body
        )


@pytest.fixture
def dashboard(served: Served) -> Iterator[Dashboard]:
    for client in served.client():
        yield Dashboard(served, client)


class TestSessions:
    async def test_a_tutor_opens_reads_and_lists_a_session(
        self, dashboard: Dashboard
    ) -> None:
        assert dashboard.served.plan is not None
        learner = str(dashboard.served.plan.learner_id)
        opened = dashboard.client.post(
            "/sessions", json={"learner_id": learner, "tutor_id": "tutor-demo"}
        )
        assert opened.status_code == 201, opened.text
        session = opened.json()
        assert session["open"] is True
        read = dashboard.client.get(f"/sessions/{session['session_id']}")
        assert read.status_code == 200
        assert read.json() == session
        listed = dashboard.client.get("/sessions").json()
        assert listed[0]["session_id"] == session["session_id"]
        tutor = dashboard.served.rows(
            "SELECT tutor_id FROM tutoring_session WHERE id = %s",
            UUID(session["session_id"]),
        )[0][0]
        assert b"tutor-demo" not in bytes(cast(bytes, tutor))

    async def test_a_learner_is_listed_by_id_without_a_pseudonym(
        self, dashboard: Dashboard
    ) -> None:
        learners = dashboard.client.get("/learners")
        assert learners.status_code == 200
        assert set(learners.json()[0]) == {"learner_id", "retained"}

    async def test_an_unknown_learner_cannot_be_given_a_session(
        self, dashboard: Dashboard
    ) -> None:
        refused = dashboard.client.post(
            "/sessions", json={"learner_id": str(uuid4()), "tutor_id": "t"}
        )
        assert refused.status_code == 422
        assert dashboard.served.rows("SELECT count(*) FROM tutoring_session") == [(1,)]

    @pytest.mark.parametrize("suffix", ["", "/audit", "/events"])
    async def test_an_unknown_session_is_404(
        self, dashboard: Dashboard, suffix: str
    ) -> None:
        response = dashboard.client.get(f"/sessions/{uuid4()}{suffix}")
        assert response.status_code == 404

    async def test_the_dashboard_origin_is_allowed_by_cors(
        self, dashboard: Dashboard
    ) -> None:
        response = dashboard.client.options(
            "/sessions",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert (
            response.headers["access-control-allow-origin"] == "http://localhost:5173"
        )


class TestTutorActions:
    async def test_one_decision_then_a_stop_then_nothing(
        self, dashboard: Dashboard
    ) -> None:
        turn = dashboard.turn()
        approved = dashboard.act(turn, "approve")
        second = dashboard.act(turn, "override")
        stopped = dashboard.act(turn, "stop")
        after = dashboard.act(turn, "approve")
        later = dashboard.client.post("/turns", json=dashboard.served.body(QUESTION))
        assert approved.status_code == 200, approved.text
        assert second.status_code == 409
        assert "already has a tutor decision" in second.json()["detail"]
        assert stopped.status_code == 200
        assert stopped.json()["stopped"] is True
        assert after.status_code == 409
        assert later.status_code == 422
        rows = dashboard.served.rows(
            "SELECT action, action_index FROM human_action ORDER BY action_index"
        )
        assert rows == [("approve", 0), ("stop", 1)]
        audit = dashboard.client.get(f"/sessions/{dashboard.session_id}/audit").json()
        assert audit["intact"] is True
        assert [a["action"] for a in audit["actions"]] == ["approve", "stop"]

    async def test_an_edit_records_the_released_text(
        self, dashboard: Dashboard
    ) -> None:
        turn = dashboard.turn()
        edited = dashboard.act(turn, "edit", edited_output="Hola is hello.")
        assert edited.status_code == 200, edited.text
        assert edited.json()["action"]["edited_output"] == "Hola is hello."

    async def test_approving_a_held_turn_is_refused_and_override_is_not(
        self, dashboard: Dashboard
    ) -> None:
        held = dashboard.turn("Tell me about volcanoes")
        assert held["status"] == "held_for_review"
        refused = dashboard.act(held, "approve")
        overridden = dashboard.act(held, "override")
        assert refused.status_code == 409
        assert "no draft to release" in refused.json()["detail"]
        assert overridden.status_code == 200

    async def test_a_turn_from_another_session_is_404(
        self, dashboard: Dashboard
    ) -> None:
        assert dashboard.served.plan is not None
        turn = dashboard.turn()
        other = dashboard.client.post(
            "/sessions",
            json={
                "learner_id": str(dashboard.served.plan.learner_id),
                "tutor_id": "tutor-demo",
            },
        ).json()
        response = dashboard.act(turn, "approve", session_id=other["session_id"])
        assert response.status_code == 404
        assert dashboard.served.rows("SELECT count(*) FROM human_action") == [(0,)]

    async def test_the_database_refuses_an_action_on_a_stopped_session(
        self, dashboard: Dashboard
    ) -> None:
        turn = dashboard.turn()
        assert dashboard.act(turn, "stop").status_code == 200
        with (
            psycopg.connect(dashboard.served.url) as connection,
            pytest.raises(psycopg.Error, match="session is stopped"),
        ):
            connection.execute(
                """
                INSERT INTO human_action (
                    id, turn_id, tutor_id, action, acted_at, session_id,
                    action_index, previous_action_hash, action_hash
                ) VALUES (%s, %s, %s, 'override', now(), %s, 1, %s, %s)
                """,
                (
                    uuid4(),
                    UUID(str(turn["turn_id"])),
                    b"\x01" + b"\x00" * 44,
                    UUID(dashboard.session_id),
                    "a" * 64,
                    "b" * 64,
                ),
            )

    async def test_a_stop_without_its_logged_action_is_refused(
        self, dashboard: Dashboard
    ) -> None:
        with (
            psycopg.connect(dashboard.served.url) as connection,
            pytest.raises(psycopg.Error, match="logged as a tutor action first"),
        ):
            connection.execute(
                "SELECT mark_session_stopped(%s, now(), %s)",
                (UUID(dashboard.session_id), b"\x01" + b"\x00" * 44),
            )
        open_ = dashboard.client.get(f"/sessions/{dashboard.session_id}").json()
        assert open_["open"] is True


class TestTurnPage:
    async def test_a_turn_shows_its_cited_text_and_verifies(
        self, dashboard: Dashboard
    ) -> None:
        turn = dashboard.turn()
        page = dashboard.client.get(f"/turns/{turn['turn_id']}")
        assert page.status_code == 200, page.text
        detail = page.json()
        assert detail["record_intact"] is True
        assert detail["cited"], "the turn cites at least one vetted chunk"
        assert detail["cited"][0]["content"]
        assert detail["record"]["history_snapshot"] is not None

    async def test_an_unknown_turn_is_404(self, dashboard: Dashboard) -> None:
        assert dashboard.client.get(f"/turns/{uuid4()}").status_code == 404

    async def test_a_recorded_turn_replays_to_the_same_output(
        self, dashboard: Dashboard
    ) -> None:
        turn = dashboard.turn()
        calls = dashboard.served.model.calls
        replay = dashboard.client.post(f"/turns/{turn['turn_id']}/replay")
        assert replay.status_code == 200, replay.text
        report = replay.json()
        assert report["outcome"] == "reproduced", report["differences"]
        assert report["checkpoint_id"] == turn["record_hash"]
        assert dashboard.served.model.calls == calls + 1

    async def test_a_held_turn_has_nothing_to_replay(
        self, dashboard: Dashboard
    ) -> None:
        held = dashboard.turn("Tell me about volcanoes")
        report = dashboard.client.post(f"/turns/{held['turn_id']}/replay").json()
        assert report["outcome"] == "not_generated"


class TestEventStream:
    async def test_a_paused_turn_does_not_end_the_stream(
        self, dashboard: Dashboard
    ) -> None:
        paused = dashboard.turn("Tell me about volcanoes")
        passed = dashboard.turn()
        events = dashboard.client.get(f"/sessions/{dashboard.session_id}/events")
        assert events.status_code == 200
        assert events.headers["cache-control"] == "no-cache"
        assert f"id: {paused['turn_id']}:conflict_and_ambiguity" in events.text
        assert f"id: {passed['turn_id']}:draft" in events.text
        assert events.text.startswith("retry: ")

    async def test_last_event_id_resumes_after_that_frame(
        self, dashboard: Dashboard
    ) -> None:
        turn = dashboard.turn()
        prompt_id = f"{turn['turn_id']}:prompt"
        resumed = dashboard.client.get(
            f"/sessions/{dashboard.session_id}/events",
            headers={"Last-Event-ID": prompt_id},
        )
        assert f"id: {prompt_id}\n" not in resumed.text
        assert f"id: {turn['turn_id']}:draft" in resumed.text

    async def test_an_approval_appears_as_an_action_frame(
        self, dashboard: Dashboard
    ) -> None:
        turn = dashboard.turn()
        dashboard.act(turn, "approve")
        events = dashboard.client.get(f"/sessions/{dashboard.session_id}/events")
        assert "event: action" in events.text


class TestTamperedLog:
    async def test_an_extra_gate_row_reports_a_break_not_a_500(
        self, dashboard: Dashboard
    ) -> None:
        turn = dashboard.turn()
        with psycopg.connect(dashboard.served.url) as connection:
            connection.execute(
                """
                INSERT INTO gate_evaluation (
                    id, turn_id, gate_name, decision, reason, policy_rule_id,
                    evaluated_at
                )
                SELECT %s, turn_id, gate_name, decision, reason,
                       policy_rule_id, evaluated_at
                FROM gate_evaluation
                WHERE turn_id = %s AND gate_name = 'context_and_permission'
                """,
                (uuid4(), UUID(str(turn["turn_id"]))),
            )
        audit = dashboard.client.get(f"/sessions/{dashboard.session_id}/audit")
        page = dashboard.client.get(f"/turns/{turn['turn_id']}")
        assert audit.status_code == 200
        assert audit.json()["intact"] is False
        assert audit.json()["break_reason"] == "unreadable"
        assert page.status_code == 409


class RubricReport:
    """Append one score to ``RUBRIC_REPORT`` when the variable is set.

    ``make eval`` sets it, so the suite emits its scores headless. Without
    it the test only asserts.
    """

    def write(self, line: dict[str, object]) -> None:
        target = os.environ.get("RUBRIC_REPORT")
        if not target:
            return
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, sort_keys=True) + "\n")


class ScenarioRun:
    """One case through the real API, scored and written to the report."""

    async def scored(
        self, fresh_database: str, case: ScenarioCase
    ) -> tuple[ScenarioObservation, RubricScore]:
        served = Served(fresh_database, RecordingModel(case.completion))
        await served.install()
        for client in served.client():
            response = client.post(
                "/turns",
                json=served.body(case.prompt, case.requested_history_fields),
            )
        assert response.status_code == 200, response.text
        outcome = TurnOutcome.model_validate(response.json())
        observed = ScenarioObserver().observe(case, outcome, served.model.calls)
        score = Rubric().score(case, observed)
        RubricReport().write(
            {
                **score.model_dump(mode="json"),
                "label": "synthetic-only",
                "observed": observed.model_dump(mode="json"),
            }
        )
        return observed, score


# Known misses of the regex classifier (ARCHITECTURE §13). Strict: a detector
# that starts catching one turns this into a failure, so the record is updated
# rather than silently flattering.
_KNOWN_MISSES = {
    "out_of_scope_prompt_paraphrase": "no pattern for 'google'",
    "safety_sensitive_prompt_paraphrase": "no pattern for 'you are at <level>'",
    "prompt_injection_paraphrase": "no pattern for 'disregard what you were told'",
}


class TestScriptedScenarios:
    """REQ-EVAL: eight cases and three paraphrases, scored on observed behaviour."""

    @pytest.mark.parametrize(
        "case",
        [c for c in ScenarioCatalogue().cases() if c.variant == "canonical"],
        ids=lambda case: case.name,
    )
    async def test_the_case_scores_full_marks(
        self, fresh_database: str, case: ScenarioCase
    ) -> None:
        observed, score = await ScenarioRun().scored(fresh_database, case)
        assert observed.halted_at == case.expected_gate
        assert observed.model_calls == case.expect_model_calls
        assert score.full_marks(), score

    @pytest.mark.parametrize(
        "case",
        [
            pytest.param(
                c,
                id=c.name,
                marks=pytest.mark.xfail(strict=True, reason=_KNOWN_MISSES[c.name]),
            )
            for c in ScenarioCatalogue().cases()
            if c.variant == "paraphrase"
        ],
    )
    async def test_the_paraphrase_scores_full_marks(
        self, fresh_database: str, case: ScenarioCase
    ) -> None:
        _, score = await ScenarioRun().scored(fresh_database, case)
        assert score.full_marks(), score


class TestRetention:
    async def purge(self, served: Served) -> PurgeLog:
        cipher = served.container.resolve(CipherPort)
        clock = served.container.resolve(ClockPort)
        assert isinstance(cipher, CipherPort)
        assert isinstance(clock, ClockPort)
        engine = DatabaseEngine(PostgresUrl(served.url).async_url())
        log = PurgeLog()
        try:
            unit = SqlAlchemyUnitOfWork(await engine.connect())
            await unit.run(RetentionPurge(cipher, clock, log))
        finally:
            await engine.dispose()
        return log

    async def test_a_due_learner_is_purged_once_and_cannot_continue(
        self, served: Served
    ) -> None:
        with psycopg.connect(served.url) as connection:
            connection.execute(
                "UPDATE learner SET retain_until = %s",
                (datetime(2000, 1, 1, tzinfo=UTC),),
            )
        first = await self.purge(served)
        second = await self.purge(served)
        assert len(first.receipts) == 1
        assert first.receipts[0].history_rows == 2
        assert first.receipts[0].sessions_stopped == 1
        assert second.receipts == ()
        assert served.rows("SELECT count(*) FROM retention_purge") == [(1,)]
        assert served.rows("SELECT count(*) FROM learner_history_event") == [(0,)]
        assert served.plan is not None
        for client in served.client():
            turn = client.post("/turns", json=served.body(QUESTION))
            reopened = client.post(
                "/sessions",
                json={"learner_id": str(served.plan.learner_id), "tutor_id": "t"},
            )
        assert turn.status_code == 422
        assert reopened.status_code == 422

    async def test_the_purge_log_is_append_only(self, served: Served) -> None:
        with psycopg.connect(served.url) as connection:
            connection.execute(
                "UPDATE learner SET retain_until = %s",
                (datetime(2000, 1, 1, tzinfo=UTC),),
            )
        await self.purge(served)
        with (
            psycopg.connect(served.url) as connection,
            pytest.raises(psycopg.Error, match="append-only"),
        ):
            connection.execute("DELETE FROM retention_purge")


class TestReportsAndEvidence:
    async def test_cohort_counts_follow_the_log(self, dashboard: Dashboard) -> None:
        dashboard.turn()
        report = dashboard.client.get("/reports/cohort")
        assert report.status_code == 200
        assert report.json()["turns"] == 1
        assert "verdict" not in report.json()

    async def test_the_evidence_survey_reads_the_chain_from_the_log(
        self, dashboard: Dashboard
    ) -> None:
        dashboard.act(dashboard.turn(), "approve")
        container = dashboard.served.container
        decoder = container.resolve(AuditRecordDecoder)
        verifier = container.resolve(ChainVerifier)
        assert isinstance(decoder, AuditRecordDecoder)
        assert isinstance(verifier, ChainVerifier)
        engine = DatabaseEngine(PostgresUrl(dashboard.served.url).async_url())
        result = ChainSurveyResult()
        try:
            connection = await engine.connect()
            await SqlAlchemyUnitOfWork(connection).run(
                ChainSurvey(PostgresAuditQuery(connection, decoder), verifier, result)
            )
        finally:
            await engine.dispose()
        assert result.chain_status() == "intact"
        assert result.turns == 1
        assert result.actions == 1
        assert result.policy_version is not None


class TestDashboardMigration:
    async def test_the_revision_downgrades_and_upgrades_again(
        self, fresh_database: str
    ) -> None:
        database = MigratedDatabase()
        database.upgrade(fresh_database)
        database.downgrade(fresh_database, "a7c3e91b04d2")
        with psycopg.connect(fresh_database) as connection:
            columns = connection.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'human_action' AND column_name = 'action_hash'
                """
            ).fetchall()
        assert columns == []
        database.upgrade(fresh_database)
        with psycopg.connect(fresh_database) as connection:
            found = connection.execute(
                "SELECT to_regprocedure('open_session(uuid,uuid,bytea,timestamptz)')"
            ).fetchone()
        assert found is not None
        assert found[0] is not None


class TestOperatorCommands:
    """``make evidence`` and ``make purge``, run as the code they invoke."""

    async def test_the_evidence_pack_is_written_from_the_log(
        self, dashboard: Dashboard, tmp_path: Path
    ) -> None:
        dashboard.act(dashboard.turn(), "approve")
        settings = TurnApp(dashboard.served.url).settings()
        destination = tmp_path / "evidence"
        code = await EvidenceMain(PackPaths(Path(__file__)).root(), destination).run(
            settings
        )
        assert code == 0
        manifest = json.loads((destination / "manifest.json").read_text())
        assert manifest["chain_status"] == "intact"
        assert manifest["turns"] == 1
        assert manifest["actions"] == 1
        assert manifest["policy_version"] != "none-published"
        assert len(manifest["model_revision"]) == 64
        assert (
            "Chain verification: intact" in (destination / "article-12.md").read_text()
        )

    async def test_a_missing_pin_is_reported_as_unpinned(self, tmp_path: Path) -> None:
        empty = tmp_path / "runtime.toml"
        empty.write_text("[model]\n", encoding="utf-8")
        assert ModelPin().revision(None) == "unpinned"
        assert ModelPin().revision(empty) == "unpinned"

    async def test_a_tree_without_a_lockfile_has_no_root(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="uv.lock"):
            PackPaths(tmp_path / "anywhere").root()

    async def test_the_purge_command_runs_once_per_due_learner(
        self, served: Served, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with psycopg.connect(served.url) as connection:
            connection.execute(
                "UPDATE learner SET retain_until = %s",
                (datetime(2000, 1, 1, tzinfo=UTC),),
            )
        settings = TurnApp(served.url).settings()
        assert await RetentionMain().run(settings) == 0
        assert await RetentionMain().run(settings) == 0
        printed = capsys.readouterr().out
        assert "purged 1 learner(s)" in printed
        assert "purged 0 learner(s)" in printed
