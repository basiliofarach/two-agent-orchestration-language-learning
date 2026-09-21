"""Package import and version for tutor-core."""

from __future__ import annotations

import tutor_core
import tutor_core.application
import tutor_core.application.agents
import tutor_core.application.services
import tutor_core.application.turn
import tutor_core.domain
import tutor_core.domain.gates
import tutor_core.domain.models
import tutor_core.domain.policy
import tutor_core.domain.ports


class TestTutorCorePackage:
    def test_version_is_exposed(self) -> None:
        assert tutor_core.__version__ == "0.1.0"

    def test_skeleton_packages_import(self) -> None:
        assert tutor_core.domain.models.__doc__ is not None
        assert tutor_core.application.services.__doc__ is not None
