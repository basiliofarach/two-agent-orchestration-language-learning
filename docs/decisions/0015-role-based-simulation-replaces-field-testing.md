# 0015. Role-based simulation replaces field testing; no LLM judge

*Status:* Accepted · *Date:* 2026-11-03

*Amended:* 2026-11-03
— Role-model weights (D-2) are not chosen here. No digest is invented.
`OllamaRoleModel` and `RoleModelPin` refuse to start when the role-model
weights SHA equals the system weights SHA in `config/runtime.toml`
(`[model] weights_sha`). The `[role_model]` table is written when a model
from a different family is chosen, before the first frozen build.

*Amended:* 2026-11-03
([architecture/SIMULATION.md §9.2](../architecture/SIMULATION.md#92-expectation-table-for-policy-prototype-2))
— Every label records its basis:

- `construction`: guaranteed by what was planted.
- `requirement`: what a correct system must do, though whether it does can
  depend on the model's output.
- `output_dependent`: the outcome depends on what the draft says.

Under the real model, an `output_dependent` case (I6, assessed proficiency)
is reported as an observed rate, outside headline accuracy. No judge is
brought in to resolve it.

Supersedes REQ-FIELD: the field-testing protocol and its
synthetic-to-tutor-sourced validation step. Also supersedes the
LLM-as-a-judge sentence of REQ-EVAL. The eight REQ-EVAL cases and the five
rubric criteria still stand.

Amends [DEC-0001](0001-interface-first-oop-di-capability-scoping.md) by
adding three harness ports. Every architecture decision still stands:

- the pipeline
- the four gates and their positions
- the audit log
- the dashboard, still designed for an adult tutor as its only user

[DEC-0016](0016-evaluation-dataset-is-the-testing-data-set.md) governs the
data this simulation runs on.

## Context

REQ-FIELD planned field testing with five to eight adult tutors in two
passes. A metric counted as validated only once it held on tutor-sourced
inputs. REQ-EVAL scored eight scripted cases on a five-criterion rubric.
It used an LLM-as-a-judge as a secondary signal, with humans resolving
disagreements.

The main instructor declined to take part. **No tutors and no pupils will
take part in the evaluation.** That removes two things the old protocol
depended on:

1. The validation step of REQ-FIELD has no input. There will be no
   tutor-sourced material to re-apply the metrics to.
2. The LLM judge has no human scores to be calibrated against.
   Calibration was the only condition under which REQ-EVAL admitted it.

The supervisor suggested two things: stress testing the system with AI, and
an LLM judge "in process". The author proposed that AI play the roles of the
tutor and the students. The supervisor agreed to the roles. The judge is not
adopted; see Rejected below.

What already exists shapes the decision:

- **The rubric reads no prose.** `tutor_core/application/evaluation/rubric.py`
  compares a `ScenarioCase` (expected) with a `ScenarioObservation` (read
  from the API).
- **The judge was never built.** `RubricScore.judge_signal` is a label with
  nothing producing it.
- **Hand-written cases flatter the classifier.** They are written against the
  classifier, and the rubric's second review found that a case written to hit
  a pattern hits it. The paraphrase twins exist because of that.
- **Detection is weak by design.** The safety classifier is a pattern list
  ([ARCHITECTURE §13](../architecture/ARCHITECTURE.md#13-deliberate-limitations)).

## Decision

**Role agents stand in for the humans. Every case's expected outcome is fixed
when the case is built. No language model scores anything.**

### Roles

- **Virtual pupils** are driven by a language model and conditioned on a
  persona card: a system prompt plus few-shot examples (DEC-0016). They write
  the learner request.
- **Tutor roles** relay that request and act on held turns:

  | Role | Driven by | On a held turn |
  | --- | --- | --- |
  | T1 Diligent | Language model; sees only what the tutor API returns | Approve, edit, override or stop |
  | T2 Complacent | Script | Approve whenever the backend allows; otherwise resubmit the draft unchanged as `edit` |
  | T3 Absent | Script | Nothing |
  | T4 Stopper | Script | `stop` at a planned turn |

  The scripted roles bound the range of oversight behaviour. T1 exercises
  natural-language edits.

- **The relay is a deterministic pass-through.** The tutor role submits the
  pupil's text unchanged. A model that paraphrased requests could delete a
  planted payload and invalidate the label.

### Oracle

- The expected outcome is derived from the policy version the run uses
  (REQ-POLICY). It has two levels:
  - The **outcome class** is the pass criterion: released for approval,
    held, refused, or stopped before retrieval.
  - The **halting gate** is diagnostic. It is reported as one of: right
    reason, wrong reason, or missed.
- **A label that depends on content rests on a payload planted verbatim**
  (DEC-0016). The construction check is an exact substring match. A failing
  case is regenerated up to three times, then discarded and logged. The
  discard rate per persona is reported.
- Any planted personal data or canary string listed in `must_not_contain`
  is checked by exact match against everything the tutor API exposes for
  the turn: the stored prompt, the retrieved context, the draft and the
  released text. The model prompt is built only from `RedactedText`
  ([ARCHITECTURE §4.1](../architecture/ARCHITECTURE.md#41-input-boundary-and-retrieval)),
  so that boundary is a typed one, already covered by integration tests.
- **A noisy twin is a metamorphic case.** It must reach the same outcome as
  its clean base case.
- **Level fit** is measured by CEFR-J coverage (DEC-0016). It is reported as a
  distribution, not a pass mark.

### No judge

- **No language model scores a system output, a pupil utterance, or a
  tutor-role decision.** T1's decisions are stimuli. The evaluation measures
  how the system handles each decision, not whether T1 decided well.
- `RubricScore.judge_signal` is removed. `EvaluationReport.label` becomes
  `simulated:<dataset_version>`. The five rubric criteria keep their current
  deterministic definitions.
- The pedagogical quality of an explanation is not scored. It was already
  out of scope, per the preamble of `requirements.md`.

### Runs

- **Tier 1, open loop.** Stimuli are generated once, checked, and frozen
  (DEC-0016). Every reported rate comes from this tier, with a 95% Wilson
  interval per stratum.
- **Tier 2, closed loop.** Episodes of at most eight turns. The pupil reads
  what was released and replies. This tier reports invariants only.
- **Automated tests stay deterministic** (rule 7). Unit and integration tests
  stub both `RoleModelPort` and `LanguageModelPort`. A campaign against real
  models is an experiment: its results are reported, never asserted.

### Harness

- The harness is a new workspace member, `tutor-sim`. It drives the tutor API
  over HTTP, as a tutor's browser does.
- It imports no `tutor_core` or `tutor_api` module. An import-linter contract
  enforces this. A harness that called the graph directly could take a path
  no tutor can, and the evidence would no longer be about the deployed
  system.
- It is first-party code, so rules 1–9 apply: ABCs first, Pydantic only,
  injected `ClockPort`, both test levels.
- Three ports are added to DEC-0001's registry:

  | Port | Responsibility | Scope boundary | Second implementation |
  | --- | --- | --- | --- |
  | `RoleModelPort` | Persona-conditioned completion for a pupil or tutor role | Harness only; never registered in the system container; holds no tutor-API client; pinned digest recorded per stimulus | Scripted stub |
  | `TutorClientPort` | Submit a turn; read its outcome; act on a held turn; stop a session | The tutor API's HTTP surface only; nothing the dashboard cannot do | In-process ASGI transport in tests; HTTP in campaigns |
  | `TutorRolePort` | Choose the dashboard action for a held turn | Sees only the turn view the API returns; returns approve, edit, override, stop, or none | T1–T4 |

- **Role model.** The role agents run on an open-weight model from a
  different family than Qwen3-8B. It is served locally by Ollama, pinned by
  digest as in DEC-0007, and recorded on every stimulus and in the run
  manifest. Using the system's own model would let stimuli and system share
  blind spots, and would invite self-preference. The specific model is
  recorded by amendment to this record before the first frozen build.

## Consequences

**Positive.** Evaluation no longer depends on recruiting anyone. The
implementation plan named recruitment lead time as the most likely schedule
slip, and that risk is gone. No personal data of tutors or minors is
processed for evaluation.

**Positive.** Coverage grows and becomes independently checkable:

- Roughly 920 frozen single-turn cases replace eight hand-written ones.
- New categories that the eight cases never reached: indirect injection
  through retrieved material, disclosure of personal data, child-safety
  risks, and history probing.
- Every score can be recomputed from the frozen stimuli and the audit log,
  by anyone, without a model.

**Positive.** The scripted tutor roles make two oversight properties
measurable:

- T2 exposes the residual risk when oversight degrades into automation bias
  (Art. 14(4)(b)). The `edit` path must still refuse high-severity flags.
- T3 tests the fail-safe: a held turn never reaches the learner unseen.

**Negative.** The evidence shows that the oversight controls exist, are
enforced and are logged. It does not show what Art. 14(4)(a)–(c) asks of
people: that an overseer understands the system, stays aware of automation
bias, and reads its output correctly. That is stated as a limitation, not
argued around. The accessibility evidence shows the controls are operable,
not that they are understood.

**Negative.** Simulated pupils are known to be too competent and to drift.
The evidence therefore concerns the system's response to the stimuli, not
the behaviour of real minors. Three mitigations limit how much any label
relies on persona fidelity:

- planted payloads, so labels do not depend on the role being played well
- a CEFR-J profile of the pupils' own utterances
- the eight-turn cap on closed-loop episodes

**Negative.** Detection rates on held-out payloads are expected to be low,
because the classifier is a pattern list. A low rate is a finding about the
classifier, not a failure of the method.

**Negative.** Until the harness lands, the code still carries the old
vocabulary:

- `judge_signal`
- the `synthetic-only` and `tutor-sourced` labels
- `Cited("REQ-FIELD", …)` in the Article 15 exhibit

REQ-FIELD stays in `requirements.md` as a superseded entry so those
citations still resolve. They change together in Phase 11 of the
implementation plan.

**Rejected: LLM-as-a-judge as a secondary signal.** This was the supervisor's
suggestion, and it fails on four counts:

1. Judges show position, verbosity and self-preference biases (Zheng et al.
   2023; Wang et al. 2024; Panickssery et al. 2024). With the system, the
   role agents and a judge all being language models, self-preference
   becomes a confound.
2. Agreement with human judges varies by property and must be validated
   before use (Bavaresco et al. 2025). Without tutors, there is nothing to
   validate against.
3. A judge's score is itself a stochastic model output. It would need its
   own pin, log and validation before it could support a declared accuracy
   metric (Art. 15(3)) or a traceable record (Art. 12).
4. Every link in the evidence chain would be a language model.

**Rejected: the author as the sole rubric rater.** One rater is neither
independent nor blind to the system. The author's role is limited to a
manipulation check on a stratified sample of benign cases, whose label no
payload guarantees. That check is reported as single-annotator.

**Rejected: a tutor model that rewrites the request before submitting it.**
That would be more natural, but it breaks label-by-construction.

**Rejected: Qwen3-8B for the role agents.** Stimuli and system would share
blind spots.

**Rejected: hand-written cases only.** They are written against the
classifier and pass it. The paraphrase twins showed the effect at a scale of
three.

**Rejected: closed-loop conversations as the primary measure.** They are not
reproducible, and their labels would depend on persona fidelity. They are
kept as Tier 2, for invariants only.
