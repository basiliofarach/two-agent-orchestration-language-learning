# 0010. Working `TurnState` is a mutable Pydantic model; graph state wraps it

*Status:* Accepted · *Date:* 2026-09-21 · *Amended:* 2026-09-21 (recorded instants)

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

### Amendment — recorded instants are UTC, and columns are `timestamptz`

The snapshot above is what the Article 12 chain hashes, so the timestamp it
carries has to be canonical. Two rules, one at each end.

**In the database, a recorded instant is `timestamptz`.** Not `timestamp`
with UTC enforced by convention in the application. `timestamptz` stores no
timezone — both types are 8 bytes holding a UTC instant — so the choice costs
nothing and buys the checks:

- psycopg3 returns an aware `datetime` for `timestamptz` and a **naive** one
  for `timestamp`. A naive read fails `AwareDatetime` on the way back in, so
  `timestamp` obliges the adapter to re-attach UTC by hand on every audit
  read: an unenforced step in the evidence path.
- `now()` and `CURRENT_TIMESTAMP` are `timestamptz`. Written to a `timestamp`
  column they are silently cast through the session `TimeZone`. That path is
  open to a column default, a trigger, `psql` or a restore — none of which
  route through the application, so an application-side convention cannot
  close it.
- Rows written under different session timezones compare as wall-clock
  digits, and the chain breaks with no error raised anywhere.

Default microsecond precision. `timestamptz(3)` and `(0)` **round**, which
changes a digest.

The exception this does not cover is floating civil time — "09:00 local,
whatever the offset turns out to be". Nothing recorded here is that; every
instant in the log is an instant. A column that genuinely needs floating
civil time is a further amendment.

**In the domain, `AwareDatetime` converts to UTC after accepting.**
`domain/models/timestamps.py` rejects naive input, then applies
`astimezone(UTC)`. Rejection alone is not enough: `12:00+02:00` and
`10:00+00:00` are the same instant and `timestamptz` stores them identically,
but they serialise to different strings and therefore hash differently. An
offset that survives into a record is a silent chain divergence. A datetime
carrying a `tzinfo` whose `utcoffset` is `None` is naive in effect and is
rejected with the naive ones.

`ClockPort` stays the only source of the current instant (rule 7). This
amendment canonicalises what callers pass in; it does not license
`datetime.now()`.

This is a replay-determinism rule, not an encryption one. `recorded_at` is a
registered cleartext exemption under
[DEC-0012](0012-encryption-at-rest-by-default.md) and is unaffected by it.

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
- A naive datetime, and one whose `tzinfo` yields no offset, are both rejected
  by every `AwareDatetime` field.
- An offset instant is normalised: two records built from the same instant in
  different offsets serialise identically.
- When the schema exists, an integration test reads `information_schema` and
  asserts no ordinary public table carries a `timestamp without time zone`
  column.
