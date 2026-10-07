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
pnpm build
```

Node 24 (`.nvmrc`, matching the Docker image). pnpm is pinned by
`packageManager` in `package.json`. Install it standalone
(`curl -fsSL https://get.pnpm.io/install.sh | sh -`) so it survives
`nvm use`; Corepack cannot run pnpm 12.
pnpm refuses packages published less than a day ago (`minimumReleaseAge`),
a supply-chain guard that stays on.

## Routes

```text
app/routes/
  _base.tsx            pathless tutor shell
  _base._index.tsx     /
```

Session view and audit viewer follow the tree in DEC-0008.

## Components

`pnpm dlx shadcn@latest add <component>` copies a component into
`app/components/ui/`. It is source we own and review.

Fonts are self-hosted through `@fontsource`; the page makes no third-party
requests.
