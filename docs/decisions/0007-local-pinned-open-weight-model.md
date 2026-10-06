# 0007. Local, pinned open-weight model behind a provider port

*Status:* Accepted · *Date:* 2026-09-18

*Amended:* 2026-10-06 — `/api/tags` reports a *manifest* digest, not the
weights. The adapter resolves the model name whose modelfile `FROM` line
names the pinned weights blob (`/api/show`), generates, then reads that
name's weights again; a name repointed in between fails the turn. The pin is
located through `MODEL_PIN_PATH`, not inferred from the package's install
location. The residual gap: Ollama generates by name, so the check brackets
generation rather than binding it.

*Amended:* 2026-10-06 — `OLLAMA_BASE_URL` is accepted only when its host is
loopback (`localhost`, `127.0.0.0/8`, or `::1`). A hosted URL is rejected
when settings load and again by the endpoint. The client does not follow
redirects and ignores `HTTP_PROXY`/`HTTPS_PROXY`: urllib does not exempt
loopback from a proxy, so an environment proxy would otherwise receive the
prompt. A comparison run against a hosted model remains a second
`LanguageModelPort` adapter, not a setting on this one.

## Context

The Content Generation Agent needs one LLM. Constraints:

- **Reproducibility.** An examiner must be able to re-run the evaluation. A
  hosted model updated silently behind a stable alias makes that impossible.
- **Data protection.** Learner data — including minimal history for minors — is
  processed at generation time. Article 10 and GDPR favour not transmitting it.
- **Platform risk.** Nvidia agreed to acquire Hugging Face on 2026-09-02 for
  ~$12.9bn, with closing expected in H1 2027 — inside this project's timeline.
  Nvidia has stated the platform stays open and its compute is not required, but
  terms could move mid-project.
- **Hardware.** Development machine is an Apple M3 with 16 GB unified memory,
  capping comfortable local inference at roughly a Q4-quantised 8B model.

Long context is not a requirement: the Content Agent receives a few retrieved
snippets plus minimal history, on the order of thousands of tokens.

## Decision

**Qwen3-8B (Apache 2.0), run locally via Ollama**, reached only through
`LanguageModelPort` (DEC-0001).

The model is pinned by **commit SHA, never by tag**, and that SHA is written
into every `TurnAuditRecord` (DEC-0002). A tag can be repointed; a SHA cannot.
The name sent to the local runtime is whichever installed model digest
contains that SHA. The audit log therefore states exactly which weights
produced each output. `complete` is async (DEC-0014); `revision()` does not
contact the runtime.

## Consequences

**Positive.** Learner data never leaves the machine — a
data-protection-by-design argument that is structural rather than contractual,
and stronger than any hosted option can offer. No credits, quotas or rate
limits, so the full scenario suite can be re-run freely. Apache 2.0 imposes no
usage restriction. Pinning by SHA makes runs reproducible. Platform risk is
sidestepped entirely: a terms change post-acquisition cannot affect
already-downloaded weights.

**Negative.** An 8B model produces weaker explanations than a frontier model, so
rubric scores (correctness, clarity, age-appropriateness) will sit below what a
larger model would achieve. This is a stated limitation, not a defect — the work
evaluates the *compliance architecture*, not model quality, and REQ-ACCURACY
bounds accuracy by retrieved-context quality rather than raw model capability.

**Mitigation.** Because access is behind `LanguageModelPort`, a larger hosted
model can be added as a second adapter for a comparison run without touching the
pipeline. If the evaluation would benefit from that contrast, it is an
afternoon's work.

**Operational note.** Record the Ollama version alongside the model SHA; the
runtime affects quantisation and sampling behaviour and is part of
reproducibility.
