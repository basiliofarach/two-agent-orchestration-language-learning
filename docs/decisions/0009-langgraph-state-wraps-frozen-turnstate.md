# 0009. LangGraph state is an application-layer wrapper over a frozen `TurnState`

*Status:* Accepted · *Date:* 2026-09-18

## Context

DEC-0002 prohibits `TypedDict` for domain data and requires audit-bearing models to be
frozen Pydantic models. LangGraph's conventional state container is a `TypedDict` that
nodes mutate in place, and its reducers are written against that shape.

DEC-0004 noted this friction without resolving it. Left undecided until Phase 6, it
would be resolved under implementation pressure, and the likely outcome is the wrong
one: relaxing `frozen=True` on `TurnState` so nodes can mutate it. That would remove
the immutability the Article 12 hash chain depends on, to satisfy a framework
convention.

## Decision

`TurnState` stays a frozen Pydantic model in the domain layer and is never mutated.

Graph state is a **separate application-layer container** holding the current
`TurnState` plus graph bookkeeping. It lives in `application/turn/`, not in `domain/`,
so the domain never imports a LangGraph type and the DEC-0002 prohibition is unaffected
inside the domain boundary.

Nodes **replace rather than mutate**: a node reads the current `TurnState`, derives a
successor with `model_copy(update=...)`, and returns it. Each turn therefore has a
sequence of immutable snapshots rather than one mutated object, which is what makes a
checkpoint meaningful — a LangGraph checkpoint of a mutable object records only its
final shape.

The graph-state container is a boundary adapter. Whether LangGraph requires a
`TypedDict` at that seam is an implementation detail of the wrapper, and the DEC-0002
ban does not reach it; that ban governs domain data.

## Consequences

**Positive.** `TurnState` immutability survives, so the hash chain and replay hold.
Checkpoints capture genuine intermediate states. The domain layer stays free of
framework types, preserving the dependency rule.

**Negative.** One translation at the graph boundary, and a small allocation per node
from `model_copy`. Negligible against an LLM call.

**Test obligation.** An integration test asserts that `TurnState` instances observed at
successive nodes are distinct objects and that no node mutates its input — otherwise
the replace-don't-mutate rule decays silently into mutation.
