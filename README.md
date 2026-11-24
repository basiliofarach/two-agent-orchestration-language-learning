# Supervised two-agent language-learning tutor

A prototype of a language-learning tutor for minors, built to show how the EU
AI Act's requirements for data governance, record-keeping, human oversight and
robustness (Articles 10, 12, 14 and 15) can be met by design. Pupils never use
the system. An adult tutor approves, edits, overrides, or stops each turn
through a dashboard.

Two agents sit behind that dashboard: a **Data Retrieval Agent**, which finds
material in a curated knowledge base, and a **Content Generation Agent**, a
local, SHA-pinned Qwen3-8B. Four oversight gates are placed at different points
in the pipeline. Every turn is written to an append-only, hash-chained audit
log and can be replayed.

Because no human participants are involved, the system is evaluated by a
**role-based simulation**. Virtual pupils and simulated tutors, played by a
second local model, drive the real API, and every result is scored
deterministically.

> The code is submitted as compliance evidence, not only as working software.
> Each rule in it backs a `REQ-*` claim in
> [`docs/requirements.md`](docs/requirements.md).

---

## Contents

1. [Repository map](#repository-map)
2. [Prerequisites](#prerequisites)
3. [Where to run commands](#where-to-run-commands)
4. [Run the prototype](#run-the-prototype)
5. [Run the simulation](#run-the-simulation)
6. [Evidence pack and scripted evaluation](#evidence-pack-and-scripted-evaluation)
7. [Tests and checks](#tests-and-checks)
8. [Documentation](#documentation)
9. [Troubleshooting](#troubleshooting)

---

## Repository map

| Path | What it is |
| --- | --- |
| `tutor-core/` | Domain models, ports and services. No I/O and no frameworks (import-linter enforces this). |
| `tutor-api/` | FastAPI service, adapters, Alembic migrations, the LangGraph pipeline. **Every backend command runs from here.** |
| `tutor-sim/` | Simulation harness. It reaches the tutor only over HTTP. |
| `app/` | Tutor dashboard: React Router v8, Vite, shadcn/ui. |
| `tests/` | Workspace test suite: unit, contract and integration tests. |
| `config/runtime.toml` | Pinned runtime versions: Postgres image digest, model weights SHAs, TreeTagger hashes. |
| `datasets/sim/<version>/` | Simulation dataset. `public/` is committed; `restricted/` is git-ignored (licensing). |
| `evidence/` | Generated evidence: compliance pack, rubric scores, simulation runs, screenshots. |
| `docs/` | Requirements, architecture, decision records, dataset definition. This is the source of truth. |
| `infra/` | Ollama smoke test and other infrastructure helpers. |

---

## Prerequisites

| Tool | Version | Needed for |
| --- | --- | --- |
| [uv](https://docs.astral.sh/uv/) | **0.12.5** | Python workspace. The Makefile calls `uvx uv@0.12.5`, so the version on your `PATH` matters less, but do not use Conda's `uv` 0.5.x. |
| Python | 3.12 | Backend and harness |
| Docker | any recent | PostgreSQL 17 + pgvector |
| [Ollama](https://ollama.com) | **0.34.2** | Generation model, and the role model for the simulation |
| Node | 24 (`app/.nvmrc`) | Dashboard |
| pnpm | 12 (pinned in `app/package.json`) | Dashboard. Install it standalone (`curl -fsSL https://get.pnpm.io/install.sh \| sh -`). Corepack cannot run pnpm 12. |
| [prek](https://github.com/j178/prek) or pre-commit | — | Git hooks (optional; `uvx prek` works too) |

The simulation also needs TreeTagger 3.2.3 and several research datasets you
download yourself. See [Simulation, one-time setup](#one-time-setup).

---

## Where to run commands

**Never run commands from the repository root.** The root holds the docs and
the workspace lockfile. It is not a working directory for operators.

| You want | Directory | Command |
| --- | --- | --- |
| Anything backend (sync, DB, API, tests, simulation) | `tutor-api/` | `make <target>` (`make help` lists them) |
| The dashboard | `app/` | `pnpm <script>` |

`tutor-api/.env` is found relative to the working directory. Run a backend
command from anywhere else and the file is silently skipped. Alembic then
fails with `POSTGRES_USER is not set`.

If you use the `tutor.code-workspace` multi-root workspace, open the terminal
in the `tutor-api` folder.

---

## Run the prototype

This brings up the API and the dashboard against the small demo knowledge
base.

### 1. Install the workspace

```sh
cd tutor-api
make sync
```

### 2. Configure `tutor-api/.env`

```sh
cp .env.example .env
```

Fill in the encryption key (DEC-0012). Generate it once and keep it.
Data sealed under one key does not open under another, so `make seed` and
`make serve` must see the same pair.

```sh
python3 -c "import base64, os; print(base64.b64encode(os.urandom(32)).decode())"   # TUTOR_KEK
python3 -c "import uuid; print(uuid.uuid4())"                                      # TUTOR_KEK_ID
```

The other defaults work as they are. Postgres listens on host port **5433**
(5432 is often taken). Change `POSTGRES_PORT` if 5433 is also taken.

### 3. Start PostgreSQL

```sh
make up          # foreground; use a second terminal for the next steps
```

This starts PostgreSQL 17 + pgvector, pinned by image digest, bound to
**127.0.0.1 only**. It creates two roles: `tutor_owner` (migrations) and
`tutor_app` (the application). `make down` stops it.

### 4. Migrate and seed

```sh
make migrate     # alembic upgrade head, as the owner role
make seed        # publish the policy card, ingest the demo KB, enrol a learner
```

### 5. Install the generation model

The model is pinned by its **weights blob SHA** in `config/runtime.toml`, not
by tag (DEC-0007). Pull it by name. The adapter then lists your local models
and accepts only the one whose weights blob matches the pin.

```sh
ollama serve                 # if it is not already running
ollama pull qwen3:8b
make smoke-model             # fails closed if no local model has the pinned weights
```

`make smoke-model` talks only to `127.0.0.1:11434`. Run it with the network
off to confirm there is no egress.

### 6. Serve the API

```sh
make serve       # http://127.0.0.1:8000, OpenAPI at /docs
```

### 7. Run the dashboard

```sh
cd app
pnpm install
TUTOR_API_MODE=live pnpm dev    # http://localhost:5173
```

Without `TUTOR_API_MODE=live`, the dashboard serves **recorded fixture
sessions** (a completed, a halted and a refused turn) and needs no backend.
That is useful for looking at the UI on its own. `TUTOR_API_URL` defaults to
`http://127.0.0.1:8000`. The browser talks only to the dashboard server (BFF),
never to FastAPI directly.

Pages: `/` (sessions), `/sessions/:id` (a turn and its gates),
`/audit/:turnId` (audit record), `/simulation` (simulation runs).

---

## Run the simulation

The simulation replaces field testing (DEC-0015). The dataset is defined in
[`docs/evaluation/DATASET.md`](docs/evaluation/DATASET.md), and the harness
architecture is in
[`docs/architecture/SIMULATION.md`](docs/architecture/SIMULATION.md).

There are two tiers:

- **Tier 1, cases.** Single scripted pupil messages (proficiency, PII,
  prompt injection, history probes, open-web requests …). Each one is compared
  with the expected gate outcome from the policy's expectation table.
- **Tier 2, episodes.** Closed-loop conversations between a virtual pupil and
  a simulated tutor (roles T1 to T4). They are checked against invariants,
  for example that no non-pass verdict is ever followed by a release.

Every measure is deterministic. No model judges the quality of prose.

### Pipeline at a glance

```text
  one-time            dataset                  campaign database      runs                         read results
  ─────────           ───────                  ─────────────────      ────                         ────────────
  sources in    ──▶   make sim            ──▶  make sim-db       ──▶  make sim-run     (Tier 1) ─▶ make sim-report
  .cache/sim          (build, pupil-           make sim-serve         make sim-episodes (Tier 2)   make sim-measures
  TreeTagger           messages, freeze,       (keep running)                                      dashboard /simulation
  role model           verify)
```

### One-time setup

Do the [prototype setup](#run-the-prototype) first (steps 1, 2, 3 and 5: sync,
`.env` with the key, Postgres up, Qwen pulled).

#### a. Fill the source cache

The dataset is built **offline** from pinned artefacts. Each source in
[`datasets/sim/unreleased/public/sources.json`](datasets/sim/unreleased/public/sources.json)
gives a URL, a licence and a `sha256`. The build reads each artefact from
`.cache/sim/<sha256>` (repository root) and checks the digest. A missing or
altered file stops the build.

Some sources are a direct download. Others need a form or an email to the
authors first (TSCC, the CEFR-J Grammar Profile). Several licences forbid
redistribution, which is why none of this is committed (DEC-0016). Respect
each source's licence terms. Most are **non-commercial research only**.

Download each artefact, then copy it into the cache under its own digest:

```sh
# from the repository root, for each downloaded file
mkdir -p .cache/sim
f=path/to/downloaded/artefact
cp "$f" ".cache/sim/$(shasum -a 256 "$f" | cut -d' ' -f1)"
```

The file name must equal the `sha256` in `sources.json`. If it does not, you
have a different revision from the pinned one.
`datasets/sim/unreleased/restricted/DOWNLOADS.txt` records which revisions
were used. The `author-*` and `synthetic-pii` sources are authored in this
repository and need no download.

#### b. Install TreeTagger

TreeTagger tags sentences at build time and for `sim-measures`. It is never
part of the system under test. Download the 3.2.3 binary for your platform and
the English parameter file from the
[TreeTagger page](https://www.cis.uni-muenchen.de/~schmid/tools/TreeTagger/),
and lay them out as:

```text
datasets/sim/unreleased/restricted/treetagger/
├── bin/tree-tagger
└── english.par
```

Both files are checked against the `[pos_tagger]` hashes in
`config/runtime.toml`. The pinned binary is the Apple Silicon build. On
another platform the hash will not match, and the pin needs updating.

#### c. Install the role model

Virtual pupils and the T1 tutor are played by a model from a **different
family** from the system under test (DEC-0015): Mistral 7B, Q4_K_M, pinned
under `[role_model]` in `config/runtime.toml`.

```sh
ollama pull mistral:7b
ollama show --modelfile mistral:7b | grep ^FROM   # the blob must end in the [role_model] weights_sha
```

The role model, like the generation model, is reached on a **loopback URL
only**. A hosted URL is refused.

### Build and freeze the dataset

```sh
cd tutor-api
make sim
```

`make sim` runs four steps, and each can also be run alone:

| Step | Target | What it does |
| --- | --- | --- |
| 1 | `make sim-build` | Builds the KB, payload bank, persona and tutor cards, roster and case plan from `.cache/sim`. Offline, no model. |
| 2 | `make sim-pupil-messages` | The role model writes each planned pupil message, and the harness appends the payload. Slow: one model call per case. |
| 3 | `make sim-freeze` | Applies licence rules (non-redistributable text stays in `restricted/`) and writes `manifest.json` with the test-split digest. |
| 4 | `verify` | Rebuilds and checks the result against the manifest. |

A frozen version is never rewritten. Freezing the same version with different
bytes is refused, so a new dataset needs a new version.

### Create the campaign database and serve it

The simulation uses its **own database**, `tutor_sim`, beside the prototype's
`tutor`.

```sh
make sim-db       # drop and recreate tutor_sim, migrate, seed the KB and persona learners
make sim-serve    # API in simulation mode on tutor_sim, http://127.0.0.1:8000. Keep it running.
```

`make serve` and `make sim-serve` both use port 8000, so stop one before
starting the other.

If `tutor_sim` already holds audit records from earlier runs, `make sim-db`
stops rather than destroy them. Use `make sim-db SIM_DB_DISCARD_AUDIT=1` once
you have measured every Tier 1 run you still need (see below).

### Tier 1: run the cases and score them

In a second terminal, still in `tutor-api/`:

```sh
make sim-run       # each case against the API, into a new evidence/runs/<run_id>/
make sim-report    # scores the latest finished Tier 1 run
```

- Every run gets a new directory, `evidence/runs/run-YYYYMMDDTHHMMSS/`, and
  earlier runs are never overwritten. `evidence/tier1-latest.json` points at
  the latest finished Tier 1 run.
- **Resume** an interrupted run with `make sim-run SIM_RUN_ID=<run_id>`.
  Recorded cases are skipped. A finished run is refused.
- Score a specific run with `make sim-report SIM_RUN_ID=<run_id>`. An
  unfinished run is refused.

### Tier 2: run the episodes

```sh
make sim-episodes  # every frozen episode with tutor roles T1–T4; writes its own report
```

Episodes create their own run directory, with `transcripts/` and
`episodes.jsonl`, and write a tier `"2"` `report.json` directly. No separate
`sim-report` step is needed. Resume with `SIM_RUN_ID=<run_id>`, as for
Tier 1.

### Measures: level fit and target structure

```sh
make sim-measures SIM_RUN_ID=<run_id>
```

This computes level fit, pupil level and I2 target-structure presence for one
**reported** run, Tier 1 or Tier 2, using TreeTagger and the CEFR-J
Wordlist. A run is measured once.

> **Order matters for Tier 1.** Tier 1 replies are read back through the API,
> so `make sim-serve` must still be running on the **same** `tutor_sim`
> database. Measure a Tier 1 run before the next `make sim-db`.

### See the results

- **Files:** `evidence/runs/<run_id>/`. Every file is listed in
  SIMULATION §5.3 ([`docs/architecture/SIMULATION.md`](docs/architecture/SIMULATION.md)).
  The main ones are `report.json` (full report), `summary.json` (one row),
  `results.jsonl` (per case, Tier 1), `episodes.jsonl` and `transcripts/`
  (Tier 2), and `measures.json`. Observation files store no learner text,
  only ids, booleans, counts and gate rows.
- **Dashboard:** with `make sim-serve` running,
  `cd app && TUTOR_API_MODE=live pnpm dev`, then open
  <http://localhost:5173/simulation>.
- **Licence status:** each report carries `licence_status` (`confirmed` or
  `pending`), read from `sources.json` when the report is written. A
  `pending` report is labelled as such everywhere and must not be cited until
  it is confirmed.

### Full campaign, end to end

```sh
cd tutor-api
make sim                                  # once per dataset version
make sim-db
make sim-serve                            # terminal 2, keep running

make sim-run && make sim-report           # Tier 1
make sim-measures SIM_RUN_ID=<tier1 run>  # before any new sim-db

make sim-episodes                         # Tier 2
make sim-measures SIM_RUN_ID=<tier2 run>
```

### Simulation settings

The Makefile sets repository-rooted paths for you. Override any of them on the
command line, for example `make sim-run SIM_API_BASE_URL=http://127.0.0.1:8001`.

| Variable | Default | Meaning |
| --- | --- | --- |
| `SIM_DATASET_DIR` | `datasets/sim/unreleased` | Dataset version to build or run |
| `SIM_CACHE_DIR` | `.cache/sim` | Source artefact cache |
| `SIM_EVIDENCE_DIR` | `evidence` | Where runs are written |
| `SIM_API_BASE_URL` | `http://127.0.0.1:8000` | Tutor API under test |
| `SIM_OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Role model (loopback only) |
| `SIM_RUN_ID` | unset | Resume (`run`, `episodes`), or choose which run (`report`, `measures`) |
| `SIM_API_TIMEOUT_SECONDS` | `600` | Per-request timeout. A turn waits on the local model. |
| `SIM_KB` | `restricted/kb`, else `public/kb` | KB file `sim-db` seeds |
| `SIM_DB_DISCARD_AUDIT` | unset | Let `sim-db` drop existing audit records |

---

## Evidence pack and scripted evaluation

From `tutor-api/`:

| Command | Output |
| --- | --- |
| `make eval` | Runs the eight REQ-EVAL scripted cases on a throwaway database and writes `evidence/rubric-scores.jsonl` (rewritten each run, misses included). |
| `make evidence` | Writes the compliance pack to `evidence/`. It includes the rubric scores, labelled synthetic-only, and the simulation run summaries. It never invents tutor-sourced scores. |
| `make purge` | Applies retention: removes the history of learners past `retain_until` and logs the removal. |

From `app/`, `pnpm evidence:screenshots` regenerates the Article 14 dashboard
screenshots in `evidence/article-14/`.

---

## Tests and checks

From `tutor-api/`:

| Command | What it runs |
| --- | --- |
| `make test` | `pytest` over the workspace, with the coverage gate from `pyproject.toml`. Integration tests use testcontainers, so Docker must be running. |
| `make sandbox-test` | A throwaway Postgres: migrate it from empty, audit the live catalogue (encryption, `timestamptz`), run the integration tests, remove it. |
| `make check` | Every pre-commit hook (Ruff, strict mypy, import-linter, Biome, markdownlint) and then `pytest`. This is what CI runs. |

Install the hooks once:

```sh
cd tutor-api
prek install        # or: uvx prek install
```

The Ollama revision test is skipped when nothing listens on port 11434.

Dashboard, from `app/`: `pnpm typecheck`, `pnpm test` (Vitest) and
`pnpm test:e2e` (Playwright, fixture mode).

---

## Documentation

Markdown in [`docs/`](docs/) is the source of truth. Suggested read order:

1. [Requirements](docs/requirements.md): the `REQ-*` claims
2. [Architecture](docs/architecture/ARCHITECTURE.md)
3. [Decision records](docs/decisions/): DEC-0001 to DEC-0016
4. [Simulation architecture](docs/architecture/SIMULATION.md) and the
   [evaluation dataset](docs/evaluation/DATASET.md)
5. [Implementation plan](docs/architecture/IMPLEMENTATION-PLAN.md)

The docs are also built as a site with Zensical. To preview locally:

```sh
uvx --from zensical==0.0.62 zensical serve
```

Publishing to GitHub Pages runs from `.github/workflows/docs.yml`. Set
Settings → Pages → Source to **GitHub Actions**, push to `main`, and set
`site_url` and `repo_url` in `zensical.toml`.

---

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `POSTGRES_USER is not set` | The command did not run from `tutor-api/`, so `.env` was not found. |
| Port 5433 already in use | Set `POSTGRES_PORT` in `tutor-api/.env`. |
| Seeded data will not decrypt | `TUTOR_KEK` / `TUTOR_KEK_ID` changed between `make seed` and `make serve`. Use the same pair, or re-create the database. |
| `no local Ollama model has the pinned weights` | You pulled a different build. Compare `ollama show --modelfile <name>` with `config/runtime.toml`. |
| `<source> is not in the cache` | An artefact is missing from `.cache/sim/`, or is saved under the wrong name. The name must be its sha256. |
| Digest mismatch during build | You downloaded a different revision from the pinned one. See `sources.json` and `DOWNLOADS.txt`. |
| `sim-db` refuses to reset | `tutor_sim` holds audit records. Measure the Tier 1 runs you need, then pass `SIM_DB_DISCARD_AUDIT=1`. |
| `sim-run` refuses a run id | That run already finished. Omit `SIM_RUN_ID` to start a new one. |
| `the tutor API is not in simulation mode` | The API was started with `make serve`, not `make sim-serve`. |
| Dashboard shows sample sessions only | It is in fixture mode. Start it with `TUTOR_API_MODE=live`. |
| Conda's `uv` errors | Use uv 0.12.5. The Makefile already calls `uvx uv@0.12.5`. |
