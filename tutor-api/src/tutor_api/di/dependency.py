"""The seam between the container and a FastAPI route signature."""

from typing import cast

from fastapi import Request


class Provide[TDependency]:
    """A ``Depends()`` callable that resolves one type from the application.

    The container is read from ``request.app.state``, which is per-application
    instance state rather than a module-level global: several applications
    exist in one process during the test run and share nothing. Resolution
    goes through one ``RequestScope`` per request.

    This is the one place resolution happens by type rather than by
    constructor. Rule 3 confines that to the router signature, and it stops
    there — what a handler receives it was handed, and everything the handler
    passes further down is constructor-injected (DEC-0013).
    """

    def __init__(self, requested: type[TDependency]) -> None:
        self._requested = requested

    def __call__(self, request: Request) -> TDependency:
        """Resolve the requested type from this request's scope.

        The scope is opened on the first dependency a request resolves and
        kept on ``request.state``, which is per request. FastAPI resolves one
        request's dependencies in sequence, so two calls here never race to
        open it. Every dependency of one request then shares its
        request-scoped objects, the connection among them (DEC-0014).
        """
        scope = getattr(request.state, "scope", None)
        if scope is None:
            scope = request.app.state.container.scope()
            request.state.scope = scope
        return cast(TDependency, scope.resolve(self._requested))
