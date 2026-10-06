"""``python -m tutor_api.sandbox`` from ``tutor-api/``."""

from tutor_api.sandbox.orchestrator import SandboxOrchestrator


class SandboxModule:
    """The module entry. Behaviour stays on the orchestrator."""

    @staticmethod
    def main() -> None:
        """Exit with the sandbox run's status."""
        raise SystemExit(SandboxOrchestrator.main())


if __name__ == "__main__":
    SandboxModule.main()
