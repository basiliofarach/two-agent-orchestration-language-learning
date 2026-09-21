# 0011. Layer roles and application-service lifecycle chain

*Status:* Accepted · *Date:* 2026-09-21

## Context

DEC-0001 requires an `abc.ABC` before any implementation. DEC-0005 already
owns Chain of Responsibility for the four oversight gates, interleaved with
the graph — not as a single `chain.run(turn)`.

What is still unspecified is how a unit of work is *authored and called*:
where a Pydantic class, a port, an adapter, a use case, and a FastAPI router
sit relative to each other, and how a service's steps are declared so they
cannot be invoked out of order from the HTTP boundary.

A single class that exposes `prepare`, `execute`, and `finalise` (even
behind a template `run()`) can be called at the wrong stage: `execute`
before `prepare`, or `finalise` at the start. Giving `execute` the
`TResult` return type makes `finalise` skippable — the work already
produced the result.

Each stage must expose **exactly one** method: the next method on the
chain. `TResult` is produced only by the last stage.

## Decision

### Four roles

| Role | In this codebase | Lives in |
| --- | --- | --- |
| **Class** | Domain model (`pydantic.BaseModel`) | `tutor-core/.../domain/models/` |
| **ABC / interface** | Port (`abc.ABC`) | `tutor-core/.../domain/ports/` |
| **Repo** | Adapter that implements an I/O port | `tutor-api/.../adapters/` |
| **Service** | Application use case | `tutor-core/.../application/services/` |
| **Router** | FastAPI route functions | `tutor-api/.../routers/` |

In Python the ABC **is** the interface. There is no second interface type
(`typing.Protocol` alongside an ABC, or a Java-style `IFoo` plus `FooBase`).
The public methods of the concrete class are exactly the ABC's methods.
Private helpers (`_…`) are allowed; extra public methods on the concrete
class are not — they would let a consumer bypass the contract.

**Call direction.** Router → Service → Port. The adapter is injected behind
the port. The router never imports an adapter. The service never constructs
one. Domain imports neither FastAPI nor SQL.

**Not every class is a service.** Agents are application collaborators of a
use case. Gates implement `OversightGatePort` and stay graph-placed
(DEC-0005). One-method ports (`ClockPort.now`) stay one method.

### Authoring order

For each unit of work, in this order, and not the reverse:

1. **ABC.** Domain port (DEC-0001 list) or, for a use case, the three
   stage-handler ABCs plus the start type that only declares `prepare`.
2. **Contract tests** against those ABCs (stubs for collaborators).
3. **Concrete class** — handler, adapter, or gate.
4. **Router last**, and only if the unit is reached over HTTP. The router
   walks the chain and maps HTTP errors. It holds no logic.

Phase 1 of the implementation plan is steps 1–2 for the domain. Adapters
and routers come in later phases.

### Service lifecycle is a typestate chain

A use case is not one class with three methods. It is three handler ABCs
and three *types*, each with a single public method. The next method does
not exist until the previous stage returns.

These ABCs live in `application/services/service.py`. They are **not**
DEC-0001 ports: they are not substitutable capabilities and do not go in
`domain/ports/`.

```python
class PrepareHandler(abc.ABC, Generic[TCommand, TPrepared]):
    @abc.abstractmethod
    def run(self, command: TCommand) -> TPrepared: ...


class ExecuteHandler(abc.ABC, Generic[TPrepared, TExecuted]):
    @abc.abstractmethod
    def run(self, prepared: TPrepared) -> TExecuted: ...


class FinaliseHandler(abc.ABC, Generic[TExecuted, TResult]):
    @abc.abstractmethod
    def run(self, executed: TExecuted) -> TResult: ...


class ApplicationService(Generic[TCommand, TPrepared, TExecuted, TResult]):
    def __init__(
        self,
        prepare: PrepareHandler[TCommand, TPrepared],
        execute: ExecuteHandler[TPrepared, TExecuted],
        finalise: FinaliseHandler[TExecuted, TResult],
    ) -> None:
        self._prepare = prepare
        self._execute = execute
        self._finalise = finalise

    def prepare(
        self, command: TCommand
    ) -> Prepared[TPrepared, TExecuted, TResult]:
        return Prepared(
            self._prepare.run(command),
            self._execute,
            self._finalise,
        )


class Prepared(Generic[TPrepared, TExecuted, TResult]):
    def execute(self) -> Executed[TExecuted, TResult]: ...


class Executed(Generic[TExecuted, TResult]):
    def finalise(self) -> TResult: ...
```

`TCommand`, `TPrepared`, `TExecuted`, and `TResult` are Pydantic models
(DEC-0002). `execute` returns `Executed`, never `TResult`. Only
`finalise` returns `TResult`.

At each point in the process, one method is callable:

| You hold | You may call | You get |
| --- | --- | --- |
| `ApplicationService` | `prepare(command)` | `Prepared` |
| `Prepared` | `execute()` | `Executed` |
| `Executed` | `finalise()` | `TResult` |

There is no `run()` that exposes every stage on the same object. There is
no `finalise` on `ApplicationService`, and no `prepare` on `Prepared`.

The router walks the chain in one expression and does nothing else:

```python
return service.prepare(body).execute().finalise()
```

`Prepared` and `Executed` are continuation values, not collaborators.
They carry the already-injected next handler; they do not construct one
(DEC-0001). Stopping after `prepare` means not calling `execute` — a
raised error, not a skipped type.

`ConductTurn`'s execute-handler delegates to the LangGraph backbone
(DEC-0004). It does **not** list the four gates as service stages. Gate
order remains graph placement (DEC-0005, REQ-GATES).

### Rejected

**Three methods on one class.** A template `run()` that calls
`prepare` / `execute` / `finalise` on `self` still leaves those methods
callable in any order. `execute -> TResult` makes `finalise` optional.
That is the shape this record replaces.

**Returning `Self` from the same type.** Untyped fluent chaining
(`service.prepare().execute()` on one class) does not remove the other
methods. The next stage must be a *different type*.

**Per-call `dispose()`.** Object lifetimes are wireup scopes (DEC-0003).
A service does not open or close the database, the model client, or the
clock per request. Resource cleanup is not a use-case stage.

**Chain of Responsibility on every class.** CoR is the gate pattern
(DEC-0005). Applying a handler chain to `ClockPort`, a Pydantic model, or
the whole tutoring turn would either add ceremony without a second
implementation (DEC-0001 collapse rule) or recreate the single-pass
`chain.run(turn)` DEC-0005 forbids.

**A new domain port for these ABCs.** The stage handlers fail both
justifications in DEC-0001: they are not a scope boundary, and they are
not a capability that a test stub replaces. Stubs replace the *ports the
handlers hold*.

## Consequences

**Positive.** Folder layout, authoring order, and the service entrypoint
are one rule. A caller physically cannot invoke the wrong stage: the
method is absent. The gate CoR and the service chain cannot be confused:
one is interleaved with retrieval and generation; the other is how a use
case is called from HTTP. Capability scoping stays on DEC-0001 ports.

**Negative.** Each use case is three handler classes plus the wired
`ApplicationService`. Accepted — the types *are* the evidence that steps
cannot run out of order.

**Test obligation.**

- `ApplicationService` has public `prepare` only. `Prepared` has public
  `execute` only. `Executed` has public `finalise` only.
- `execute` annotated return type is `Executed`, not `TResult`.
- A spy records `prepare` then `execute` then `finalise`, in that order.
- Instantiating a handler ABC that does not implement `run` raises
  `TypeError`.
- A router test (integration) calls
  `prepare(...).execute().finalise()` and never a handler `run` directly.
- `ConductTurn` tests still assert gate placement on the graph, not on
  service-stage methods.
