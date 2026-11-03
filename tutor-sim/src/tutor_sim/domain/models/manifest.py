"""The frozen dataset manifest."""

from pydantic import BaseModel, ConfigDict, Field

from tutor_sim.domain.models.source import LicenceReview
from tutor_sim.domain.models.storage import DatasetTree
from tutor_sim.domain.models.timestamps import AwareDatetime


class RoleModelPin(BaseModel):
    """The role model a freeze was built with."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    weights_sha: str = Field(pattern=r"^[0-9a-f]{64}$")


class SourceRef(BaseModel):
    """Review status copied at freeze. Confirming it later does not move this."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    licence: str = Field(min_length=1)
    licence_review: LicenceReview


class FileDigest(BaseModel):
    """One hashed file in either tree."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str = Field(min_length=1)
    tree: DatasetTree
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(ge=0)


class Manifest(BaseModel):
    """What a freeze fixed. The test-split hash is recorded before any test run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset_version: str = Field(min_length=1)
    seed: int
    policy_version: str = Field(min_length=1)
    role_model: RoleModelPin
    sources: tuple[SourceRef, ...]
    files: tuple[FileDigest, ...]
    test_split_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    frozen_at: AwareDatetime
