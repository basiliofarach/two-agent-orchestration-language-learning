# 0001. Interface-first OOP; dependency injection as capability scoping

*Status:* Accepted · *Date:* 2026-09-18

*Amended:* 2026-09-22 — `TransactionConnection` added. It was an
adapter-side ABC; `TransactionalWork.run` now receives it, and a domain
signature cannot name an infrastructure type. `fetch_one` was added the same
day so an enlisted adapter can read one predecessor row without opening a
second connection.

*Amended:* 2026-10-05 ([DEC-0014](0014-one-request-connection.md)) —
`KnowledgeBasePort.retrieve`, `CorpusIngestionPort.ingest`,
`PolicyArtifactPort.current`/`version` and `PolicyPublicationPort.publish`
are async, and `TransactionConnection` gains `fetch_all`, so every
persistence port enlists in the request's one connection.

*Amended:* 2026-10-05 — `CorpusIngestionPort` and `PolicyPublicationPort`
added. Retrieval stays read-only and policy selection stays read-only.
Curation and publication are separate capabilities, so the agent that
retrieves cannot ingest, and the reader of the policy cannot publish a
version.

*Amended:* 2026-10-05 — `LearnerHistoryPort.read`, `OversightGatePort.evaluate`
and `LanguageModelPort.complete` are async. History and the gates read on
the request connection (DEC-0014); `complete` moves local model I/O off the
event loop. `revision()` stays synchronous: it returns the stored SHA.
`SourceSupportPort.verify` takes the retrieved snippets, because a
`SourceRef` has no passage text. The port set is otherwise unchanged.

*Amended:* 2026-10-06 — `LearnerHistoryPort.read(learner_id, requested)`
reads exactly the fields the turn requested, which the permission gate has
already judged; a requested field outside the allowlist raises. The gate
and the adapter are bound to one `HistoryFieldSet`, so they cannot disagree.
`AuditSinkPort` gains `head(session_id)`, a read of where the next record
attaches; it still has no update, delete or upsert. The database grant on
the history tables is column-level, so the application role cannot select
`learner.pseudonym` at all.

*Amended:* 2026-10-06 — `TutoringSessionPort.require_active(session_id, learner_id)`
reads the session on the enlisted connection before retrieval. A missing
session, a stopped session, or a session that belongs to another learner
raises, and the turn rolls back: one learner's history is not retrieved
into another's session, and no audit row is written there. The grant is
column-level — `id`, `learner_id`, and `stopped_at` only.

## Context

The prototype must produce *evidence* that Articles 10, 12, 14 and 15 are
satisfied, not merely behave correctly. Two properties follow:

1. **Substitutability.** Every scripted scenario (REQ-EVAL) must be replayable
   with a component swapped for a recording stub, or the evaluation cannot
   isolate which part of the pipeline produced a result.
2. **Least privilege, enforced by construction.** The Content Generation Agent
   must have *no code path* to the open web or to student-history fields beyond
   the documented minimum. A convention ("don't call that") is not evidence; an
   absent method is.

A common framing is that dependency injection is itself a security control. It
is not. DI is a wiring technique. What it provides here is the *enforcement
mechanism* for capability scoping: a collaborator receives a narrow port
instance, so out-of-scope operations are not merely discouraged but unavailable
on the object it holds. That is the claim this ADR makes, and the only security
claim it makes.

## Decision

Every collaborator is defined as an abstract base class (`abc.ABC`) before it is
implemented. Concrete classes are resolved and injected; no module-level
singletons, no service locators, no direct instantiation of a collaborator
inside a consumer.

Ports defined before implementation, each traced to the requirement it carries:

| Port | Responsibility | Scope boundary | Requirement |
| --- | --- | --- | --- |
| `PiiRedactionPort` | Redact PII from learner input in real time | Runs at the boundary; nothing downstream sees raw text | REQ-MINOR |
| `KnowledgeBasePort` | Retrieve vetted educational material | Vetted corpus only; no open web | REQ-KB, REQ-COMP |
| `CorpusIngestionPort` | Record source, version, and review status | Curation only; no retrieval; no open web; no default review status | REQ-KB |
| `LearnerHistoryPort` | Read minimal student-history fields | Read-only; field allowlist; reads only the requested fields; `read` is async | REQ-HISTORY |
| `TutoringSessionPort` | Confirm the session is this learner's and still open | Read-only; no open, stop, or reassignment; on the enlisted connection before retrieval | REQ-MINOR, REQ-AUDIT |
| `EmbeddingPort` | Text → vector | — | — |
| `LanguageModelPort` | Prompt → completion | No retriever; `complete` is async local-model I/O; `revision` is the pinned SHA | REQ-COMP |
| `PromptTemplatePort` | Build structured prompts; carry tone constraints | Fixed templates only | REQ-ACCURACY, REQ-MINOR |
| `GrammarCheckPort` | Grammar findings on the draft | Reports; does not edit the draft | REQ-COMP |
| `SafetyClassifierPort` | Flag unsafe or out-of-scope content | Reports; does not edit the draft | REQ-COMP |
| `SourceSupportPort` | Verify claims against retrieved snippets; flag unsupported spans | `verify(draft, snippets)`; does not drop spans | REQ-COMP, REQ-ACCURACY |
| `OversightGatePort` | One gate in the graph | Returns a verdict; `evaluate` is async; see DEC-0005 | REQ-GATES |
| `AuditSinkPort` | Append one immutable turn record and its gate rows | Append-only; `head` reads the chain position; no update/delete | REQ-AUDIT |
| `PolicyArtifactPort` | Supply the versioned machine-readable policy | Read-only; version logged per verdict | REQ-POLICY |
| `PolicyPublicationPort` | Append one policy version | No update or delete; a changed rule meaning needs a new id | REQ-POLICY |
| `ClockPort` | Current time | Injected for deterministic replay | — |
| `CipherPort` | Encrypt / decrypt bytes at the persistence boundary | Bytes only; no domain types; holds no store | REQ-MINOR, DEC-0012 |
| `UnitOfWorkPort` | One transaction for a turn's writes | Adapters enlist; they do not open a connection | REQ-AUDIT, DEC-0006 |
| `TransactionConnection` | Commit, rollback, close, execute, and fetch one row or all rows on the enlisted transaction | No connect, no engine, no cursor; a holder cannot open a second transaction | REQ-AUDIT, DEC-0006 |

`AuditSinkPort` exposes `append()` and no mutating method. `LearnerHistoryPort`
takes an explicit field allowlist at construction and selects only those
columns. `LanguageModelPort` is handed a rendered prompt and returns text —
it holds no retriever. Local model I/O is the adapter's, addressed by the
pinned SHA (DEC-0007), not a general HTTP client a prompt could aim at the
open web.

## Consequences

**Positive.** Each compliance claim maps to a named port, so the evidence pack
can cite an interface rather than prose. Scenarios replay deterministically
because `ClockPort` and `LanguageModelPort` are substitutable. The
least-privilege argument is structural and demonstrable at defence by showing
the class definition.

**Negative.** More files and indirection than a prototype of this size strictly
needs; navigating the code requires following the wiring. Accepted deliberately
— the indirection *is* part of the contribution.

**Risk.** "Interfaces everywhere" can decay into one-implementation ports that
add ceremony without benefit. Mitigation: a port is justified only if it has a
second implementation (a stub counts) or enforces a scope boundary. Ports
failing both tests get collapsed.

`CipherPort` was added to the table above by
[DEC-0012](0012-encryption-at-rest-by-default.md). The table is a registry, so
it is kept current as ports are introduced; the decision this record makes is
unchanged.

See also
[DEC-0011](0011-layer-roles-and-service-lifecycle.md) for authoring order,
the class / repo / service / router mapping, and the application-service
typestate chain. Those stage ABCs are not added to the port table above.
