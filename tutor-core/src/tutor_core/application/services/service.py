"""Stage-handler ABCs and the typestate chain a use case is called through.

These are not DEC-0001 ports (DEC-0011). Each holder type exposes exactly one
public method, and that method returns the next type: ``execute`` does not
exist until ``prepare`` has returned ``Prepared``, and only ``finalise``
returns the result.

``ExecuteHandler.run`` is async: execution is where a use case does its I/O,
and the request path is async end to end (DEC-0014). ``prepare`` and
``finalise`` stay synchronous. The router therefore writes
``(await service.prepare(body).execute()).finalise()``.
"""

from abc import ABC, abstractmethod


class PrepareHandler[TCommand, TPrepared](ABC):
    """Turn a command into the prepared input of the execute stage."""

    @abstractmethod
    def run(self, command: TCommand) -> TPrepared:
        """Validate and shape the command. No I/O."""
        raise NotImplementedError  # pragma: no cover


class ExecuteHandler[TPrepared, TExecuted](ABC):
    """Do the use case's work on prepared input."""

    @abstractmethod
    async def run(self, prepared: TPrepared) -> TExecuted:
        """Perform the work and return what finalise needs."""
        raise NotImplementedError  # pragma: no cover


class FinaliseHandler[TExecuted, TResult](ABC):
    """Shape the executed state into the result the caller receives."""

    @abstractmethod
    def run(self, executed: TExecuted) -> TResult:
        """Return the result. No I/O."""
        raise NotImplementedError  # pragma: no cover


class Executed[TExecuted, TResult]:
    """Holds the executed state. The only method is ``finalise``."""

    def __init__(
        self,
        executed: TExecuted,
        finalise: FinaliseHandler[TExecuted, TResult],
    ) -> None:
        self._executed = executed
        self._finalise = finalise

    def finalise(self) -> TResult:
        """Return the use case's result."""
        return self._finalise.run(self._executed)


class Prepared[TPrepared, TExecuted, TResult]:
    """Holds the prepared input. The only method is ``execute``."""

    def __init__(
        self,
        prepared: TPrepared,
        execute: ExecuteHandler[TPrepared, TExecuted],
        finalise: FinaliseHandler[TExecuted, TResult],
    ) -> None:
        self._prepared = prepared
        self._execute = execute
        self._finalise = finalise

    async def execute(self) -> Executed[TExecuted, TResult]:
        """Run the work. Returns ``Executed``, never the result."""
        executed = await self._execute.run(self._prepared)
        return Executed(executed, self._finalise)


class ApplicationService[TCommand, TPrepared, TExecuted, TResult]:
    """The start of the chain. The only method is ``prepare``."""

    def __init__(
        self,
        prepare: PrepareHandler[TCommand, TPrepared],
        execute: ExecuteHandler[TPrepared, TExecuted],
        finalise: FinaliseHandler[TExecuted, TResult],
    ) -> None:
        self._prepare = prepare
        self._execute = execute
        self._finalise = finalise

    def prepare(self, command: TCommand) -> Prepared[TPrepared, TExecuted, TResult]:
        """Prepare ``command`` and return the holder whose only method is execute."""
        return Prepared(self._prepare.run(command), self._execute, self._finalise)
