"""Write the persona cards ``build`` would write, for tests that skip build."""

from pathlib import Path

from tutor_sim.application.personas import ErrorProfileLoader, PersonaCardBuilder


class PersonaFiles:
    """The sixteen built cards under ``<dataset>/public/personas/``."""

    def write(self, dataset_dir: Path) -> None:
        directory = dataset_dir / "public" / "personas"
        directory.mkdir(parents=True, exist_ok=True)
        for card in PersonaCardBuilder(ErrorProfileLoader()).cards():
            (directory / f"{card.persona_id}.json").write_text(
                card.model_dump_json(indent=2) + "\n", encoding="utf-8"
            )
