"""Wire the harness. Consumers receive the objects this class builds."""

import sys
from typing import TextIO
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict

from tutor_sim.adapters.digest import ArtefactDigest
from tutor_sim.adapters.file_dataset_store import FileDatasetStore
from tutor_sim.adapters.http_source_fetch import CachedOnlySourceFetch, HttpSourceFetch
from tutor_sim.adapters.http_tutor_client import HttpTutorClient
from tutor_sim.adapters.role_model import (
    EchoRoleModel,
    OllamaRoleModel,
    RoleChatLimits,
    RoleModelfile,
    RoleModelPin,
    TomlTable,
    UrllibRoleChat,
)
from tutor_sim.adapters.system_clock import SystemClock
from tutor_sim.application.commands import CampaignCommands
from tutor_sim.application.roles import DiligentTutor
from tutor_sim.catalogue import SourceCatalogue
from tutor_sim.domain.models.source import SourceRecord
from tutor_sim.domain.ports.clock import ClockPort
from tutor_sim.domain.ports.dataset_store import DatasetStorePort
from tutor_sim.domain.ports.role_model import RoleModelPort
from tutor_sim.domain.ports.source_fetch import SourceFetchPort
from tutor_sim.settings import SimulationSettings


class CatalogueHosts:
    """The hosts a fetch may contact. They come from the admitted catalogue."""

    def from_records(self, records: tuple[SourceRecord, ...]) -> frozenset[str]:
        """Every source host and its declared redirect hosts."""
        hosts: set[str] = set()
        for record in records:
            hosts.add(self._host(record.url))
            hosts.update(record.redirect_hosts)
        return frozenset(hosts)

    def _host(self, url: str) -> str:
        host = urlsplit(url).hostname
        if host is None:
            msg = "source URL has no host"
            raise ValueError(msg)
        return host


class RoleUnpinned(Exception):
    """A live command has no role-model pin. Echo is a fixture, not that pin."""


class RoleModelChoice:
    """Echo only when the operator asked for the fixture. Otherwise the pin."""

    def choose(self, settings: SimulationSettings) -> RoleModelPort:
        """The model a command may freeze. A missing pin is a command error."""
        if settings.role_fixture:
            return EchoRoleModel()
        try:
            system = TomlTable(settings.runtime_pin_path, "model").field("weights_sha")
            role = RoleModelPin(settings.runtime_pin_path, system).weights_sha()
        except (OSError, TypeError, ValueError) as exc:
            msg = (
                "a role-model pin is required for a live run; "
                "echo is only available with SIM_ROLE_FIXTURE"
            )
            raise RoleUnpinned(msg) from exc
        return OllamaRoleModel(
            role,
            system,
            UrllibRoleChat(settings.ollama_base_url, RoleModelfile(), RoleChatLimits()),
        )


class WiredHarness(BaseModel):
    """The objects one command run holds."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    clock: ClockPort
    fetch: SourceFetchPort
    store: DatasetStorePort
    commands: CampaignCommands
    client: httpx.Client | None = None

    def close(self) -> None:
        """Release the HTTP client when this run built one."""
        if self.client is not None:
            self.client.close()


class SimulationCompositionRoot:
    """Construct the harness collaborators. This is the only place that does."""

    def __init__(self, settings: SimulationSettings) -> None:
        self._settings = settings

    def wire(self, errors: TextIO | None = None) -> WiredHarness:
        """Build the clock, the fetch, the store, and the commands."""
        stream = sys.stderr if errors is None else errors
        digest = ArtefactDigest()
        catalogue = SourceCatalogue(self._settings.sources_path).load()
        store = FileDatasetStore(self._settings.dataset_dir)
        clock = SystemClock()
        model = RoleModelChoice().choose(self._settings)
        role = DiligentTutor(model, "You are a diligent tutor. Answer with one action.")
        if self._settings.offline:
            commands = CampaignCommands(
                self._settings,
                clock,
                store,
                model,
                tuple(catalogue),
                None,
                role,
                stream,
            )
            return WiredHarness(
                clock=clock,
                fetch=CachedOnlySourceFetch(self._settings.cache_dir, digest),
                store=store,
                commands=commands,
                client=None,
            )
        hosts = CatalogueHosts().from_records(catalogue)
        client = httpx.Client()
        tutor = HttpTutorClient(client, self._settings.api_base_url)
        commands = CampaignCommands(
            self._settings, clock, store, model, tuple(catalogue), tutor, role, stream
        )
        return WiredHarness(
            clock=clock,
            fetch=HttpSourceFetch(client, self._settings.cache_dir, digest, hosts),
            store=store,
            commands=commands,
            client=client,
        )
