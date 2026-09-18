# Requirements this prototype must prove

Normative claims the code and tests are evidence for. Implementers cite **these
identifiers** (and `ARCHITECTURE.md` / `docs/decisions/`), not an external paper.

AI Act article numbers, GDPR, and the OWASP Top 10 for LLM Applications are public
instruments and remain cited by name. Pedagogical effectiveness is out of scope.

Read order: this file → [ARCHITECTURE.md](architecture/ARCHITECTURE.md) →
[decisions](decisions/).

---

## REQ-COMP — Two-agent components

| Component | Role | Article |
|---|---|---|
| Data Retrieval Agent | Parses the learner query; retrieves vetted explanations and exercises from the curated knowledge base; fetches prior performance from the student-history schema; supplies provenance metadata with every snippet. | 10 |
| Content Generation Agent (one LLM) | Assembles retrieved context into a prompt; generates explanations and practice items; applies grammar, safety, and source-support checks; emits an AI-generated disclosure; refuses out-of-scope prompts. | 15 |
| Human tutor dashboard | Surfaces the live session, retrieved context, generated draft, and safety flags; provides approve, edit, override, and stop controls. Interventions are logged. | 14 |
| Audit log | Records the redacted learner prompt, retrieved context identifiers, model revision, decoding parameters, output before and after checks, safety flags, and human actions per turn. | 12 |

Process (system context): an adult tutor submits a learner query; PII is redacted at
the input boundary; the Data Retrieval Agent reads the curated knowledge base and the
minimal history schema; the Content Generation Agent (one local LLM) produces a draft;
grammar, safety, and source-support checks run; the tutor dashboard is the only path
to the learner (approve / edit / override / stop). Every step appends to the per-turn
audit log. The minor never operates the system.

Canonical drawing: [ARCHITECTURE.md §1](architecture/ARCHITECTURE.md#1-system-context).

---

## REQ-MAP — Compliance is distributed

Each selected obligation has a named locus. Compliance is not a documentation layer
on top of the pipeline.

| Article | Locus in this prototype |
|---|---|
| Art. 10 — Data governance | Curated knowledge base, student-history schema (allowlist), real-time PII redaction |
| Art. 12 — Record-keeping | Per-turn audit log and versioned policy artifact |
| Art. 14 — Human oversight | Four gates (REQ-GATES) and the tutor dashboard (REQ-DASH) |
| Art. 15 — Accuracy and robustness | Retrieval-constrained generation, output checks, refusal, prompt-injection hardening |

Canonical drawing: [ARCHITECTURE.md §9](architecture/ARCHITECTURE.md#9-compliance-mapping).

---

## REQ-KB — Knowledge-base governance

- Ingestion records **source**, **version**, and **review status** of each document.
- Retrieval is limited to vetted, reviewed sources. There is no open-web retrieval
  method.
- Source metadata travels with every retrieved snippet.

---

## REQ-HISTORY — Minimal student-history schema

- History is read-only and bound to an explicit field allowlist at construction.
- Only fields needed to manage next-item selection are admitted.
- Periodic review of retrieval and generation outcomes across learner cohorts is a
  human activity; the architecture supplies the query, not an automated verdict.

---

## REQ-MINOR — Minor-centric constraints

| Requirement | Implementation |
|---|---|
| Age-appropriate transparency | AI-generated disclosure on every output |
| Safety and well-being | Content filter and tone constraint on the Content Agent; refusal for out-of-scope prompts; routing to the tutor when safety flags fire |
| Data protection by design | Minimal history schema (REQ-HISTORY); real-time PII redaction at the input boundary; retention policy aligned with GDPR (`learner.retain_until`) |
| Non-discrimination | Periodic cohort review of retrieval and generation outcomes; bias controls in the curated knowledge base (REQ-KB) |

---

## REQ-AUDIT — Per-turn log schema

Each turn records:

- the learner prompt, **redacted** at the input boundary (not hashed out of the log),
  with the categories redacted stored beside it
- identifiers of retrieved context documents
- model revision (pinned commit SHA) and decoding parameters
- generated output **before and after** any grammar or safety pass
- safety flags raised
- any human action at the tutor dashboard
- policy version against which the turn was checked
- a hash chaining this record to its predecessor

The prompt is stored, not digested. Data protection is discharged by redaction and
the history allowlist (REQ-MINOR, REQ-HISTORY), not by removing the prompt from the
log. Output before and after checks are both stored; `human_action.edited_output`
is a third state when the tutor edits.

Append-only: the sink exposes `append()` and no update or delete (DEC-0002,
DEC-0006).

---

## REQ-POLICY — Versioned policy artifact

A machine-readable, versioned deployment artifact encodes allowed and denied
actions, escalation requirements, evidentiary logging, and mappings to the AI Act.
Its version is written into every audit record and every gate verdict
(`policy_rule_id`), so the log records not only what was generated but **against
which rule version it was checked**. The trail is exportable.

---

## REQ-GATES — Four oversight gates

Gates share one interface (`OversightGatePort`) and are invoked at **different
points** in the orchestration graph (DEC-0005). There is no single-pass
`chain.run()` over a finished turn.

| Gate | Position | Trigger |
|---|---|---|
| Context and permission | **Before retrieval** | Requested operation out of the agent's scope (for example, unvetted sources would be needed, or history fields outside the necessary minimum would be read) |
| Conflict and ambiguity | **After retrieval, before generation** | Retrieval result empty, contradictory, or below a confidence threshold |
| Sensitivity and high-stakes | **After generation** | Output touches a flagged category (for example assessed proficiency, or content with safety markers) |
| Drift and anomaly | **After generation** | Retrieval or generation behaviour leaves the expected envelope |

A non-pass verdict (`pause` or `stop`) routes to human review and **does not**
continue to the next pipeline stage. A permission `stop` means retrieval does not
run. Ordering is structural: permission resolves before retrieval, conflict before
generation, and the human stop before any material reaches the learner. Gates that
are advisory rather than enforced do not support the claim that the obligations are
structural.

This prototype scopes drift to the **session** ([ARCHITECTURE.md §13](architecture/ARCHITECTURE.md#13-deliberate-limitations)).

Canonical drawing: [ARCHITECTURE.md §8](architecture/ARCHITECTURE.md#8-runtime-view).

---

## REQ-ACCURACY — Generation controls

- The Content Agent does not act on free-form learner input directly. It assembles
  retrieved context and the learning task into a **fixed prompt template** (role,
  retrieved context, target proficiency, output structure, tone). Prompt formulation
  is an accuracy control; `template_version()` is logged.
- Hallucination control: key claims in a generated explanation are verified against
  retrieved sources; **unsupported spans are flagged for human review**, not silently
  removed.
- Refusal for out-of-scope or inappropriate prompts.
- `LanguageModelPort` has no retriever and no HTTP client (OWASP LLM tool-scoping).

---

## REQ-DASH — Tutor dashboard

The only user is an adult tutor. The dashboard surfaces:

- live learner prompt
- retrieved context
- generated draft
- visible safety flags
- approve / edit / override / stop

`stop` terminates the session and preserves state. Every tutor action produces an
audit entry tied to the per-turn record. No action is offered that the backend cannot
log. Route tree: DEC-0008.

---

## REQ-EVAL — Scripted scenarios

Eight tutor-side cases, each an integration test:

1. Grammar explanation request
2. Exercise-generation request
3. Learner-history personalisation
4. Ambiguous or low-context prompt
5. Out-of-scope prompt
6. Safety-sensitive prompt
7. Noisy prompt (language errors)
8. Prompt-injection attempt

Rubric: correctness, clarity, source support, age-appropriateness, and safety.
LLM-as-a-judge is a secondary signal; disagreements are resolved by humans.
Never assert on a real model's generated text in automated tests — stub
`LanguageModelPort` and assert on pipeline behaviour.

---

## REQ-FIELD — Evaluation protocol

Field testing is gated on a usable dashboard. Roughly five to eight adult tutors
(not minors) run guided sessions. Two passes: an early formative round and a later
confirmatory round after disruptive issues are corrected.

Metrics are first recorded on synthetic inputs, then re-applied to tutor-sourced
material. A metric is treated as validated only when it has held up on tutor-sourced
inputs; drift between the two is reported, not smoothed over.
