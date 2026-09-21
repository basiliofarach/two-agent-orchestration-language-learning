# 0005. Oversight gates as ordered handlers placed across the orchestration graph

*Status:* Accepted · *Date:* 2026-09-18

## Context

REQ-GATES specifies four oversight gates. Their positions in the pipeline are
fixed by their trigger conditions, and they are **not** all located between
generation and delivery:

| Gate | Position (REQ-GATES) |
| --- | --- |
| Context and permission | **before retrieval** — verifies scope so that out-of-minimum history fields are not read |
| Conflict and ambiguity | **after retrieval, before generation** — evaluates the retrieval result, pauses the generation step |
| Sensitivity and high-stakes | **after generation** — evaluates outputs before they are shown |
| Drift and anomaly | **after generation** — monitors retrieval and generation behaviour |

Ordering is a **claim this prototype makes**, not a wiring preference: the
permission gate resolves before retrieval, the conflict gate resolves before
generation, and the human stop resolves before any material reaches the learner.
Gates that are advisory rather than enforced do not support the claim that the
obligations are structural. An implementation that evaluates gates at the wrong
point falsifies REQ-GATES.

## Decision

Each gate is a class implementing `OversightGatePort`, injected, and **invoked
at its own point in the orchestration graph** in the order declared above.

There is **no single-pass `chain.run(turn)` over a finished turn.** A single
pass would require retrieval and generation to have already executed before any
gate is consulted, which would make the permission and conflict gates detective
rather than preventive. The ordering constraint cannot be satisfied by a chain
that runs after the fact.

```python
class GateVerdict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    gate_name: str
    decision: Literal["pass", "pause", "stop"]
    reason: str                       # surfaced verbatim on the dashboard
    policy_rule_id: str               # which rule version was checked (REQ-POLICY)
```

`GateVerdict` carries no safety flags. Flags are produced by the output checks
and live on the turn; a verdict reports a *decision about* the turn, not new
facts within it.

**Composition.** The ordered gate collection is registered in one place and
consumed by the orchestrator, which owns placement and logging. A gate cannot
reorder the sequence, skip a successor, or edit what it inspects. It returns a
verdict; that is all.

**Control flow on a non-pass verdict.** `pause` and `stop` route to human review
([ARCHITECTURE.md §8](../architecture/ARCHITECTURE.md#8-runtime-view)). Neither
continues to the next pipeline stage. A permission `stop` means retrieval does
not run.

**Logging policy — owned by the orchestrator, not the gate.** Every gate that
had sufficient input to evaluate is logged with its verdict and
`policy_rule_id`. A gate that was never reached, because an earlier gate stopped
the turn, is recorded as `not_evaluated` with the reason. The log therefore
distinguishes three states — *checked and passed*, *checked and fired*, *not
reached* — which is strictly more informative for the evidence pack than forcing
every gate to run on incomplete input.

## Consequences

**Positive.** The REQ-GATES ordering claim is enforced by graph structure rather
than by a convention. Gates remain unit-testable in isolation. Adding a fifth
gate is a registration plus a graph placement. The three-state log makes the
Article 12 record honest about what was and was not evaluated.

**Negative.** Gate invocation is distributed across the graph rather than
centralised in one call, so "where do the gates run" is answered by the graph
definition rather than by a single class. Mitigated by keeping the ordered
registry in one module, so the sequence is still declared in one readable place.

**On the pattern name.** This is Chain of Responsibility in its essential sense
— ordered handlers sharing one interface, each able to stop processing, defer to
a human, or pass control on. It deviates from the textbook form in that the
chain is *interleaved with the pipeline* rather than invoked as a single linked
traversal. The deviation is forced by REQ-GATES: the handlers guard different
stages, so they cannot all be invoked at one point. Stating the deviation is
more defensible than claiming a pattern the code does not implement.

See also
[DEC-0011](0011-layer-roles-and-service-lifecycle.md): application use cases
use a typestate chain (`prepare` → `execute` → `finalise` on different
types). That is not this gate chain and must not become a second
`chain.run(turn)`.

## Superseded reasoning

An earlier revision of this record placed all four gates "between generation and
delivery" and specified a single `OversightChain.run(turn)` that evaluated every
gate on a complete turn, never short-circuiting. That was wrong on both counts:
it contradicted REQ-GATES, and "never short-circuit" would have meant running
retrieval after a permission `stop` — making the permission gate detective and
undoing the control it exists to provide.
