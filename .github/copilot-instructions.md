# Code review

This repository is graded as compliance evidence. Review the diff against the
rules below. Comment only on lines the diff adds or changes.

## Post only High and Medium

Before posting, name the concrete input or state that produces a wrong result,
a crash, a data leak, or a broken rule. If you cannot name it, do not post.

- **High**: wrong behaviour, data loss, a security or privilege hole, a broken
  audit or transaction guarantee, or a broken rule below that a test or the
  database does not catch.
- **Medium**: a broken rule below, or a real bug on an uncommon path, or new
  logic with no unit or integration test.
- **Low, do not post**: naming, wording, docstrings, comments, formatting,
  import order, type-hint style, "consider", "for readability", refactors of
  working code, speculative future problems, and anything ruff, mypy, or
  import-linter already fails on.

Do not comment on code the diff does not touch. Do not restate a rule the diff
already follows. Do not suggest a design a decision record rejected.

## Priority Medium

A Medium comment that breaks one of these rules is priority. Start the comment
with the id, for example `DEC-0014:`. Post every priority Medium. When a
review has many comments, drop other Medium comments first.

- DEC-0001. An `abc.ABC` port exists before its implementation. Only ports
  listed in that record. A consumer never constructs a collaborator. No
  module-level singleton, service locator, or global state.
- DEC-0002. Structured data is a Pydantic `BaseModel`. No `dataclass`,
  `TypedDict`, or `NamedTuple` in first-party code. Audit and evidence models
  are `frozen=True, extra="forbid"`, with `tuple` sequence fields.
- DEC-0005. The four oversight gates run at their own graph positions:
  permission before retrieval, conflict before generation. A gate returns a
  verdict and never mutates. A non-pass verdict halts the pipeline. No
  single-pass `chain.run` over a finished turn. Every gate result is logged,
  including `not_evaluated`.
- DEC-0006. An audit record and its retrieval commit together or not at all.
  No `UPDATE` or `DELETE` on the audit table.
- DEC-0007. The model is referenced by pinned commit SHA, never by tag.
- DEC-0010. Recorded instants are `timestamptz` (full precision) and UTC
  `AwareDatetime`. Inject `ClockPort`; no `datetime.now()`. `TurnState` is a
  mutable `BaseModel`. DEC-0009 is superseded.
- DEC-0011. A use case is `prepare`, `execute`, `finalise` on three types.
  `execute` returns `Executed`, not the result. Public methods on a concrete
  class are exactly its ABC's methods.
- DEC-0012. The application encrypts through `CipherPort`. No `pgcrypto`. The
  KEK is injected. A plaintext column needs a `protected_column_exemption`
  row. Encryption cites GDPR Art. 32, never AI Act Art. 15.
- DEC-0013. The container in `tutor_api/di/` resolves below the router.
  `Depends()` only on the router signature. No PEP 695 `type` alias for a
  dependency. No DI library. A singleton must not depend on a request-scoped
  provider.
- DEC-0014. One async connection per request. The application connects as
  the application role, never the migration owner.
- Tests. New logic has both unit and integration tests. A bug fix has a test
  that fails without it. Tests never assert on real model output.

## Format

One comment per defect. If the same cause appears on other lines, list them
in that comment instead of posting again. State the failure, then the fix.
