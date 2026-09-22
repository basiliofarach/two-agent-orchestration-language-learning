# Documentation

A compliance-evidence prototype of a supervised two-agent language-learning
tutor for minor learners, built to demonstrate compliance-by-design with
EU AI Act Articles 10, 12, 14 and 15. The code is graded as evidence, not only
as working software: every rule in the repository backs a numbered requirement.
{ .lead }

The tree is self-contained. The four documents below are read in order;
no accompanying paper is required.

## Read order

[Requirements](requirements.md)
:   What the code must prove, as numbered `REQ-*` claims traceable to the
    Articles they satisfy. Every rule in `CLAUDE.md` backs one of these.

[Architecture](architecture/ARCHITECTURE.md)
:   Ports, adapters, the LangGraph backbone, and where each of the four
    oversight gates sits in the orchestration graph.

[Decisions](decisions/README.md)
:   Twelve MADR records, DEC-0001 to DEC-0012 — what was chosen, what was
    rejected, and the reasoning. Immutable once accepted.

[Implementation plan](architecture/IMPLEMENTATION-PLAN.md)
:   The sequence the prototype is built in, with the authoring order that the
    interface-first rule requires.

Cite those identifiers from code, tests, and later decisions. Do not cite
external section, figure, or table numbers.

## Regulatory scope

| Article | Obligation | Where it is argued |
| --- | --- | --- |
| Art. 10 | Data governance and minimisation | [DEC-0002](decisions/0002-pydantic-basemodel-only.md), [DEC-0006](decisions/0006-postgres-pgvector-single-store.md), [DEC-0012](decisions/0012-encryption-at-rest-by-default.md) |
| Art. 12 | Logging and traceability | [DEC-0004](decisions/0004-langgraph-orchestration-backbone.md), [DEC-0010](decisions/0010-mutable-turnstate-graph-wrapper.md), [DEC-0012](decisions/0012-encryption-at-rest-by-default.md) |
| Art. 14 | Human oversight | [DEC-0005](decisions/0005-oversight-gates-chain-of-responsibility.md), [DEC-0008](decisions/0008-frontend-react-router-v8-shadcn.md) |
| Art. 15 | Accuracy and robustness | [DEC-0001](decisions/0001-interface-first-oop-di-capability-scoping.md), [DEC-0007](decisions/0007-local-pinned-open-weight-model.md), [DEC-0011](decisions/0011-layer-roles-and-service-lifecycle.md) |

!!! note "Encryption is a GDPR measure, not an AI Act control"

    Encryption at rest ([DEC-0012](decisions/0012-encryption-at-rest-by-default.md))
    is a GDPR Article 32 measure under a risk test. Do not cite AI Act
    Article 15 as its legal basis.

## Provenance

The architecture was proposed in Farach, B. (2026), *Agentic Workflow
Orchestration and EU AI Act Compliance for a Minor-Centric Language-Learning AI
Tutor* (literature review). That document is background, not a dependency of
this tree.

## Building this site

=== "Locally"

    ```text
    uvx --from zensical==0.0.62 zensical serve
    ```

=== "Published"

    Pushing to `main` publishes this site through
    [`.github/workflows/docs.yml`](https://github.com/basiliofarach/two-agent-orchestration-language-learning/blob/main/.github/workflows/docs.yml).
    It requires **Settings → Pages → Source: GitHub Actions** once, after
    which the site is at
    <https://basiliofarach.github.io/two-agent-orchestration-language-learning/>.

The Markdown under `docs/` remains the source of truth. This site is a browser
view of those files, including Mermaid diagrams.
