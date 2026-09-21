# Supervised two-agent language-learning tutor

Compliance-evidence prototype for EU AI Act Articles 10, 12, 14 and 15. Minors
never operate the system; an adult tutor approves, edits, overrides, or stops
each turn.

## Documentation

Markdown in [`docs/`](docs/) is the source of truth. Start at
[`docs/index.md`](docs/index.md).

Once this repository is on GitHub:

1. Settings → Pages → **Source: GitHub Actions**
2. Push to `main` (or `master`)
3. The site is published at `https://<user>.github.io/<repo>/`

Then set `site_url` and `repo_url` in `zensical.toml` to that address.

Local preview (optional):

```text
uvx --from zensical==0.0.62 zensical serve
```

## Where to run commands

**Never from this directory (the repository root).** Root holds docs and the
workspace lockfile. It is not an operator cwd.

| You want | Directory | Command |
| --- | --- | --- |
| Backend (sync, tests, Postgres, later the API) | `tutor-api/` | `make` |
| Frontend dashboard (when it exists) | `app/` | `pnpm dev` |

Cursor's multi-root workspace can open a terminal in `tutor-api`. Use that.

## From a clean checkout

Requires **uv 0.12.5**, Python 3.12, Docker, and (for the model smoke)
[Ollama](https://ollama.com) **0.34.2**. Do not use Conda's `uv` 0.5.x.

```text
cd tutor-api
make sync
make up
```

`make up` starts PostgreSQL 17 with `pgvector`, pinned by image digest in
`config/runtime.toml` and `tutor-api/docker-compose.yml`. It binds
**127.0.0.1 only**. Two roles exist after init: `tutor_owner` (migrations) and
`tutor_app` (application).

Copy `tutor-api/.env.example` to `tutor-api/.env` to override credentials or
the host port. This project defaults to **5433** because `learner-postgres`
already publishes 5432 on this machine.

There is **no HTTP API process in this phase**. After the API ticket (Phase 7):

```text
cd tutor-api
make sync
uvx uv@0.12.5 run uvicorn tutor_api.main:app --reload --host 127.0.0.1 --port 8000
```

The dashboard (Phase 8, DEC-0008) will live in `app/`. When that tree exists:

```text
cd app
pnpm install
pnpm dev
```

That is Vite / React Router on port **5173**. It will talk to the API on
**8000** through the BFF, not from the browser to FastAPI.

Pull the generation model **by SHA**, never by tag (DEC-0007):

```text
cd tutor-api
ollama pull sha256:$(make print-model-sha)
make smoke-model
```

`make smoke-model` talks only to `127.0.0.1:11434`. Run it with the host's
outbound network off to confirm there is no egress.

## Checks

Ruff reviews Python (`tutor-core`, `tutor-api`). import-linter enforces the
hexagonal boundary. Biome reviews the dashboard once TypeScript files exist.
The same hook config works with **prek** or **pre-commit**. CI runs those
hooks and `pytest` (coverage gate in `pyproject.toml`).

```text
cd tutor-api
prek install
make check
```

`prek install` is enough if `prek` is on `PATH`. Otherwise, from `tutor-api/`:

```text
uvx prek install
make check
```

The Ollama revision test skips when nothing is listening on port 11434.

## Read order

1. [Requirements](docs/requirements.md) (`REQ-*`)
2. [Architecture](docs/architecture/ARCHITECTURE.md)
3. [Decisions](docs/decisions/)
4. [Implementation plan](docs/architecture/IMPLEMENTATION-PLAN.md)
