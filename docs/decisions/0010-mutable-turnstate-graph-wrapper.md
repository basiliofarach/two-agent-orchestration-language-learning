# 0010. Working `TurnState` is a mutable Pydantic model; graph state wraps it

*Status:* Accepted · *Date:* 2026-09-21

Supersedes the frozen-`TurnState` clause of
[DEC-0009](0009-langgraph-state-wraps-frozen-turnstate.md). The application-layer
graph wrapper and the domain/LangGraph seam from DEC-0009 still stand.

## Context

[ARCHITECTURE.md §5](../architecture/ARCHITECTURE.md#5-domain-model) accumulates
working turn state on a live `TurnState`. DEC-0009 froze that object and had
nodes derive successors with `model_copy(update=...)`, on the argument that the
Article 12 hash chain needed an immutable in-flight turn.

That argument does not hold. The hash chain hashes the **written audit record**,
not the working object. DEC-0002 already requires `TurnAuditRecord`,
`HumanAction` and `GateVerdict` to be frozen. Pydantic is in this stack so
working models can validate and accumulate fields across a turn; freezing
`TurnState` fights that choice and contradicts §5.

DEC-0009 also warned that relaxing `frozen=True` on `TurnState` would be
resolved "under implementation pressure" the wrong way. This record decides it
on purpose, against that frozen default.

## Decision

`TurnState` is a mutable Pydantic `BaseModel`. It is accumulated across the
turn. `extra="forbid"` still applies. It is **not** `frozen=True`.

Audit and evidence records stay frozen, per DEC-0002:
`TurnAuditRecord`, `HumanAction`, `GateVerdict`, and `SourceRef` as an
evidence-bearing identifier. The orchestrator snapshots the live turn into a
`TurnAuditRecord` at each append. Immutability is required of the record written
to the log, not of the in-flight object.

Graph state remains an application-layer wrapper in `application/turn/`, holding
the current `TurnState` plus bookkeeping. The domain still imports no LangGraph
type. A `TypedDict` at that seam, if LangGraph requires one, stays a boundary
adapter (the part of DEC-0009 that is kept).

Nodes update the live `TurnState` (assign validated fields) and return the
wrapper. They stay thin: resolve a port, delegate, write results onto the turn,
return.

Gates still **return a verdict and never mutate** the turn (REQ-GATES,
DEC-0005). That is a gate contract, not a `frozen=True` constraint on
`TurnState`. Tests compare the turn before and after `evaluate()`.

## Consequences

**Positive.** Working state matches ARCHITECTURE §5 and the reason Pydantic is
used. The hash chain remains on frozen audit records. Nodes stop allocating a
successor per step for a compliance property the snapshot already provides.

**Negative.** A gate or node that mutates the turn when it should not is no
longer a type error. Tests must catch it: gates do not mutate; audit snapshots
are frozen copies, not aliases of the live object.

**Test obligation.**

- `TurnState` accepts field assignment; audit/evidence models raise on
  assignment.
- Each gate's `test_*_does_not_mutate_the_turn` compares the input before and
  after `evaluate()`.
- An integration test asserts that a `TurnAuditRecord` is a frozen snapshot
  distinct from the live `TurnState` it was copied from — mutating the turn
  afterwards must not change a record already appended.
