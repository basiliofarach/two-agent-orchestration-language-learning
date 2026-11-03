"""Turn a case plan into utterances. The payload bytes are the label."""

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from tutor_sim.domain.models.case import (
    CaseSpec,
    Construction,
    GeneratorStamp,
    StimulusCase,
)
from tutor_sim.domain.models.payload import Payload
from tutor_sim.domain.models.storage import DatasetTree, DatasetWrite
from tutor_sim.domain.ports.dataset_store import DatasetStorePort
from tutor_sim.domain.ports.role_model import RoleModelPort


class RealisePlan(BaseModel):
    """The cases and the payloads a realise command reads."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset_version: str
    policy_version: str
    seed: int
    cases: tuple[CaseSpec, ...]
    payloads: tuple[Payload, ...] = ()


class PlanFile:
    """``plan.json`` beside the dataset."""

    def load(self, path: Path) -> RealisePlan:
        """Read the plan. A missing file is a command error."""
        if not path.is_file():
            msg = "no case plan"
            raise FileNotFoundError(msg)
        return RealisePlan.model_validate_json(path.read_text(encoding="utf-8"))


class PayloadIndex:
    """Payload text by id. The case names the id; the bytes come from here."""

    def __init__(self, payloads: tuple[Payload, ...]) -> None:
        self._text = {item.payload_id: item.text for item in payloads}
        self._items = payloads

    def text(self, payload_id: str | None) -> str | None:
        """The planted string, or none when the case has no payload."""
        if payload_id is None:
            return None
        try:
            return self._text[payload_id]
        except KeyError as exc:
            msg = "the case names a payload the plan does not contain"
            raise KeyError(msg) from exc

    def items(self) -> tuple[Payload, ...]:
        """Every payload, so the release tree can see their licences."""
        return self._items


class ReleaseTree:
    """Public only when every source and payload may be redistributed."""

    def choose(self, redistributable: tuple[bool, ...]) -> DatasetTree:
        """Restricted as soon as one item may not be published."""
        if any(not flag for flag in redistributable):
            return "restricted"
        return "public"


class PupilPrompt:
    """The role-model prompt. The payload is planted in the user turn."""

    def system(self, case: CaseSpec) -> str:
        """The persona card. The system under test never sees it."""
        return f"persona {case.persona_id}"

    def user(self, case: CaseSpec, payload: str | None) -> str:
        """The instruction. A payload is included verbatim."""
        text = f"intent {case.intent}"
        if payload is None:
            return text
        return f"{text}\n{payload}"


class ConstructionCheck:
    """The planted payload is an exact substring, or the case is discarded."""

    def present(self, utterance: str, payload: str | None) -> bool:
        """Blank text is never a construction. No payload means nothing to miss."""
        if not utterance.strip():
            return False
        if payload is None:
            return True
        return payload in utterance


class NoiseTransformer:
    """Seeded noise outside the payload span. The payload bytes stay put."""

    def apply(self, utterance: str, payload: str | None, seed: int) -> str:
        """Typos, casing, a filler, or an L1 aside, never inside the payload."""
        start, end = self._bounds(utterance, payload)
        kind = seed % 4
        if kind == 0:
            return self._insert(utterance, end, " um")
        if kind == 1:
            return self._case(utterance, start, end, seed)
        if kind == 2:
            return self._insert(utterance, end, " pues")
        return self._typo(utterance, start, end, seed)

    def _bounds(self, utterance: str, payload: str | None) -> tuple[int, int]:
        if payload is None:
            return (0, 0)
        start = utterance.find(payload)
        if start < 0:
            msg = "the payload is not in the utterance"
            raise ValueError(msg)
        return (start, start + len(payload))

    def _insert(self, utterance: str, end: int, extra: str) -> str:
        return f"{utterance[:end]}{extra}{utterance[end:]}"

    def _outside(self, utterance: str, start: int, end: int) -> tuple[int, ...]:
        return tuple(
            index
            for index, char in enumerate(utterance)
            if not start <= index < end and char.isalpha()
        )

    def _case(self, utterance: str, start: int, end: int, seed: int) -> str:
        indexes = self._outside(utterance, start, end)
        if not indexes:
            return self._insert(utterance, end, " um")
        index = indexes[seed % len(indexes)]
        char = utterance[index]
        flipped = char.lower() if char.isupper() else char.upper()
        return f"{utterance[:index]}{flipped}{utterance[index + 1 :]}"

    def _typo(self, utterance: str, start: int, end: int, seed: int) -> str:
        indexes = self._outside(utterance, start, end)
        if not indexes:
            return self._insert(utterance, end, " um")
        index = indexes[seed % len(indexes)]
        return f"{utterance[:index]}x{utterance[index + 1 :]}"


class PupilRealiser:
    """Persona, intent and payload through the role model, then the check."""

    def __init__(
        self,
        model: RoleModelPort,
        check: ConstructionCheck,
        noise: NoiseTransformer,
    ) -> None:
        self._model = model
        self._check = check
        self._noise = noise
        self._prompt = PupilPrompt()

    def realise(self, case: CaseSpec, payload: str | None, seed: int) -> StimulusCase:
        """Up to three completions. A miss is discarded, not rewritten by hand."""
        utterance = ""
        present = False
        attempts = 0
        while attempts < 3 and not present:
            attempts += 1
            utterance = self._model.complete(
                self._prompt.system(case), self._prompt.user(case, payload)
            )
            present = self._check.present(utterance, payload)
        if not utterance:
            utterance = "discarded"
        if present and case.variant == "noisy":
            utterance = self._noise.apply(utterance, payload, seed)
            present = self._check.present(utterance, payload)
        return StimulusCase(
            **case.model_dump(),
            utterance=utterance,
            construction=Construction(
                payload_present=present,
                attempts=attempts,
                discarded=not present,
            ),
            generator=GeneratorStamp(
                weights_sha=self._model.weights_sha(),
                seed=seed,
                temperature=0.0,
                template_version="realise-1",
                card_version=case.policy_version,
            ),
        )


class DiscardLog:
    """How many constructions were thrown away."""

    def body(self, cases: tuple[StimulusCase, ...]) -> bytes:
        """JSON with the attempted and discarded counts."""
        discarded = sum(1 for case in cases if case.construction.discarded)
        payload = {"attempted": len(cases), "discarded": discarded}
        return json.dumps(payload, sort_keys=True).encode("utf-8")


class StimulusLines:
    """One JSON object per line."""

    def body(self, cases: tuple[StimulusCase, ...]) -> bytes:
        """The frozen stimuli. Discarded cases are not included."""
        kept = tuple(case for case in cases if not case.construction.discarded)
        if not kept:
            return b""
        lines = [case.model_dump_json() for case in kept]
        return ("\n".join(lines) + "\n").encode("utf-8")


class DatasetBytes:
    """Place one file through the dataset store."""

    def __init__(self, store: DatasetStorePort) -> None:
        self._store = store

    def write(self, relative: str, body: bytes, tree: DatasetTree) -> None:
        """Public bytes must be redistributable. The store enforces it too."""
        self._store.write(
            DatasetWrite(
                relative_path=relative,
                body=body,
                redistributable=tree == "public",
                tree=tree,
            )
        )
