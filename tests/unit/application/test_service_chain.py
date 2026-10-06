"""DEC-0011: one public method per holder, and only finalise returns the result."""

import inspect
import typing

import pytest

from tutor_core.application.services.service import (
    ApplicationService,
    Executed,
    ExecuteHandler,
    FinaliseHandler,
    Prepared,
    PrepareHandler,
)


class Calls:
    def __init__(self) -> None:
        self.order: list[str] = []


class SpyPrepare(PrepareHandler[str, str]):
    def __init__(self, calls: Calls) -> None:
        self._calls = calls

    def run(self, command: str) -> str:
        self._calls.order.append("prepare")
        return command + ":prepared"


class SpyExecute(ExecuteHandler[str, str]):
    def __init__(self, calls: Calls) -> None:
        self._calls = calls

    async def run(self, prepared: str) -> str:
        self._calls.order.append("execute")
        return prepared + ":executed"


class SpyFinalise(FinaliseHandler[str, int]):
    def __init__(self, calls: Calls) -> None:
        self._calls = calls

    def run(self, executed: str) -> int:
        self._calls.order.append("finalise")
        return len(executed)


class Public:
    def methods(self, holder: type) -> set[str]:
        return {
            name
            for name, _ in inspect.getmembers(holder, inspect.isfunction)
            if not name.startswith("_")
        }


class TestTypestateChain:
    def test_each_holder_exposes_exactly_one_method(self) -> None:
        assert Public().methods(ApplicationService) == {"prepare"}
        assert Public().methods(Prepared) == {"execute"}
        assert Public().methods(Executed) == {"finalise"}

    def test_execute_returns_executed_never_the_result(self) -> None:
        hints = typing.get_type_hints(Prepared.execute)
        assert typing.get_origin(hints["return"]) is Executed

    async def test_the_stages_run_in_order_and_only_finalise_yields(self) -> None:
        calls = Calls()
        service = ApplicationService(
            SpyPrepare(calls), SpyExecute(calls), SpyFinalise(calls)
        )
        prepared = service.prepare("turn")
        assert calls.order == ["prepare"]
        executed = await prepared.execute()
        assert calls.order == ["prepare", "execute"]
        assert isinstance(executed, Executed)
        assert executed.finalise() == len("turn:prepared:executed")
        assert calls.order == ["prepare", "execute", "finalise"]

    @pytest.mark.parametrize(
        "handler", [PrepareHandler, ExecuteHandler, FinaliseHandler]
    )
    def test_a_handler_without_run_cannot_be_instantiated(self, handler: type) -> None:
        incomplete = type("Incomplete", (handler,), {})
        with pytest.raises(TypeError, match="abstract"):
            incomplete()
