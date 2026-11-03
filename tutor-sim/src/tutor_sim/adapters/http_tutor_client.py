"""The tutor API over httpx. Status codes become results."""

import json
from collections.abc import Mapping
from typing import TypeVar
from uuid import UUID

import httpx
from pydantic import BaseModel

from tutor_sim.domain.models.api_views import (
    AuditView,
    HealthView,
    LearnerView,
    RecordedActionView,
    ReplayView,
    SessionView,
    TurnDetailView,
    TurnOutcomeView,
)
from tutor_sim.domain.models.client_call import (
    ActionCall,
    ApiCall,
    AuditCall,
    CallKind,
    DetailCall,
    HealthCall,
    LearnerCall,
    ReplayCall,
    SessionCall,
    TurnCall,
)
from tutor_sim.domain.ports.tutor_client import TutorClientPort

_Call = TypeVar("_Call", bound=ApiCall)
_View = TypeVar("_View", bound=BaseModel)


class StatusKind:
    """Map the four status codes the runner treats as results."""

    def of(self, status: int) -> CallKind:
        """200 is ok. Anything else is a named failure or unexpected."""
        if 200 <= status < 300:
            return "ok"
        if status == 404:
            return "not_found"
        if status == 409:
            return "rejected"
        if status == 422:
            return "session_rejected"
        if status == 503:
            return "errored"
        return "unexpected"


class ResponseText:
    """A short detail string from a problem body or a transport error."""

    def from_body(self, payload: object) -> str:
        """Prefer ``detail`` when the body is an object. Otherwise the text."""
        if isinstance(payload, str):
            return payload
        if isinstance(payload, dict) and isinstance(payload.get("detail"), str):
            return str(payload["detail"])
        return ""


class HttpTutorClient(TutorClientPort):
    """One httpx client. The harness does not import the tutor API."""

    def __init__(self, client: httpx.Client, base_url: str) -> None:
        self._client = client
        self._base = base_url.rstrip("/")
        self._status = StatusKind()
        self._text = ResponseText()

    def health(self) -> HealthCall:
        """``GET /health``."""
        status, kind, payload = self._exchange("GET", "/health", None)
        if kind != "ok" or not isinstance(payload, dict):
            return HealthCall(
                http_status=status, kind=kind, detail=self._text.from_body(payload)
            )
        return HealthCall(
            http_status=status, kind="ok", body=HealthView.model_validate(payload)
        )

    def learners(self) -> LearnerCall:
        """``GET /learners``."""
        status, kind, payload = self._exchange("GET", "/learners", None)
        if kind != "ok" or not isinstance(payload, list):
            return LearnerCall(
                http_status=status, kind=kind, detail=self._text.from_body(payload)
            )
        body = tuple(LearnerView.model_validate(row) for row in payload)
        return LearnerCall(http_status=status, kind="ok", body=body)

    def open_session(self, learner_id: UUID, tutor_id: str) -> SessionCall:
        """``POST /sessions``."""
        sent = {"learner_id": str(learner_id), "tutor_id": tutor_id}
        return self._one(SessionCall, SessionView, "POST", "/sessions", sent)

    def submit(
        self,
        session_id: UUID,
        learner_id: UUID,
        prompt: str,
        fields: tuple[str, ...],
    ) -> TurnCall:
        """``POST /turns``. The prompt is sent unchanged."""
        sent = {
            "session_id": str(session_id),
            "learner_id": str(learner_id),
            "prompt": prompt,
            "requested_history_fields": list(fields),
        }
        return self._one(TurnCall, TurnOutcomeView, "POST", "/turns", sent)

    def detail(self, turn_id: UUID) -> DetailCall:
        """``GET /turns/{id}``."""
        return self._one(DetailCall, TurnDetailView, "GET", f"/turns/{turn_id}", None)

    def act(
        self,
        session_id: UUID,
        turn_id: UUID,
        tutor_id: str,
        action: str,
        edited_output: str | None,
    ) -> ActionCall:
        """``POST .../actions``. 409 comes back as ``rejected``."""
        sent: dict[str, object] = {"tutor_id": tutor_id, "action": action}
        if edited_output is not None:
            sent["edited_output"] = edited_output
        path = f"/sessions/{session_id}/turns/{turn_id}/actions"
        return self._one(ActionCall, RecordedActionView, "POST", path, sent)

    def audit(self, session_id: UUID) -> AuditCall:
        """``GET /sessions/{id}/audit``."""
        return self._one(
            AuditCall, AuditView, "GET", f"/sessions/{session_id}/audit", None
        )

    def replay(self, turn_id: UUID) -> ReplayCall:
        """``POST /turns/{id}/replay``."""
        return self._one(
            ReplayCall, ReplayView, "POST", f"/turns/{turn_id}/replay", None
        )

    def _one(
        self,
        call: type[_Call],
        view: type[_View],
        method: str,
        path: str,
        sent: Mapping[str, object] | None,
    ) -> _Call:
        status, kind, payload = self._exchange(method, path, sent)
        if kind != "ok" or not isinstance(payload, dict):
            return call.model_validate(
                {
                    "http_status": status,
                    "kind": kind,
                    "detail": self._text.from_body(payload),
                }
            )
        return call.model_validate(
            {
                "http_status": status,
                "kind": "ok",
                "body": view.model_validate(payload),
            }
        )

    def _exchange(
        self, method: str, path: str, sent: Mapping[str, object] | None
    ) -> tuple[int, CallKind, object]:
        try:
            response = self._client.request(method, f"{self._base}{path}", json=sent)
        except httpx.HTTPError as exc:
            return (503, "errored", str(exc))
        kind = self._status.of(response.status_code)
        if kind != "ok":
            return (response.status_code, kind, response.text)
        return (response.status_code, kind, self._json(response))

    def _json(self, response: httpx.Response) -> object:
        try:
            return response.json()
        except json.JSONDecodeError:
            return response.text
