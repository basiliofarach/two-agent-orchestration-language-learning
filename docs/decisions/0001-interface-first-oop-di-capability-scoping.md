# 0001. Interface-first OOP; dependency injection as capability scoping

*Status:* Accepted · *Date:* 2026-09-18

## Context

The prototype must produce *evidence* that Articles 10, 12, 14 and 15 are
satisfied, not merely behave correctly. Two properties follow:

1. **Substitutability.** Every scripted scenario (REQ-EVAL) must be replayable
   with a component swapped for a recording stub, or the evaluation cannot
   isolate which part of the pipeline produced a result.
2. **Least privilege, enforced by construction.** The Content Generation Agent
   must have *no code path* to the open web or to student-history fields beyond
   the documented minimum. A convention ("don't call that") is not evidence; an
   absent method is.

A common framing is that dependency injection is itself a security control. It
is not. DI is a wiring technique. What it provides here is the *enforcement
mechanism* for capability scoping: a collaborator receives a narrow port
instance, so out-of-scope operations are not merely discouraged but unavailable
on the object it holds. That is the claim this ADR makes, and the only security
claim it makes.

## Decision

Every collaborator is defined as an abstract base class (`abc.ABC`) before it is
implemented. Concrete classes are resolved and injected; no module-level
singletons, no service locators, no direct instantiation of a collaborator
inside a consumer.

Ports defined before implementation, each traced to the requirement it carries:

| Port | Responsibility | Scope boundary | Requirement |
| --- | --- | --- | --- |
| `PiiRedactionPort` | Redact PII from learner input in real time | Runs at the boundary; nothing downstream sees raw text | REQ-MINOR |
| `KnowledgeBasePort` | Retrieve vetted educational material | Vetted corpus only; no open web | REQ-KB, REQ-COMP |
| `LearnerHistoryPort` | Read minimal student-history fields | Read-only; field allowlist | REQ-HISTORY |
| `EmbeddingPort` | Text → vector | — | — |
| `LanguageModelPort` | Prompt → completion | No tool access; no network | REQ-COMP |
| `PromptTemplatePort` | Build structured prompts; carry tone constraints | Fixed templates only | REQ-ACCURACY, REQ-MINOR |
| `GrammarCheckPort` | Grammar findings on the draft | — | REQ-COMP |
| `SafetyClassifierPort` | Flag unsafe or out-of-scope content | — | REQ-COMP |
| `SourceSupportPort` | Verify claims against retrieved sources; flag unsupported spans | — | REQ-COMP, REQ-ACCURACY |
| `OversightGatePort` | One gate in the graph | See DEC-0005 | REQ-GATES |
| `AuditSinkPort` | Append one immutable turn record | Append-only; no update/delete | REQ-AUDIT |
| `PolicyArtifactPort` | Supply the versioned machine-readable policy | Read-only; version logged per verdict | REQ-POLICY |
| `ClockPort` | Current time | Injected for deterministic replay | — |

`AuditSinkPort` exposes `append()` and no mutating method. `LearnerHistoryPort`
takes an explicit field allowlist at construction. `LanguageModelPort` is handed
a prompt string and returns text — it holds no retriever and no HTTP client, so
prompt-injected instructions to "search the web" have nothing to reach (OWASP
LLM tool-scoping per the OWASP Top 10 for LLM Applications).

## Consequences

**Positive.** Each compliance claim maps to a named port, so the evidence pack
can cite an interface rather than prose. Scenarios replay deterministically
because `ClockPort` and `LanguageModelPort` are substitutable. The
least-privilege argument is structural and demonstrable at defence by showing
the class definition.

**Negative.** More files and indirection than a prototype of this size strictly
needs; navigating the code requires following the wiring. Accepted deliberately
— the indirection *is* part of the contribution.

**Risk.** "Interfaces everywhere" can decay into one-implementation ports that
add ceremony without benefit. Mitigation: a port is justified only if it has a
second implementation (a stub counts) or enforces a scope boundary. Ports
failing both tests get collapsed.

See also
[DEC-0011](0011-layer-roles-and-service-lifecycle.md) for authoring order,
the class / repo / service / router mapping, and the application-service
typestate chain. Those stage ABCs are not added to the port table above.
