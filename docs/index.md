# Documentation

This repository is the compliance-evidence prototype of a supervised two-agent
language-learning tutor (EU AI Act Articles 10, 12, 14 and 15). It is self-contained:
clone, read the files below, and implement. No accompanying paper is required.

The architecture was proposed in Farach, B. (2026), *Agentic Workflow Orchestration
and EU AI Act Compliance for a Minor-Centric Language-Learning AI Tutor* (literature
review). That document is background, not a dependency of this tree.

## Read order

1. [Requirements](requirements.md) — what the code must prove (`REQ-*`)
2. [Architecture](architecture/ARCHITECTURE.md) — how it is structured
3. [Decisions](decisions/README.md) — why this stack (DEC-0001 … DEC-0009)
4. [Implementation plan](architecture/IMPLEMENTATION-PLAN.md) — build order

Cite those identifiers from code, tests, and later decisions. Do not cite external
section, figure, or table numbers.

## Reading this site

After the repository is on GitHub with Pages set to **GitHub Actions**, this site is
at `https://<user>.github.io/<repo>/`. Set `site_url` (and `repo_url`) in
`zensical.toml` to that address.

Locally:

```
uvx --from zensical==0.0.62 zensical serve
```

The Markdown under `docs/` remains the source of truth. This site is a browser view
of those files, including Mermaid diagrams.
