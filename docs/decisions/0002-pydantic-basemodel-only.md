# 0002. Pydantic `BaseModel` as the only model type

*Status:* Accepted · *Date:* 2026-09-18

## Context

Data crossing agent boundaries must be validated at runtime, serialised to the
audit log, and — for audit records — tamper-evident. Python offers `dataclass`,
`TypedDict`, `NamedTuple` and Pydantic models; mixing them fragments validation
and serialisation.

Article 12 evidence additionally requires that a written audit record cannot be
mutated after the fact. Mutability is the enemy of tamper-evidence: if a record
can be edited in memory after its hash is computed, the hash chain proves
nothing.

## Decision

All structured data is a Pydantic `BaseModel`. **`dataclasses.dataclass` is
prohibited project-wide**, as are `TypedDict` and `NamedTuple` for domain data.

Audit and evidence records are immutable:

```python
class TurnAuditRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    turn_id: UUID
    learner_prompt_redacted: str      # PII-redacted prompt (REQ-AUDIT)
    redacted_categories: tuple[str, ...]
    retrieved_context_ids: tuple[str, ...]
    model_revision: str | None        # pinned SHA when the model ran; null on a stop
    output_before_checks: str | None  # null with the revision when the model did not run
    output_after_checks: str | None
    safety_flags: tuple[SafetyFlag, ...] | None
    policy_version: str               # REQ-POLICY
    previous_record_hash: str         # hash chain
    recorded_at: datetime
```

`frozen=True` gives immutability and hashability; `extra="forbid"` means an
unexpected field is an error, not silent data leakage into the log. Sequence
fields are tuples, not lists, so the frozen guarantee is not defeated by a
mutable member.

**The prompt is stored, not hashed.** REQ-AUDIT records the learner prompt. Data
protection is discharged where REQ-MINOR places it — real-time PII redaction at
the input boundary, plus the student-history field allowlist — not by hashing
the prompt out of the log. Storing only a digest would make the record unable to
show what was asked, weakening both replay and the REQ-EVAL learner-history
personalisation case. What is stored is the redacted prompt, with the categories
redacted recorded beside it.

## Consequences

**Positive.** One validation and serialisation mechanism throughout.
`frozen=True` supplies the immutability the hash chain depends on, satisfying
the tamper-evidence requirement without a dataclass. `extra="forbid"` is a
data-minimisation control: undeclared fields cannot reach the log.

**Negative.** Pydantic validation costs more per object than a dataclass.
Irrelevant at this scale — the LLM call dominates every turn by orders of
magnitude.

**Note.** Third-party libraries (LangGraph, FastAPI internals) may use
dataclasses internally. The prohibition binds code authored in this project, not
its dependencies.
