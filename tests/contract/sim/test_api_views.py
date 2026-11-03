"""The harness views match the fields the API publishes."""

from collections.abc import Mapping

from fastapi.testclient import TestClient
from pydantic import BaseModel
from tests.integration.test_health_router import ConfiguredSettingsProvider

from tutor_api.di.container import Container
from tutor_api.main import Application
from tutor_sim.adapters.http_tutor_client import HttpTutorClient
from tutor_sim.domain.models.api_views import (
    AuditView,
    GateRowView,
    HealthView,
    LearnerView,
    RecordedActionView,
    RecordView,
    ReplayView,
    SessionView,
    TurnDetailView,
    TurnOutcomeView,
)


class SchemaProperties:
    """Every property the OpenAPI document declares, by name."""

    def collect(
        self, document: Mapping[str, object]
    ) -> dict[str, Mapping[str, object]]:
        """Walk the document. The first schema for a name is kept."""
        found: dict[str, Mapping[str, object]] = {}
        self._walk(document, found)
        return found

    def _walk(self, node: object, found: dict[str, Mapping[str, object]]) -> None:
        if isinstance(node, dict):
            props = node.get("properties")
            if isinstance(props, dict):
                for name, schema in props.items():
                    if isinstance(name, str) and isinstance(schema, dict):
                        found.setdefault(name, schema)
            for value in node.values():
                self._walk(value, found)
        elif isinstance(node, list):
            for item in node:
                self._walk(item, found)


class TestApiViews:
    def test_health_over_asgi_reports_the_mode_and_the_fields_exist(self) -> None:
        container = Container((ConfiguredSettingsProvider(),))
        container.validate()
        app = Application(container).asgi()
        with TestClient(app) as client:
            health = HttpTutorClient(client, "http://testserver").health()
        assert health.kind == "ok"
        assert health.body is not None
        assert health.body.mode == "prototype"
        published = SchemaProperties().collect(app.openapi())
        views: tuple[type[BaseModel], ...] = (
            HealthView,
            LearnerView,
            SessionView,
            GateRowView,
            TurnOutcomeView,
            RecordView,
            TurnDetailView,
            ReplayView,
            AuditView,
            RecordedActionView,
        )
        for view in views:
            for name in view.model_fields:
                schema = published[name]
                assert (
                    "type" in schema
                    or "anyOf" in schema
                    or "$ref" in schema
                    or "enum" in schema
                )
