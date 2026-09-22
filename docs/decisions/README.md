# Decision records

One record per choice: what was decided, what was rejected, and why. These
records document decisions and their rationale. They do not state requirements,
describe architecture, or define build order; each of those has its own
document.
{ .lead }

Format: [MADR](https://adr.github.io/madr/). Immutable once `Accepted` —
supersede rather than edit, so each decision keeps a stable identifier.

Related documents: the obligations these decisions serve are in
[Requirements](../requirements.md); how the accepted decisions compose is in
[Architecture](../architecture/ARCHITECTURE.md); the order they are built in is
in the [Implementation plan](../architecture/IMPLEMENTATION-PLAN.md).

## Register

| ID | Decision | Status |
| ---- | ---------- | -------- |
| [DEC-0001](0001-interface-first-oop-di-capability-scoping.md) | Interface-first OOP; DI as capability scoping | Accepted |
| [DEC-0002](0002-pydantic-basemodel-only.md) | Pydantic `BaseModel` as the only model type | Accepted |
| [DEC-0003](0003-python-toolchain-uv-fastapi-wireup.md) | uv + FastAPI + wireup | Accepted |
| [DEC-0004](0004-langgraph-orchestration-backbone.md) | LangGraph as deterministic backbone | Accepted |
| [DEC-0005](0005-oversight-gates-chain-of-responsibility.md) | Oversight gates as ordered handlers across the graph | Accepted |
| [DEC-0006](0006-postgres-pgvector-single-store.md) | Postgres + pgvector, single store | Accepted |
| [DEC-0007](0007-local-pinned-open-weight-model.md) | Local pinned Qwen3-8B behind a provider port | Accepted |
| [DEC-0008](0008-frontend-react-router-v8-shadcn.md) | React Router v8 + fs-routes + shadcn/ui | Accepted |
| [DEC-0009](0009-langgraph-state-wraps-frozen-turnstate.md) | LangGraph state wraps a frozen `TurnState` | *Superseded by DEC-0010* |
| [DEC-0010](0010-mutable-turnstate-graph-wrapper.md) | Working `TurnState` is mutable Pydantic; graph state wraps it | Accepted (amended: recorded instants) |
| [DEC-0011](0011-layer-roles-and-service-lifecycle.md) | Layer roles; application-service typestate chain | Accepted |
| [DEC-0012](0012-encryption-at-rest-by-default.md) | Encryption at rest by default; plaintext is the exception | Accepted |

## Article coverage

Which records carry the argument for each Article. A record appears under every
Article it speaks to, so the columns do not partition.

| AI Act article | Records |
| --- | --- |
| Art. 10 — Data governance | 0002, 0006, 0007, 0012 |
| Art. 12 — Logging and traceability | 0002, 0004, 0006, 0009, 0010, 0012 |
| Art. 14 — Human oversight | 0004, 0005, 0008 |
| Art. 15 — Accuracy and robustness | 0001, 0005, 0007, 0011 |

!!! warning "DEC-0012 is not an AI Act control"

    Encryption at rest is a GDPR Article 32 measure under a risk test. It
    appears under Art. 10 and Art. 12 above because the *data governance* and
    *traceability* arguments depend on it — not because Article 15 requires
    encryption. Citing Art. 15 as its legal basis is an error the record
    explicitly forbids.
