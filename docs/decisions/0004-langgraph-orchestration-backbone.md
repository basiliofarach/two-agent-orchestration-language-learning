# 0004. LangGraph as the deterministic orchestration backbone

*Status:* Accepted · *Date:* 2026-09-18

## Context

DEC-0005 and [ARCHITECTURE.md §8](../architecture/ARCHITECTURE.md#8-runtime-view)
require a backbone where retrieval reliably precedes generation, oversight gates are
reified as graph nodes, and every tutor intervention is captured in the same state the
audit log records. Article 14 requires that a natural person can interrupt before
delivery; Article 12 requires the full chain producing each turn be reconstructable —
not just LLM input/output pairs.

## Decision

**LangGraph** as the state graph. The tutoring turn is a graph whose nodes are
retrieval, generation and the four gates of DEC-0005, and whose edges encode the order
REQ-GATES requires: permission gate → retrieval → conflict gate → generation →
sensitivity → drift → tutor approval. Human interrupts use LangGraph's `interrupt` checkpoints; the
checkpointer persists a state snapshot at each step.

The graph is *not* used to coordinate autonomous agents. It is used as a
programmatic control-flow device that happens to supply persistence and interrupts.

Every state transition emits a `TurnAuditRecord` (DEC-0002) through `AuditSinkPort`.
Checkpoint identifiers are recorded on the audit record, so a stored checkpoint and
its log entry are mutually resolvable: an examiner can pick a log line and replay
the exact state that produced it.

## Consequences

**Positive.** Article 14's interrupt requirement and Article 12's replay requirement
are met by framework features rather than bespoke code, which is both less work and
more defensible — the mechanism is citable.

**Negative.** LangGraph's state model constrains how domain objects are passed
between nodes, adding friction against DEC-0001's port abstractions. Nodes stay thin:
they resolve ports and delegate, holding no logic themselves. The specific clash
between LangGraph's `TypedDict` state and the DEC-0002 prohibition is resolved in
DEC-0009 — graph state is an application-layer wrapper over a frozen `TurnState`, and
nodes replace rather than mutate.

**Rejected — CrewAI.** The deterministic-flow-wrapping-scoped-crew pattern is
conceptually close, but its human-interrupt and replay primitives are weaker, and
replay is load-bearing for the evidence pack.

**Rejected — hand-rolled orchestrator.** Cleanest possible Chain of Responsibility,
but checkpointing and replay would be built from scratch and the prototype loses the
ability to cite an established framework.
