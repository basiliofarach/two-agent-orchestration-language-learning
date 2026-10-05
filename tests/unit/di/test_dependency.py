"""``Provide`` resolves from one request scope per HTTP request (DEC-0014)."""

from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from tests.unit.di.test_lifetime_validation import StubProvider

from tutor_api.di.container import Container
from tutor_api.di.dependency import Provide
from tutor_api.di.lifetime import Lifetime


class Connection:
    """Stands in for the request's enlisted connection."""


class SeenPairs:
    """An app whose route records the two objects it was handed."""

    def __init__(self) -> None:
        self.pairs: list[tuple[Connection, Connection]] = []

    def app(self) -> FastAPI:
        app = FastAPI()
        app.state.container = Container((StubProvider(Connection, Lifetime.REQUEST),))
        seen = self.pairs

        @app.get("/pair")
        def pair(
            one: Annotated[Connection, Depends(Provide(Connection))],
            two: Annotated[Connection, Depends(Provide(Connection))],
        ) -> None:
            seen.append((one, two))

        return app


class TestProvide:
    def test_one_request_resolves_one_request_object(self) -> None:
        recorder = SeenPairs()
        TestClient(recorder.app()).get("/pair")
        one, two = recorder.pairs[0]
        assert one is two

    def test_two_requests_resolve_two_request_objects(self) -> None:
        recorder = SeenPairs()
        client = TestClient(recorder.app())
        client.get("/pair")
        client.get("/pair")
        assert recorder.pairs[0][0] is not recorder.pairs[1][0]
