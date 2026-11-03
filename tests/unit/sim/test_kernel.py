"""DEC-0011 and the harness clock, settings, and command entry."""

import inspect
import io
import sys
import typing
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tutor_sim.adapters.frozen_clock import FrozenClock
from tutor_sim.adapters.system_clock import SystemClock
from tutor_sim.application.service import (
    ApplicationService,
    Executed,
    ExecuteHandler,
    FinaliseHandler,
    Prepared,
    PrepareHandler,
)
from tutor_sim.cli import SimulationCli
from tutor_sim.composition import CatalogueHosts, SimulationCompositionRoot
from tutor_sim.domain.models.identity import SimulationNamespace
from tutor_sim.domain.models.source import SourceRecord
from tutor_sim.domain.ports.clock import ClockPort
from tutor_sim.settings import SimulationSettings


class Calls:
    def __init__(self) -> None:
        self.order: list[str] = []


class SpyPrepare(PrepareHandler[str, str]):
    def __init__(self, calls: Calls) -> None:
        self._calls = calls

    def run(self, command: str) -> str:
        self._calls.order.append("prepare")
        return command + ":prepared"


class SpyExecute(ExecuteHandler[str, str]):
    def __init__(self, calls: Calls) -> None:
        self._calls = calls

    async def run(self, prepared: str) -> str:
        self._calls.order.append("execute")
        return prepared + ":executed"


class SpyFinalise(FinaliseHandler[str, int]):
    def __init__(self, calls: Calls) -> None:
        self._calls = calls

    def run(self, executed: str) -> int:
        self._calls.order.append("finalise")
        return len(executed)


class Public:
    def methods(self, holder: type) -> set[str]:
        return {
            name
            for name, _ in inspect.getmembers(holder, inspect.isfunction)
            if not name.startswith("_")
        }


class PinnedSource:
    def record(self, url: str = "https://example.invalid/pin") -> SourceRecord:
        return SourceRecord(
            source_id="ellipse",
            title="Grammar notes",
            url=url,
            revision="2026-11-03",
            sha256="ab" * 32,
            licence="custom:author-own",
            licence_url=url,
            redistributable=True,
            use="kb",
            attribution="The author.",
        )


class OfflineSettings:
    def build(self, tmp_path: Path, offline: bool) -> SimulationSettings:
        catalogue = tmp_path / "sources.json"
        catalogue.write_text(
            "[" + PinnedSource().record().model_dump_json() + "]",
            encoding="utf-8",
        )
        return SimulationSettings(
            dataset_dir=tmp_path / "dataset",
            cache_dir=tmp_path / "cache",
            sources_path=catalogue,
            offline=offline,
            evidence_dir=tmp_path / "evidence",
            runtime_pin_path=tmp_path / "runtime.toml",
        )


class TestTypestateChain:
    def test_each_holder_exposes_exactly_one_method(self) -> None:
        assert Public().methods(ApplicationService) == {"prepare"}
        assert Public().methods(Prepared) == {"execute"}
        assert Public().methods(Executed) == {"finalise"}

    def test_execute_returns_executed_never_the_result(self) -> None:
        hints = typing.get_type_hints(Prepared.execute)
        assert typing.get_origin(hints["return"]) is Executed

    async def test_the_stages_run_in_order_and_only_finalise_yields(self) -> None:
        calls = Calls()
        service = ApplicationService(
            SpyPrepare(calls), SpyExecute(calls), SpyFinalise(calls)
        )
        prepared = service.prepare("turn")
        assert calls.order == ["prepare"]
        executed = await prepared.execute()
        assert calls.order == ["prepare", "execute"]
        assert isinstance(executed, Executed)
        assert executed.finalise() == len("turn:prepared:executed")
        assert calls.order == ["prepare", "execute", "finalise"]

    @pytest.mark.parametrize(
        "handler", [PrepareHandler, ExecuteHandler, FinaliseHandler]
    )
    def test_a_handler_without_run_cannot_be_instantiated(self, handler: type) -> None:
        incomplete = type("Incomplete", (handler,), {})
        with pytest.raises(TypeError, match="abstract"):
            incomplete()


class TestClocks:
    def test_the_system_clock_is_timezone_aware(self) -> None:
        instant = SystemClock().now()
        assert isinstance(instant, datetime)
        assert instant.utcoffset() is not None

    def test_the_frozen_clock_returns_the_injected_instant(self) -> None:
        instant = datetime(2026, 11, 3, tzinfo=UTC)
        assert FrozenClock(instant).now() == instant

    def test_a_clock_port_without_now_cannot_be_instantiated(self) -> None:
        incomplete = type("Incomplete", (ClockPort,), {})
        with pytest.raises(TypeError, match="abstract"):
            incomplete()


class TestSimulationNamespace:
    def test_ids_are_stable(self) -> None:
        namespace = SimulationNamespace()
        assert namespace.document_id("clear-corpus", "item") == namespace.document_id(
            "clear-corpus", "item"
        )
        assert namespace.learner_id("p-a1-es-12_14-01") == namespace.learner_id(
            "p-a1-es-12_14-01"
        )
        assert namespace.document_id("clear-corpus", "item") != namespace.learner_id(
            "clear-corpus"
        )


class TestSettings:
    def test_the_default_role_model_url_is_loopback(self) -> None:
        assert SimulationSettings(_env_file=None).ollama_base_url == (
            "http://127.0.0.1:11434"
        )

    @pytest.mark.parametrize(
        "url",
        [
            "http://localhost:11434",
            "http://127.0.0.2:11434",
            "http://[::1]:11434/",
        ],
    )
    def test_loopback_names_are_accepted(self, url: str) -> None:
        settings = SimulationSettings(ollama_base_url=url)
        assert settings.ollama_base_url.rstrip("/") == url.rstrip("/")

    @pytest.mark.parametrize(
        ("url", "message"),
        [
            ("http://example.com:11434", "local machine"),
            ("http://user:secret@127.0.0.1:11434", "credentials"),
            ("ftp://127.0.0.1:11434", "http"),
            ("http://", "http"),
        ],
    )
    def test_a_hosted_or_credentialed_url_is_refused(
        self, url: str, message: str
    ) -> None:
        with pytest.raises(ValueError, match=message):
            SimulationSettings(ollama_base_url=url)


class TestComposition:
    def test_offline_uses_the_cache_and_opens_no_client(self, tmp_path: Path) -> None:
        from tutor_sim.adapters.http_source_fetch import CachedOnlySourceFetch

        wired = SimulationCompositionRoot(
            OfflineSettings().build(tmp_path, offline=True)
        ).wire()
        assert isinstance(wired.fetch, CachedOnlySourceFetch)
        assert wired.clock.now().utcoffset() is not None
        wired.close()

    def test_online_opens_a_client_limited_to_catalogue_hosts(
        self, tmp_path: Path
    ) -> None:
        from tutor_sim.adapters.http_source_fetch import HttpSourceFetch

        wired = SimulationCompositionRoot(
            OfflineSettings().build(tmp_path, offline=False)
        ).wire()
        try:
            assert isinstance(wired.fetch, HttpSourceFetch)
        finally:
            wired.close()

    def test_declared_redirect_hosts_join_the_allowlist(self) -> None:
        record = PinnedSource().record("https://huggingface.co/datasets/x")
        redirected = SourceRecord.model_validate(
            {**record.model_dump(), "redirect_hosts": ["cdn-lfs.hf.co"]}
        )
        assert CatalogueHosts().from_records((redirected,)) == frozenset(
            {"huggingface.co", "cdn-lfs.hf.co"}
        )
        assert record.redirect_hosts == ()

    @pytest.mark.parametrize(
        "host", ["https://cdn-lfs.hf.co", "cdn-lfs.hf.co/path", "", "CDN.hf.co"]
    )
    def test_a_redirect_host_is_a_bare_lowercase_hostname(self, host: str) -> None:
        record = PinnedSource().record()
        with pytest.raises(ValueError, match="redirect_hosts"):
            SourceRecord.model_validate(
                {**record.model_dump(), "redirect_hosts": [host]}
            )

    def test_a_source_url_without_a_host_is_refused(self) -> None:
        with pytest.raises(ValueError, match="no host"):
            CatalogueHosts().from_records((PinnedSource().record("not-a-url"),))


class TestCli:
    def test_an_empty_command_is_a_usage_error(self, tmp_path: Path) -> None:
        root = SimulationCompositionRoot(OfflineSettings().build(tmp_path, True))
        assert SimulationCli(root, io.StringIO()).main([]) == 2

    def test_an_unknown_command_is_a_usage_error(self, tmp_path: Path) -> None:
        root = SimulationCompositionRoot(OfflineSettings().build(tmp_path, True))
        assert SimulationCli(root, io.StringIO()).main(["publish"]) == 2

    @pytest.mark.parametrize("command", ["build"])
    def test_an_unimplemented_command_wires_the_harness_and_fails(
        self, tmp_path: Path, command: str
    ) -> None:
        root = SimulationCompositionRoot(OfflineSettings().build(tmp_path, True))
        errors = io.StringIO()
        assert SimulationCli(root, errors).main([command]) == 1
        assert f"{command} is not implemented" in errors.getvalue()


class TestModuleMain:
    def test_build_uses_the_process_arguments(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from tutor_sim.__main__ import ModuleMain

        monkeypatch.setattr(sys, "argv", ["tutor_sim", "nope"])
        assert ModuleMain()() == 2
