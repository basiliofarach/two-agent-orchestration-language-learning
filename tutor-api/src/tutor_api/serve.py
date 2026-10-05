"""``uv run tutor-api``: serve the API. The project script points here."""

from collections.abc import Callable

import uvicorn

from tutor_api.settings import ApplicationSettings


class ApiServer:
    """Start the ASGI server on the configured host and port.

    The server imports ``tutor_api.main:app`` itself, so the object graph is
    built once, in the server's process, by the composition root.
    """

    def __init__(
        self,
        settings: ApplicationSettings,
        runner: Callable[..., None],
    ) -> None:
        self._settings = settings
        self._runner = runner

    @classmethod
    def main(cls) -> None:
        """The console-script entry: read settings and serve."""
        cls(ApplicationSettings(), uvicorn.run).run()

    def run(self) -> None:
        """Serve until interrupted."""
        self._runner(
            "tutor_api.main:app",
            host=self._settings.api_host,
            port=self._settings.api_port,
        )
