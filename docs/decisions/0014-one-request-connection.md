# 0014. One connection per request; persistence ports enlist in it

*Status:* Accepted · *Date:* 2026-10-05

Amends [DEC-0001](0001-interface-first-oop-di-capability-scoping.md) (four
port signatures, one `TransactionConnection` method) and
[DEC-0013](0013-first-party-composition-root.md) (a request scope). Carries out
the single-transaction clause of
[DEC-0006](0006-postgres-pgvector-single-store.md).

## Context

DEC-0006 decides that an audit record and the retrieval it describes commit in
one transaction. Phase 3 shipped the retrieval, policy, ingestion and
publication adapters on a synchronous `SqlGateway` over psycopg, while the
audit sink and the unit of work run on an async SQLAlchemy connection over
asyncpg. Two drivers mean two connections. The only test of the single
transaction ran over a test-only bridge that made blocking psycopg calls inside
`async` methods. Production had no path on which the guarantee held.

A second gap sat in the container. `Container.resolve` built a new object for
every request-scoped resolution. If the knowledge base and the audit sink each
asked for a connection, they got two, so registering them would have broken
DEC-0006 again.

## Decision

**One async SQLAlchemy connection per request. Every persistence adapter on
the request path enlists in it.**

- `KnowledgeBasePort.retrieve`, `CorpusIngestionPort.ingest`,
  `LearnerHistoryPort.read`, `PolicyArtifactPort.current` / `version` and
  `PolicyPublicationPort.publish` are `async`. Each adapter takes a
  `TransactionConnection`, the same domain ABC the audit sink takes.
- `OversightGatePort.evaluate` is `async`, because a gate loads the policy
  card on that connection. `LanguageModelPort.complete` is `async` so the
  local runtime call does not block the event loop; `revision()` stays
  synchronous.
- `TransactionConnection` gains `fetch_all`. Retrieval and policy history read
  through it, so they read on the turn's transaction.
- `SqlGateway`, `PsycopgGateway` and `PsycopgTransactionConnection` are
  removed. psycopg stays only where Alembic needs a synchronous driver.
- `Container.scope()` returns a `RequestScope`. Inside one scope, a
  `REQUEST`-lifetime type is built once. `Provide` opens one scope per HTTP
  request and keeps it on `request.state`. Two scopes share nothing
  request-scoped, so one learner's request never receives another's
  connection. `LifetimeValidation` is unchanged: a singleton still may not
  require a request-scoped type.
- `RequestConnection` is the registered `TransactionConnection`. Providers are
  synchronous and connecting is not, so it opens on first use. Commit, rollback
  and close before first use are no-ops. `SqlAlchemyUnitOfWork` closes it.
- The application connects as `tutor_app` (`ApplicationDatabaseUrl`), never as
  the migration owner.
- **Curation is not registered.** `CorpusIngestionPort` and
  `PolicyPublicationPort` have no provider, so a request cannot ingest a
  document or publish a policy version. They run on an operator path, each in
  a unit of work of its own.

## Consequences

**Positive.** DEC-0006's guarantee is now a property of the wiring rather than
of a test harness. `tests/integration/test_request_transaction.py` resolves
the policy, knowledge base, audit sink and unit of work from one scope. It
asserts that the unit of work hands the turn the scope's own connection, and
that a failed turn leaves no `turn_audit` row and no `turn_citation`.

**Positive.** One driver on the request path. No blocking I/O on the event
loop.

**Negative.** Persistence ports, `OversightGatePort.evaluate` and
`LanguageModelPort.complete` are `async`. `EmbeddingPort` stays synchronous:
it does no I/O. `LanguageModelPort.revision` stays synchronous: it returns
the stored SHA.

**Negative.** A request connection that is used but never reaches a unit of
work is not closed by the scope. On the request path every database access
goes through `UnitOfWorkPort.run`, which closes it. A read outside a unit of
work would hold a connection until garbage collection. That is a usage rule,
not a mechanism.

**Rejected: keep sync ports and make psycopg the only driver.** That would
mean rewriting the async audit sink to be synchronous and running every turn
in a worker thread. It also moves away from the async LangGraph backbone
(DEC-0004).

**Rejected: pass the connection into every port method.**
`retrieve(request, connection)` would put a persistence concern into the
signature of a retrieval capability, and every stub would carry it. The
request scope gives the same sharing without widening the port.
