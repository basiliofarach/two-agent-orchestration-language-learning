"""Write the dataset tree. A non-redistributable item stays out of public/."""

from abc import ABC, abstractmethod

from tutor_sim.domain.models.storage import DatasetWrite


class DatasetStorePort(ABC):
    """Place one file in the public or the restricted tree."""

    @abstractmethod
    def write(self, item: DatasetWrite) -> None:
        """Write the file. Refuse a non-redistributable item under public/."""
        raise NotImplementedError  # pragma: no cover
