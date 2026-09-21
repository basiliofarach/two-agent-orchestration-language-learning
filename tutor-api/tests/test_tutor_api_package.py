"""Package import and version for tutor-api."""

from __future__ import annotations

import tutor_api
import tutor_api.adapters
import tutor_api.adapters.checks
import tutor_api.adapters.llm
import tutor_api.adapters.persistence
import tutor_api.retention
import tutor_api.routers


class TestTutorApiPackage:
    def test_version_is_exposed(self) -> None:
        assert tutor_api.__version__ == "0.1.0"

    def test_skeleton_packages_import(self) -> None:
        assert tutor_api.adapters.persistence.__doc__ is not None
        assert tutor_api.routers.__doc__ is not None
