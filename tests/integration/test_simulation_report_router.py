"""``GET /reports/simulation`` over the real container and a run directory."""

from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from tests.unit.test_container import FixedSettings

from tutor_api.container import ApplicationContainer
from tutor_api.di.container import Container
from tutor_api.di.lifetime import Lifetime
from tutor_api.di.provider import Provider
from tutor_api.main import Application
from tutor_api.settings import ApplicationSettings
from tutor_core.application.services.read_simulation_reports import (
    ExecuteSimulationReports,
    SimulationQuery,
    SimulationRead,
)
from tutor_core.application.services.service import ExecuteHandler
from tutor_sim.application.run_files import RunDirectory
from tutor_sim.domain.models.report import SimulationReport

_RUN = "run-20261104T120000"


class EmptyRead(ExecuteHandler[SimulationQuery, SimulationRead]):
    """An execute stage that reads nothing, whatever it was asked."""

    async def run(self, prepared: SimulationQuery) -> SimulationRead:
        return SimulationRead()


class EmptyReadProvider(Provider):
    def provides(self) -> type:
        return ExecuteSimulationReports

    def lifetime(self) -> Lifetime:
        return Lifetime.SINGLETON

    def requires(self) -> tuple[type, ...]:
        return ()

    def create(self, resolved: Mapping[type, object]) -> object:
        return EmptyRead()


class ReportApp:
    def __init__(self, root: Path) -> None:
        self._settings = ApplicationSettings(
            _env_file=None,  # type: ignore[call-arg]
            simulation_reports_dir=root,
        )

    def providers(self) -> tuple[Provider, ...]:
        return ApplicationContainer(FixedSettings(self._settings)).providers()

    def client(self, providers: tuple[Provider, ...]) -> Iterator[TestClient]:
        container = Container(providers)
        container.validate()
        with TestClient(Application(container).asgi()) as client:
            yield client


@pytest.fixture
def written(tmp_path: Path) -> Path:
    report = SimulationReport(
        run_id=_RUN,
        dataset_version="sim-dataset/0.1.0",
        label="simulated:sim-dataset/0.1.0",
        licence_status="pending",
        pending_sources=("grammar-profile",),
        finished=True,
    )
    RunDirectory(tmp_path).write(report, "1", datetime(2026, 11, 4, 12, tzinfo=UTC))
    return tmp_path / "runs"


class TestSimulationReportRouter:
    def test_the_run_tutor_sim_wrote_is_listed_and_served(self, written: Path) -> None:
        app = ReportApp(written)
        for client in app.client(app.providers()):
            listed = client.get("/reports/simulation")
            one = client.get(f"/reports/simulation/{_RUN}")
            missing = client.get("/reports/simulation/run-absent")
        assert listed.status_code == 200
        assert [run["run_id"] for run in listed.json()] == [_RUN]
        assert one.status_code == 200
        assert one.json()["pending_sources"] == ["grammar-profile"]
        assert missing.status_code == 404

    def test_a_report_filed_under_another_run_is_409(self, written: Path) -> None:
        moved = written / "run-other"
        (written / _RUN).rename(moved)
        app = ReportApp(written)
        for client in app.client(app.providers()):
            response = client.get("/reports/simulation/run-other")
        assert response.status_code == 409

    def test_an_execute_stage_that_read_nothing_is_not_served(
        self, written: Path
    ) -> None:
        app = ReportApp(written)
        providers = tuple(
            provider
            for provider in app.providers()
            if provider.provides() is not ExecuteSimulationReports
        )
        for client in app.client((*providers, EmptyReadProvider())):
            response = client.get(f"/reports/simulation/{_RUN}")
        assert response.status_code == 404
        assert response.json()["detail"] == "the simulation report was not read"
