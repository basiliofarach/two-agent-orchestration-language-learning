"""``python -m tutor_sim``. The composition root builds every collaborator."""

import sys

from tutor_sim.cli import SimulationCli
from tutor_sim.composition import SimulationCompositionRoot
from tutor_sim.settings import SimulationSettings


class ModuleMain:
    """The process entry. Tests call this with the process arguments."""

    def __call__(self) -> int:
        settings = SimulationSettings()
        root = SimulationCompositionRoot(settings)
        return SimulationCli(root, sys.stderr).main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(ModuleMain()())  # pragma: no cover
