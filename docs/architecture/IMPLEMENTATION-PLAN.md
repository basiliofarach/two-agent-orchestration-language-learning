# Implementation plan — order of creation

Build sequence for the architecture in [ARCHITECTURE.md](ARCHITECTURE.md).
Requirements: [../requirements.md](../requirements.md).

**Definition of done, every phase:** unit tests and integration tests both exist
and pass. A phase with working code and one test level is not complete.

**Ordering principle.** The audit spine is built *before* the agents, not after.
Everything in the system writes to it, it is the Article 12 claim in its
entirety, and retrofitting logging onto a working pipeline is how gaps get
introduced. Likewise ports precede adapters — the interface-first rule is a
build order, not only a style.

**Gates are built with the stage they guard, not in one batch.** REQ-GATES and
DEC-0005: gates that are advisory rather than enforced do not support the
structural claim. A gate therefore ships with the pipeline stage it precedes:
the permission gate with retrieval, the conflict gate before generation,
sensitivity and drift after it. There is no phase in which all four gates are
added at once.

---

## Phase 0 — Scaffold

uv workspace with `tutor-core` and `tutor-api` members; committed `uv.lock`.
pnpm + Vite + React Router v8 app. `tutor-api/docker-compose.yml` for
PostgreSQL 17 + pgvector. Ollama installed, model pulled and its SHA recorded.

Enforcement wired now, before any code exists to violate it:

- `pytest --cov --cov-fail-under=<threshold>` in CI
- pre-commit: ruff, mypy strict on `tutor-core`
- a ruff rule banning `dataclasses` imports, so DEC-0002 is mechanical rather
  than remembered

*Done when:* `uv sync` reproduces the environment, the database starts, the
model answers a smoke prompt, and CI fails on an untested commit.

## Phase 1 — Domain skeleton

Every Pydantic model in `domain/models/` and every port in `domain/ports/` as an
`abc.ABC`. Stage-handler ABCs and the typestate wrappers in
`application/services/service.py` (DEC-0011) — `prepare` / `execute` /
`finalise` on *different types*, no use-case body yet. No port
implementations. `tutor-core` imports nothing but stdlib and Pydantic.

*Done when:* models are unit tested for validation, `extra="forbid"` raising on
undeclared fields, `frozen=True` raising on mutation **of audit and evidence
records**, and `TurnState` accepting field assignment (DEC-0010).
`ApplicationService` exposes only `prepare`; `Prepared` only `execute`;
`Executed` only `finalise`. A handler ABC missing `run` cannot be
instantiated. An import-linter check fails the build if `domain` imports any
framework.

*Why first:* everything downstream is written against these signatures, and
DEC-0001 requires the abstraction before the implementation.

## Phase 2 — Audit spine

The turn row is written once. Generation columns are null when the model did
not run, and gate rows and citations commit with that row. A tutor action is
a later insert. The sequence is
[ARCHITECTURE.md §8](ARCHITECTURE.md#8-runtime-view).

`AuditSinkPort` + `PostgresAuditSink`. Migrations for `turn_audit` and
`gate_evaluation`, the `BEFORE UPDATE OR DELETE` trigger, and an application
role granted `INSERT`/`SELECT` only. Hash chaining over records.

`CipherPort` ships here, ahead of the first migration, so the schema is born
encrypted rather than retrofitted (DEC-0012). The same migration creates the
`ciphertext` domain, the `protected_column_exemption` registry seeded from
DEC-0012, and the `ddl_command_end` event trigger that rejects a plaintext
column on a protected table.

*Done when:* integration tests prove `UPDATE` and `DELETE` raise at the database
level, the chain detects a tampered or excised record, and a rolled-back
transaction leaves no partial audit row. For DEC-0012: reading `turn_audit`
directly as the application role returns ciphertext for every encrypted column;
`ALTER TABLE turn_audit ADD COLUMN note text` raises from the event trigger;
the same statement succeeds once the column is registered as an exemption; a
turn replays byte-identically across a key rotation; and the hash chain still
detects tampering with encryption enabled.

*Why second:* it is the Article 12 evidence, and every later phase writes to it.

## Phase 3 — Permission gate and retrieval

`PiiRedactionPort` at the input boundary. KB ingestion recording source, version
and review status per REQ-KB. `EmbeddingPort` + local embeddings,
`PgVectorKnowledgeBase`, `LearnerHistoryPort` with its field allowlist.
`DataRetrievalAgent`.

**`ContextPermissionGate` ships here**, not with the other gates. REQ-GATES
places it before retrieval, so it is built with the thing it guards.

*Done when:* the permission gate runs before any retrieval call and a `stop`
verdict provably prevents retrieval from executing at all; no unredacted learner
text exists downstream of the boundary; unreviewed documents are provably
unretrievable; retrieval returns source metadata with every snippet; a history
read outside the allowlist raises; retrieval and its audit record commit in one
transaction.

## Phase 4 — Conflict gate, generation and output checks

`ConflictAmbiguityGate` first — REQ-GATES places it between retrieval and
generation, so it is built before the generation it gates.

`PromptTemplatePort` with fixed templates encoding role, retrieved context,
target proficiency, output structure and tone (REQ-ACCURACY).
`OllamaLanguageModel` exposing `revision`. `ContentGenerationAgent`.

All three Article 15 output checks, per REQ-COMP — not safety alone:

- `SafetyClassifierPort`
- `GrammarCheckPort`
- `SourceSupportPort` — the hallucination control REQ-ACCURACY argues for; flags
  unsupported spans for human review rather than removing them

Plus the AI-generated disclosure on every output, and refusal for out-of-scope
prompts (REQ-COMP, REQ-MINOR).

*Done when:* a conflict-gate `pause` provably prevents the model from being
invoked; the model revision and template version appear in every audit record;
both `output_before_checks` and `output_after_checks` are recorded (REQ-AUDIT);
every output carries a disclosure; unsupported spans are surfaced rather than
silently dropped; a stubbed `LanguageModelPort` drives deterministic tests.

## Phase 5 — Post-generation gates and the registry

`SensitivityHighStakesGate` and `DriftAnomalyGate` — the two gates that
genuinely do inspect a draft, so they come after generation exists. Plus the
ordered `GateRegistry` that declares all four in sequence.

*Done when:* each gate is unit tested for `pass`, `pause` and `stop` in
isolation; a gate attempting to mutate its input fails a test; every gate with
sufficient input appends a `gate_evaluation` row whether or not it fired, and a
gate not reached is recorded as `not_evaluated` with its reason; the registry's
declared order matches REQ-GATES and [ARCHITECTURE.md
§8](ARCHITECTURE.md#8-runtime-view).

## Phase 6 — Orchestration

LangGraph graph in the order REQ-GATES and [ARCHITECTURE.md
§8](ARCHITECTURE.md#8-runtime-view) require:

```text
permission gate → retrieval → conflict gate → generation + checks
  → sensitivity gate → drift gate → tutor approval
```

Graph state is an application-layer wrapper over a mutable Pydantic
`TurnState`; nodes accumulate fields on the live turn (DEC-0010). Gates still
do not mutate the turn. Checkpointer configured; `interrupt` on `pause` and
`stop`. Nodes stay thin — resolve port, delegate, return.

*Done when:* an integration test drives a full turn with a stubbed model; **no
graph path reaches retrieval without the permission gate, or generation without
the conflict gate**; a non-pass verdict provably halts the pipeline rather than
falling through to the next stage; a `TurnAuditRecord` is a frozen snapshot
distinct from the live turn; a recorded turn replays from the audit log and
reproduces its output; checkpoint identifiers resolve to their log entries.

*Milestone:* end-to-end backend. Everything before this is components; this is
the prototype.

## Phase 7 — API

Before this phase registers a provider that holds one learner's data, startup
validation rejects cycles and duplicate registrations, and one request reuses
a single request-scoped instance. The direct singleton-to-request check
already exists ([DEC-0013](../decisions/0013-first-party-composition-root.md)).

FastAPI routers for sessions and audit. `container.py` provider registration
(DEC-0013). `Depends()` only in router signatures, through `Provide(T)`.

*Done when:* the container resolves and `LifetimeValidation` passes at startup —
the test that catches a singleton holding request-scoped learner state, and
raises `ScopeLeak` before the application serves traffic.

## Phase 8 — Tutor dashboard

Flat routes per DEC-0008. Live prompt, retrieved context, generated draft,
visible safety flags, gate timeline, and approve / edit / override / stop. Audit
log viewer.

*Done when:* every control produces a logged intervention tied to its per-turn
record; `stop` terminates and preserves state; no action is offered that the
backend cannot log; controls are keyboard reachable with visible focus.

*Milestone:* demonstrable system. Screenshots from here are Article 14 evidence.

## Phase 9 — Evaluation harness

Eight scripted scenarios as integration tests (REQ-EVAL): grammar explanation,
exercise generation, history personalisation, ambiguous prompt, out-of-scope
prompt, safety-sensitive prompt, noisy prompt, prompt-injection attempt.

Out-of-scope refusal and safety-sensitive routing exercise different gates; a
noisy prompt tests robustness while an injection attempt tests tool scoping.
Evidence is reported against these eight cases.

Rubric scoring for correctness, clarity, source support, age-appropriateness and
safety. LLM-as-a-judge as secondary signal, with human resolution of
disagreements.

*Done when:* the suite runs headless and emits scores; the injection attempt is
provably refused and flagged; results are reproducible from the lockfile and
pinned SHA.

## Phase 10 — Evidence pack

Exporter producing: curation checklist and source metadata (Art. 10), audit log
excerpts with verified hash chain (Art. 12), dashboard exports and intervention
log (Art. 14), accuracy/refusal/robustness results (Art. 15).

*Done when:* the pack regenerates from a clean checkout with one command.

---

## Sequencing notes

**Critical path:** 0 → 1 → 2 → 3 → 4 → 5 → 6. Phases 7–8 can overlap with 9 once
the backend is end-to-end at phase 6.

**Frontend timing.** The dashboard can start any time after phase 2 against
fixtures, but its audit viewer is not meaningful until real records exist.

**Field testing** (REQ-FIELD) is gated on phase 8 and tracked as FIELD-01.
Recruit the 5–8 tutors during phases 6–7 so the formative round starts as soon
as the dashboard is usable — that recruitment lead time is the most common
schedule slip in a project of this shape.

**Synthetic-to-validated metrics** (REQ-FIELD) spans phases 9 and field testing:
record the synthetic baseline at phase 9 so any later movement is attributable
to the change in input rather than to a change in the system.
