"""Write the dataset. Non-redistributable bytes never enter ``public/``."""

from pathlib import Path

from tutor_sim.domain.models.storage import DatasetWrite
from tutor_sim.domain.ports.dataset_store import DatasetStorePort


class NotRedistributable(ValueError):
    """A restricted item was aimed at the public tree."""


class PathEscapesTree(ValueError):
    """The relative path leaves the dataset tree."""


class FileDatasetStore(DatasetStorePort):
    """Two trees under one dataset root."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def write(self, item: DatasetWrite) -> None:
        """Place the file. The redistributable flag decides which refusal applies."""
        if item.tree == "public" and not item.redistributable:
            msg = f"{item.relative_path} is not redistributable"
            raise NotRedistributable(msg)
        destination = (self._root / item.tree / item.relative_path).resolve()
        tree = (self._root / item.tree).resolve()
        if tree != destination and tree not in destination.parents:
            msg = f"{item.relative_path} escapes the dataset tree"
            raise PathEscapesTree(msg)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(item.body)
