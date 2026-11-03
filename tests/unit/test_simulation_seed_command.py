"""The simulation seed refuses the request role and keeps the fault partition out."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from tutor_api.curation.simulation_seed import (
    FaultPartition,
    HistoryInstants,
    JsonlFile,
    OperatorRole,
    SeedDocument,
    SeedLearner,
    SeedProcess,
    SimulationSeedMain,
)
from tutor_api.settings import ApplicationSettings
from tutor_core.domain.ports.clock import ClockPort


class FixedClock(ClockPort):
    def __init__(self, instant: datetime) -> None:
        self._instant = instant

    def now(self) -> datetime:
        return self._instant


class Catalogue:
    def document(self, partition: str = "default") -> SeedDocument:
        return SeedDocument(
            document_id=UUID(int=2 if partition == "default" else 4),
            source_uri="kb://sim/note",
            version="1",
            review_status="approved",
            licence="custom:generated",
            cefr_level="A1",
            level_method="dataset-label",
            content="Hola means hello.",
            partition=partition,  # type: ignore[arg-type]
        )

    def learner(self, history: bool = True, number: int = 3) -> SeedLearner:
        events: tuple[dict[str, object], ...] = ()
        if history:
            events = ({"item_id": "hola", "correct": True, "days_before_seed": 2},)
        return SeedLearner.model_validate(
            {
                "persona_id": f"p{number}",
                "learner_id": str(UUID(int=number)),
                "pseudonym": f"p{number}",
                "proficiency_level": "A1",
                "history": events,
            }
        )


class TestOperatorRole:
    def test_the_request_role_cannot_seed(self) -> None:
        with pytest.raises(PermissionError, match="request role"):
            OperatorRole().require_owner("request")

    def test_the_owner_may_seed(self) -> None:
        OperatorRole().require_owner("owner")


class TestFaultPartition:
    def test_stress_is_the_only_way_in_for_a_fault(self) -> None:
        documents = (Catalogue().document(), Catalogue().document("faults"))
        assert [
            item.partition for item in FaultPartition().select(documents, False)
        ] == ["default"]
        assert len(FaultPartition().select(documents, True)) == 2


class TestHistoryInstants:
    def test_days_before_seed_are_subtracted_from_the_clock(self) -> None:
        clock = FixedClock(datetime(2026, 11, 3, tzinfo=UTC))
        assert HistoryInstants(clock).occurred_at(2) == datetime(
            2026, 11, 1, tzinfo=UTC
        )

    def test_a_naive_clock_is_refused(self) -> None:
        clock = FixedClock(datetime(2026, 11, 3))
        with pytest.raises(ValueError, match="timezone-aware"):
            HistoryInstants(clock).occurred_at(0)


class TestJsonlFile:
    def test_blank_lines_are_skipped(self, tmp_path: Path) -> None:
        path = tmp_path / "kb.jsonl"
        path.write_text(
            "\n" + Catalogue().document().model_dump_json() + "\n\n", encoding="utf-8"
        )
        assert len(JsonlFile().documents(path)) == 1

    def test_a_missing_file_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="roster.jsonl"):
            JsonlFile().learners(tmp_path / "roster.jsonl")


class TestSeedProcess:
    def test_stress_is_optional_and_two_paths_are_required(self) -> None:
        stress, kb, roster = SeedProcess().arguments(
            ["--stress", "kb.jsonl", "c2.jsonl"]
        )
        assert stress is True
        assert kb.name == "kb.jsonl"
        assert roster.name == "c2.jsonl"
        plain = SeedProcess().arguments(["kb.jsonl", "c2.jsonl"])
        assert plain[0] is False

    @pytest.mark.parametrize("argv", [[], ["--stress"], ["only.jsonl"]])
    def test_a_bad_invocation_is_a_usage_error(self, argv: list[str]) -> None:
        with pytest.raises(ValueError, match="usage"):
            SeedProcess().arguments(argv)


class TestSeedMainGuards:
    async def test_a_missing_threshold_is_refused_before_a_connection(self) -> None:
        settings = ApplicationSettings(_env_file=None)  # type: ignore[call-arg]
        with pytest.raises(ValueError, match="CONFLICT_CONFIDENCE_THRESHOLD"):
            await SimulationSeedMain().run(settings, (), (), False, "owner")

    async def test_the_request_role_is_refused_before_a_connection(self) -> None:
        settings = ApplicationSettings(  # type: ignore[call-arg]
            _env_file=None, conflict_confidence_threshold=0.3
        )
        with pytest.raises(PermissionError, match="request role"):
            await SimulationSeedMain().run(settings, (), (), False, "request")
