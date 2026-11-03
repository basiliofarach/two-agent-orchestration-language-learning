"""A file the dataset store is asked to place."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DatasetTree = Literal["public", "restricted"]


class DatasetWrite(BaseModel):
    """One relative path and the tree it is allowed to enter."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    relative_path: str = Field(min_length=1)
    body: bytes
    redistributable: bool
    tree: DatasetTree
