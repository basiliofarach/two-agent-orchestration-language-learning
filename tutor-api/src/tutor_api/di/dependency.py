"""The seam between the container and a FastAPI route signature."""

from fastapi import Request


class Provide:
    """A ``Depends()`` callable that resolves one type from the application.

    The container is read from ``request.app.state``, which is per-application
    instance state rather than a module-level global: several applications
    exist in one process during the test run and share nothing.

    This is the one place resolution happens by type rather than by
    constructor. Rule 3 confines that to the router signature, and it stops
    there — what a handler receives it was handed, and everything the handler
    passes further down is constructor-injected (DEC-0013).
    """

    def __init__(self, requested: type) -> None:
        self._requested = requested

    def __call__(self, request: Request) -> object:
        """Resolve the requested type from the running application's graph."""
        return request.app.state.container.resolve(self._requested)
