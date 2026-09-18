# 0003. Python toolchain: uv, FastAPI, wireup

*Status:* Accepted · *Date:* 2026-09-18

## Context

The backend hosts the two agents, the gate chain, the audit sink and the
dashboard API. DEC-0001 requires constructor injection into domain services with
enforced lifetimes; DEC-0002 requires Pydantic throughout.

## Decision

**uv 0.12.5** for packaging. PEP 621 `pyproject.toml`, a committed
cross-platform `uv.lock`, and a workspace splitting `tutor-core` (domain, ports,
gates) from `tutor-api` (FastAPI adapter). The lockfile is part of the evidence
pack: reproducing an evaluation run means `uv sync` at a known commit.

**FastAPI** for HTTP. Pydantic-native, so DEC-0002 models are request/response
schemas without translation.

**wireup 2.12** for the domain object graph, with FastAPI's `Depends()` retained
only at the HTTP boundary.

The split matters. `Depends()` is request-scoped and function-oriented; it does
not constructor-inject domain services, and FastAPI cannot detect a singleton
that has captured request-scoped state. wireup validates lifetimes **at
startup** and fails fast on scope leakage. Concretely: a
`ContentGenerationAgent` registered as a singleton that accidentally retains a
`LearnerHistoryPort` bound to one learner's session would leak one minor's
history into another's. wireup refuses to start. That is a data-protection
control with a mechanical guarantee, citable as such.

## Consequences

**Positive.** Scope leakage — the highest-severity plausible defect in this
system — becomes a startup failure rather than a runtime incident. Lockfile plus
pinned model revision (DEC-0007) makes evaluation runs reproducible.

**Negative.** Two DI mechanisms in one codebase; a contributor must know which
applies where. Mitigated by the rule: *anything below the router is wireup, the
router signature is `Depends`.*

**Rejected — Litestar.** Class-based controllers and first-class DI fit the OOP
mandate more natively. Rejected for ecosystem size: under time pressure,
FastAPI's documentation and community volume outweigh the idiomatic gain, and
wireup recovers most of the DI ergonomics.
