"""Isolate the suite from whatever configuration the developer has exported.

``BaseSettings`` reads ``os.environ`` ahead of any ``_env_file``, so a shell
with ``POSTGRES_*`` set silently overrides what a test states: the same commit
passes on one machine and fails on another, and it fails in a way that points
at the assertion rather than at the environment.

Clearing these makes every test state its own configuration. A test that wants
an environment variable sets it with ``monkeypatch`` — that still works,
because this fixture and the test share the same ``monkeypatch`` instance and
this one runs first.
"""

import pytest

# Everything ApplicationSettings declares, plus the URL that overrides them.
_SETTINGS_ENVIRONMENT = (
    "DATABASE_URL",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_APP_USER",
    "POSTGRES_APP_PASSWORD",
)


@pytest.fixture(autouse=True)
def isolate_settings_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove ambient configuration before every test."""
    for name in _SETTINGS_ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)
