# 0013. First-party composition root; FastAPI `Depends()` is the only DI library

*Status:* Accepted · *Date:* 2026-09-22

Supersedes the wireup clause of
[DEC-0003](0003-python-toolchain-uv-fastapi-wireup.md). The uv and FastAPI
clauses of that record still stand, as does the rule that the router signature
is the injection boundary.

## Context

DEC-0003 adopted wireup for the domain object graph and justified it not on
ergonomics but as a control:

> FastAPI cannot detect a singleton that has captured request-scoped state.
> wireup validates lifetimes **at startup** and fails fast on scope leakage.
> [...] a `ContentGenerationAgent` registered as a singleton that accidentally
> retains a `LearnerHistoryPort` bound to one learner's session would leak one
> minor's history into another's.

That reasoning is correct and still holds. `Depends()` resolves per call and
has no view of how long the object on the other side lives, so FastAPI alone
cannot see the hazard.

What does not follow is that the control requires *that library*. The check is
a property of the registration graph: for every singleton, no requirement may
be request-scoped. Expressed directly it is a few dozen lines.

Two things argue for expressing it here. A third-party package sitting in the
enforcement path of a data-protection claim has to be trusted and maintained
for as long as the claim is made. And a thesis that *shows* the mechanism is
stronger evidence than one that cites a dependency for it.

## Decision

**No dependency-injection library.** FastAPI's `Depends()` at the router
signature, and a first-party composition root below it.

- `Provider` (`di/provider.py`) is the ABC every registration implements. It
  declares `provides`, `lifetime`, `requires` and `create` — `requires` exists
  so the graph is checkable, not merely constructible.
- `LifetimeValidation` (`di/container.py`) raises `ScopeLeak` when a singleton
  requires a request-scoped provider, and `UnregisteredDependency` when a
  requirement has no provider. `ApplicationContainer.build()` runs it, so an
  invalid graph never reaches the first request.
- `Provide(SomeType)` (`di/dependency.py`) is the `Depends()` callable. It
  reads the container from `request.app.state`, which is per-application
  instance state — several applications exist in one process during the test
  run and share nothing.
- `container.py` names every concrete class, and nothing else does.

## Consequences

**Positive.** The scope-leak guarantee survives supersession, and its mechanism
is now reviewable first-party code with unit tests that name the hazard
directly. DEC-0003's own stated negative — *two DI mechanisms in one codebase;
a contributor must know which applies where* — disappears: there is one.
One fewer third-party package in the path of a compliance claim.

**Negative.** Resolution at the router signature is by type, read from
`request.app.state`, rather than constructor injection all the way into the
handler as wireup did. Rule 3 confining that to the router signature is
therefore doing more work than before, and it is a rule rather than a
mechanism. Below the signature nothing changes: what a handler passes onward
is constructor-injected.

**Negative.** The validator is ours to maintain and to get right. wireup's is
exercised by its whole user base; ours is exercised by this repository's tests.
That is the trade accepted for removing the dependency, and it is why the
lifetime tests assert on the hazard (`GenerationAgent` holding
`LearnerHistory`) rather than on abstract types.

**Negative.** No auto-wiring: every provider is written out. That is more
typing, and also the point — `container.py` is meant to be the only site
naming concrete classes, and now it visibly is.

**Rejected — keeping wireup.** A maintained, competent library, and the
mechanical guarantee was genuine. Rejected because the guarantee is
reproducible in-repo at small cost, and a claim this repository exists to prove
should not depend on a package it does not control.

**Rejected — `Depends()` with no lifetime check.** The common FastAPI shape.
Rejected because it withdraws the control rather than relocating it: nothing
would catch a singleton that captured learner-bound state, and REQ-MINOR would
lose its mechanical backing and become a review convention.

**Rejected — `@lru_cache def get_settings()`.** The idiom most FastAPI projects
use. It is a module-level function holding behaviour (rule 2) and a
module-level singleton (rule 3), and its cache is process-global, so two
applications in one test run would share configuration. `DatabaseSettingsProvider`
gives the same read-once behaviour scoped to a container instance.
