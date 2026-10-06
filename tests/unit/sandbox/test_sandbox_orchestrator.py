"""The sandbox runner never points a command at the operator database."""

import runpy
import sys
from pathlib import Path

import pytest
from tests.support.repository import RepositoryPaths
from tests.support.runtime_pin import RuntimePin

from tutor_api.adapters.persistence.schema import (
    ApplicationRole,
    AuditSchema,
    BaseSchema,
    InstantColumn,
)
from tutor_api.adapters.persistence.versioned_policy import EffectiveInstant
from tutor_api.sandbox.__main__ import SandboxModule
from tutor_api.sandbox.commands import (
    ProcessEnvironment,
    SandboxCommands,
    SandboxEnvironment,
    SandboxPaths,
)
from tutor_api.sandbox.identity import SandboxIdentity
from tutor_api.sandbox.orchestrator import ProcessLaunch, SandboxOrchestrator
from tutor_core.domain.models.audit import GateEvaluation, HumanAction, TurnAuditRecord
from tutor_core.domain.models.learner import HistoryItem
from tutor_core.domain.models.timestamps import Timestamped


class ScriptedLaunch(ProcessLaunch):
    """Records argv and returns a status keyed by a token in the command."""

    def __init__(self, codes: dict[str, int] | None = None) -> None:
        self.commands: list[tuple[str, ...]] = []
        self.directories: list[Path] = []
        self.environments: list[dict[str, str]] = []
        self._codes = {} if codes is None else codes

    def run(
        self,
        command: tuple[str, ...],
        env: dict[str, str],
        cwd: Path,
    ) -> int:
        self.commands.append(command)
        self.directories.append(cwd)
        self.environments.append(env)
        for token, code in self._codes.items():
            if token in command:
                return code
        return 0


class Wired:
    """One orchestrator over a scripted launch and the real paths."""

    def __init__(self, codes: dict[str, int] | None = None) -> None:
        self.launch = ScriptedLaunch(codes)
        self.identity = SandboxIdentity()
        self.paths = SandboxPaths.from_here()
        self.base = {"POSTGRES_PORT": "5433", "DATABASE_URL": "postgresql://operator"}
        self.orchestrator = SandboxOrchestrator(
            self.launch,
            SandboxCommands(self.identity, self.paths, sys.executable),
            SandboxEnvironment(self.identity, self.base),
            self.paths,
        )


class TestSandboxIdentity:
    def test_the_default_identity_is_not_the_operator_database(self) -> None:
        identity = SandboxIdentity()
        assert identity.separated_from_the_operator()
        assert ":55433/" in identity.maintenance_url()
        assert identity.alembic_url().startswith("postgresql+psycopg://")
        assert identity.application_url().startswith("postgresql+asyncpg://")

    def test_an_identity_that_reuses_the_operator_is_refused(self) -> None:
        assert not SandboxIdentity(project="tutor").separated_from_the_operator()
        assert not SandboxIdentity(volume="postgres-data").separated_from_the_operator()
        assert not SandboxIdentity(host="0.0.0.0").separated_from_the_operator()
        assert not SandboxIdentity(port=5433).separated_from_the_operator()
        assert not SandboxIdentity(port=5432).separated_from_the_operator()

    def test_the_compose_file_spells_the_identity_and_not_the_operator(self) -> None:
        identity = SandboxIdentity()
        text = SandboxPaths.from_here().compose_file().read_text(encoding="utf-8")
        for marker in identity.required_in_compose():
            assert marker in text
        for marker in identity.forbidden_in_compose():
            assert marker not in text
        assert RuntimePin().postgres_image() in text
        assert "127.0.0.1:55433:5432" in text


class TestSandboxRun:
    def test_teardown_is_armed_before_migrate_and_pytest(self) -> None:
        wired = Wired()
        assert wired.orchestrator.run() == 0
        tokens = [" ".join(command) for command in wired.launch.commands]
        assert any(" up " in token for token in tokens)
        assert any("alembic" in token for token in tokens)
        suite = next(token for token in tokens if "pytest" in token)
        assert "not sandbox_lifecycle" in suite
        assert tokens[-1].endswith("down -v --remove-orphans")
        started = next(token for token in tokens if " up " in token)
        migrated = next(token for token in tokens if "alembic" in token)
        assert tokens.index(started) < tokens.index(migrated)

    def test_a_failed_migrate_still_removes_the_sandbox(self) -> None:
        wired = Wired({"alembic": 2})
        assert wired.orchestrator.run() == 2
        joined = [" ".join(command) for command in wired.launch.commands]
        assert not any("pytest" in token for token in joined)
        assert "down -v" in joined[-1]

    def test_a_failed_start_still_removes_the_sandbox(self) -> None:
        wired = Wired({"up": 3})
        assert wired.orchestrator.run() == 3
        joined = [" ".join(command) for command in wired.launch.commands]
        assert not any("alembic" in token for token in joined)
        assert "down -v" in joined[-1]

    def test_a_failing_check_is_the_status_and_the_volume_is_removed(self) -> None:
        wired = Wired({"-c": 1})
        code = wired.orchestrator.run((sys.executable, "-c", "import sys; sys.exit(1)"))
        assert code == 1
        assert wired.launch.commands[2][1] == "-c"
        assert "down -v" in " ".join(wired.launch.commands[-1])

    def test_a_failed_teardown_fails_a_run_whose_checks_passed(self) -> None:
        wired = Wired({"down": 9})
        assert wired.orchestrator.run() == 9

    def test_commands_run_in_the_api_tree_and_pytest_in_the_repository(self) -> None:
        wired = Wired()
        wired.orchestrator.run()
        api = wired.paths.api_root()
        repo = wired.paths.repo_root()
        assert wired.launch.directories == [api, api, repo, api]

    def test_the_environment_replaces_the_operator_database(self) -> None:
        wired = Wired()
        wired.orchestrator.run()
        env = wired.launch.environments[0]
        assert env["COMPOSE_DISABLE_ENV_FILE"] == "1"
        assert env["POSTGRES_PORT"] == "55433"
        assert env["POSTGRES_USER"] == "sandbox_owner"
        assert env["POSTGRES_APP_USER"] == "sandbox_app"
        assert env["TUTOR_SANDBOX_URL"] == wired.identity.maintenance_url()
        assert env["DATABASE_URL"] == wired.identity.alembic_url()
        assert env["DATABASE_URL"].endswith(":55433/sandbox")
        assert ":5433/" not in env["DATABASE_URL"]
        assert env["APPLICATION_DATABASE_URL"] == wired.identity.application_url()

    def test_a_substituted_check_replaces_pytest(self) -> None:
        commands = SandboxCommands(
            SandboxIdentity(),
            SandboxPaths.from_here(),
            "python",
        )
        assert commands.check(("echo", "ok")) == ("echo", "ok")
        assert "not sandbox_lifecycle" in commands.check(None)

    def test_already_inside_reads_the_sandbox_variable(self) -> None:
        identity = SandboxIdentity()
        assert not SandboxEnvironment(identity, {}).already_inside()
        assert SandboxEnvironment(identity, {"TUTOR_SANDBOX_URL": "x"}).already_inside()

    def test_process_environment_is_a_copy(self) -> None:
        values = ProcessEnvironment().values()
        values["TUTOR_SANDBOX_URL"] = "changed"
        again = ProcessEnvironment().values().get("TUTOR_SANDBOX_URL", "")
        assert "changed" not in again

    def test_paths_resolve_to_this_checkout(self) -> None:
        paths = SandboxPaths.from_here()
        assert paths.api_root() == RepositoryPaths().root() / "tutor-api"
        assert paths.compose_file().is_file()

    def test_main_returns_the_launch_status(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def succeed(
            self: ProcessLaunch,
            command: tuple[str, ...],
            env: dict[str, str],
            cwd: Path,
        ) -> int:
            return 0

        monkeypatch.setattr(ProcessLaunch, "run", succeed)
        assert SandboxOrchestrator.main() == 0

    def test_the_module_entry_exits_with_that_status(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(SandboxOrchestrator, "main", classmethod(lambda cls: 4))
        with pytest.raises(SystemExit) as caught:
            SandboxModule.main()
        assert caught.value.code == 4

    def test_python_m_runs_the_module_entry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            SandboxOrchestrator,
            "main",
            classmethod(lambda cls: 0),
        )
        sys.modules.pop("tutor_api.sandbox.__main__", None)
        with pytest.raises(SystemExit) as caught:
            runpy.run_module("tutor_api.sandbox", run_name="__main__")
        assert caught.value.code == 0

    def test_a_real_process_returns_its_status(self) -> None:
        launch = ProcessLaunch()
        code = launch.run(
            (sys.executable, "-c", "import sys; sys.exit(5)"),
            {},
            Path("."),
        )
        assert code == 5


class TestInstantColumn:
    def test_a_name_that_is_not_an_identifier_is_refused(self) -> None:
        with pytest.raises(ValueError, match="lowercase identifier"):
            InstantColumn("Recorded-At")

    def test_base_tables_use_full_precision_timestamptz(self) -> None:
        sql = "\n".join(BaseSchema().statements())
        assert InstantColumn("occurred_at").required() in sql
        assert InstantColumn("reviewed_at").optional() in sql
        assert "timestamp without time zone" not in sql
        assert "timestamptz(" not in sql

    def test_audit_tables_keep_full_precision_timestamptz(self) -> None:
        sql = "\n".join(AuditSchema(ApplicationRole("tutor_app")).statements())
        assert "recorded_at timestamptz NOT NULL" in sql
        assert "timestamptz(" not in sql
        assert "timestamp without time zone" not in sql


class TestTimestampedRecords:
    def test_instant_bearing_records_inherit_the_base(self) -> None:
        assert issubclass(HistoryItem, Timestamped)
        assert issubclass(GateEvaluation, Timestamped)
        assert issubclass(HumanAction, Timestamped)
        assert issubclass(TurnAuditRecord, Timestamped)
        assert issubclass(EffectiveInstant, Timestamped)
        assert HistoryItem.model_config.get("frozen") is True
        assert HistoryItem.model_config.get("extra") == "forbid"
