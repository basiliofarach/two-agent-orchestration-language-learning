"""One tutor role. T1 is a stimulus. The scripted roles bound oversight."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

TutorRoleName = Literal["T1", "T2", "T3", "T4"]
TutorDriver = Literal["model", "script"]


class TutorRoleCard(BaseModel):
    """How a tutor role acts on a held turn."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: TutorRoleName
    driver: TutorDriver
    system_prompt: str | None = None
    few_shot: tuple[str, ...] = ()
    stop_at_turn: int | None = None

    @model_validator(mode="after")
    def fields_match_the_role(self) -> "TutorRoleCard":
        """T1 is the only model. T4 is the only role that stops on a turn."""
        if self.role == "T1":
            if (
                self.driver != "model"
                or not self.system_prompt
                or self.stop_at_turn is not None
            ):
                msg = "T1 is a model with a prompt and no planned stop"
                raise ValueError(msg)
            return self
        if self.driver != "script" or self.system_prompt is not None or self.few_shot:
            msg = "a scripted role has no prompt"
            raise ValueError(msg)
        if self.role == "T4" and self.stop_at_turn is None:
            msg = "T4 names the turn it stops"
            raise ValueError(msg)
        if self.role != "T4" and self.stop_at_turn is not None:
            msg = "only T4 stops on a planned turn"
            raise ValueError(msg)
        return self


class DashboardView(BaseModel):
    """The held turn a tutor role is allowed to see. Nothing else."""

    model_config = ConfigDict(extra="ignore")

    status: Literal["awaiting_tutor_approval", "held_for_review"]
    output_before_checks: str | None = None
    turn_index: int = Field(default=0, ge=0)
    policy_version: str = ""


class TutorDecision(BaseModel):
    """The dashboard action. An unparseable model answer is ``none``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: Literal["approve", "edit", "override", "stop", "none"]
    edited_output: str | None = None
    role_failure: bool = False

    @model_validator(mode="after")
    def edit_names_the_text(self) -> "TutorDecision":
        """An edit carries the text it would release. Nothing else does."""
        if self.decision == "edit":
            output = self.edited_output
            if output is None or not output.strip():
                msg = "an edit names the text"
                raise ValueError(msg)
            return self
        if self.edited_output is not None:
            msg = "edited_output is set only when the tutor edits"
            raise ValueError(msg)
        return self
