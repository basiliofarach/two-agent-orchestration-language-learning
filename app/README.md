# Tutor dashboard

The human tutor's oversight surface (DEC-0008, REQ-DASH). Minors never use it.

pnpm + Vite + React Router v8 in framework mode, flat file routes via
`@react-router/fs-routes`, shadcn/ui + Tailwind.

## Commands

Run from this directory, never the repository root.

```text
pnpm install
pnpm dev          # http://localhost:5173
pnpm typecheck
pnpm test
pnpm test:e2e
pnpm build
```

`pnpm dev` serves the fixture sessions (a completed turn, a halted turn, and a
refused turn). The browser talks only to this app. Set `TUTOR_API_MODE=live`
and `TUTOR_API_URL` (default `http://127.0.0.1:8000`) to read FastAPI instead.
Any other `TUTOR_API_MODE` value fails at the first request rather than
falling back to fixtures.

Node 24 (`.nvmrc`, matching the Docker image). pnpm is pinned by
`packageManager` in `package.json`. Install it standalone
(`curl -fsSL https://get.pnpm.io/install.sh | sh -`) so it survives
`nvm use`; Corepack cannot run pnpm 12.
pnpm refuses packages published less than a day ago (`minimumReleaseAge`),
a supply-chain guard that stays on.

## Layout

```text
app/
  .server/                  server-only; React Router keeps it out of the browser bundle
    composition-root.ts     builds the object graph a loader uses
    dashboard-source.ts     what each loader returns
    tutor-api.ts            TutorApi port + HttpTutorApi (FastAPI)
    fixture-tutor-api.ts    FixtureTutorApi (recorded turns, same JSON)
    tutor-api.types.ts      FastAPI JSON shapes
    turn-projection.ts      audit record -> TurnView
    draft-segmenter.ts      draft + source support -> marked segments
    route-params.ts         UUID check before an id reaches a backend path
  lib/
    view-models.ts          everything a loader sends to the browser
    gates.ts                the four gates in graph order
  components/
    ui/                     shadcn source we own
    panel.tsx               titled, labelled region (Card + useId heading)
    turn/                   one component per part of a turn
  routes/
    _base.tsx                         pathless tutor shell
    _base._index.tsx                  /
    _base.sessions.$sessionId/        /sessions/:sessionId
    _base.audit.$turnId.tsx           /audit/:turnId
tests/e2e/                  Playwright, fixture mode
```

Fixture mode and live mode differ only in which `TutorApi` the composition
root builds, so fixtures go through the same projection as FastAPI data.
`null` in a view model means a stage was not reached, never "empty".
Unit tests sit next to the code they test.

## Components

`pnpm dlx shadcn@latest add <component>` copies a component into
`app/components/ui/`. It is source we own and review.

Fonts are self-hosted through `@fontsource`; the page makes no third-party
requests.
