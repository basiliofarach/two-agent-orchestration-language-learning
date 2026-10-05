"""``uv run tutor-api`` serves the composed app on the configured address."""

import pytest

from tutor_api import serve
from tutor_api.serve import ApiServer
from tutor_api.settings import ApplicationSettings


class RecordingRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def __call__(self, *args: object, **kwargs: object) -> None:
        self.calls.append((args, kwargs))


class TestApiServer:
    def test_serves_the_composed_app_on_the_configured_address(self) -> None:
        runner = RecordingRunner()
        settings = ApplicationSettings(
            _env_file=None,  # type: ignore[call-arg]
            api_host="0.0.0.0",  # noqa: S104
            api_port=9001,
        )
        ApiServer(settings, runner).run()
        assert runner.calls == [
            (("tutor_api.main:app",), {"host": "0.0.0.0", "port": 9001})  # noqa: S104
        ]

    def test_the_script_entry_defaults_to_loopback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        runner = RecordingRunner()
        monkeypatch.setattr(serve.uvicorn, "run", runner)
        monkeypatch.chdir("/")
        ApiServer.main()
        assert runner.calls == [
            (("tutor_api.main:app",), {"host": "127.0.0.1", "port": 8000})
        ]
