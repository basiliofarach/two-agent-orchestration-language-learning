# 0008. Frontend: React Router v8, fs-routes, shadcn/ui

*Status:* Accepted · *Date:* 2026-09-18

## Context

The only user interface is the human tutor dashboard — the surface through which
Article 14 becomes operational (REQ-DASH). Minors never interact with the system
directly. It needs a live session view, retrieved context, generated draft,
approve/edit/override/stop controls, visible safety flags, and an audit-log viewer.
Screenshots and exports from it are compliance evidence.

A route-file convention colocating components with their endpoint was wanted:
`_base.$sessionId`, originally native to Remix v2.

## Decision

**pnpm + Vite + React Router v8.2 in framework mode**, with file routing via
`@react-router/fs-routes`. In `app/routes.ts`, the default-exported config is
`flatRoutes()` from that package, satisfying `RouteConfig`.

Resulting route tree:

```
app/routes/
  _base.tsx                      → authenticated tutor shell
  _base._index.tsx               → /
  _base.sessions.$sessionId/
    route.tsx                    → /sessions/:sessionId
    GateTimeline.tsx             → colocated, not a route
    SafetyFlagPanel.tsx          → colocated, not a route
  _base.audit.$turnId.tsx        → /audit/:turnId
```

Leading `_` marks a pathless layout; `$` marks a dynamic segment; dots create both
path segments and layout nesting; a folder with `route.tsx` colocates
non-route modules beside the endpoint they serve.

**shadcn/ui + Tailwind** for components.

## Consequences

**Positive.** The desired convention, on a supported framework. The folder form
colocates components with their endpoint. shadcn's copy-in model means components
live in the repository — inspectable as part of the artifact, with no dependency
that can change under the evaluation.

**Negative.** shadcn ships source, not a library, so accessibility correctness of
each component is ours to maintain, and composites (the audit-log table) are
assembled by hand rather than imported. Costs frontend time that Mantine would have
saved.

**Rejected — Remix v2.** Where the convention was native, requiring no extra
package. End-of-life since June 2026 with security updates stopped; building an
Article 15 cybersecurity argument on an unmaintained framework is untenable.

**Rejected — Remix 3.** Public beta since 2026-07-28 (`v3.0.0-beta.5`), weekly
releases, and a ground-up rewrite that drops React for a forked Preact with no
migration path from v2. Too unstable for a graded artifact.

**Rejected — TanStack Start.** Same `_`/`$` conventions and stronger end-to-end type
inference, but its server-function advantage is muted here: application logic lives
in FastAPI (DEC-0003), so the router mostly calls a Python backend. A smaller
ecosystem is not worth it for a narrowed benefit.

**Rejected — Mantine.** Faster dashboard assembly, but shadcn was preferred for
in-repo component ownership.
