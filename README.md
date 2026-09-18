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

## Checks

Ruff reviews Python (`tutor-core`, `tutor-api`). Biome reviews the dashboard
once TypeScript files exist. The same config works with **prek** or
**pre-commit**.

```text
prek install
prek run --all-files
```

`prek install` is enough if `prek` is on `PATH`. Otherwise:

```text
uvx prek install
uvx prek run --all-files
```

## Read order

1. [Requirements](docs/requirements.md) (`REQ-*`)
2. [Architecture](docs/architecture/ARCHITECTURE.md)
3. [Decisions](docs/decisions/)
4. [Implementation plan](docs/architecture/IMPLEMENTATION-PLAN.md)
