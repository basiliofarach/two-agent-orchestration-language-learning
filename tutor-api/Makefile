# Operator entrypoint. Run every backend command from this directory.
# uv 0.12.5; Conda uv 0.5.x will fail — use `uvx uv@0.12.5` via UV.

UV ?= uvx uv@0.12.5
REPO := $(abspath ..)
# The environment lives at $(REPO)/.venv — the one tutor.code-workspace,
# prek and CI all resolve. Do not relocate it per-member.

.PHONY: help sync test check up down smoke-model lint-imports print-model-sha \
	lint-migrations migrate seed serve sandbox-test sandbox-lifecycle evidence \
	purge eval sim sim-build sim-pupil-messages sim-freeze sim-run sim-episodes sim-report sim-db sim-serve

# Harness paths are repository-rooted. ``$(RUN)`` keeps this directory as the
# working directory so ApplicationSettings still finds tutor-api/.env.
SIM_DATASET_DIR ?= $(REPO)/datasets/sim/unreleased
SIM_SOURCES_PATH ?= $(SIM_DATASET_DIR)/public/sources.json
SIM_EVIDENCE_DIR ?= $(REPO)/evidence
SIM_RUNTIME_PIN_PATH ?= $(REPO)/config/runtime.toml
# Empty means: restricted/kb when the build wrote it there (a non-redistributable
# input such as CEFR-SP SCoRE), else public/kb. Chosen in the shell, because
# make's wildcard splits the repository path at its space.
SIM_KB ?=
SIM_ROSTER ?= $(SIM_DATASET_DIR)/public/learners/roster.jsonl
SIM_CACHE_DIR ?= $(REPO)/.cache/sim
SIM_ENV = SIM_DATASET_DIR="$(SIM_DATASET_DIR)" \
	SIM_CACHE_DIR="$(SIM_CACHE_DIR)" \
	SIM_SOURCES_PATH="$(SIM_SOURCES_PATH)" \
	SIM_EVIDENCE_DIR="$(SIM_EVIDENCE_DIR)" \
	SIM_RUNTIME_PIN_PATH="$(SIM_RUNTIME_PIN_PATH)" \
	SIM_TREETAGGER_DIR="$(SIM_DATASET_DIR)/restricted/treetagger" \
	$(if $(SIM_RUN_ID),SIM_RUN_ID="$(SIM_RUN_ID)")

# Source roots are explicit: macOS marks .venv files hidden and Python
# >=3.12.7 skips hidden .pth files, so the editable installs are not enough.
SRC := PYTHONPATH="$(REPO)/tutor-core/src:$(CURDIR)/src:$(REPO)/tutor-sim/src"
# `--project` keeps this directory as the working directory, so
# ApplicationSettings finds tutor-api/.env (`--directory` would not).
RUN := $(SRC) $(UV) run --project "$(REPO)"

help:
	@echo "Backend commands (cwd must be tutor-api):"
	@echo "  make sync          install the workspace from uv.lock"
	@echo "  make up            start Postgres + pgvector"
	@echo "  make down          stop Postgres"
	@echo "  make test          pytest (coverage gate in the workspace)"
	@echo "  make sandbox-test  throwaway Postgres: migrate it empty, audit it, integration tests"
	@echo "  make sandbox-lifecycle  the sandbox runner itself, against real docker"
	@echo "  make check         prek hooks + pytest"
	@echo "  make lint-migrations  ruff --fix + format over alembic/versions"
	@echo "  make smoke-model   local Ollama completion (SHA-pinned)"
	@echo "  make migrate       apply every Alembic revision, as the owner role"
	@echo "  make seed          publish the policy card, ingest the demo KB, enrol a learner"
	@echo "  make serve         the API on http://127.0.0.1:8000 (docs at /docs)"
	@echo "  make evidence      write the compliance pack to ../evidence"
	@echo "  make purge         remove history of learners past retain_until, and log it"
	@echo "  make eval          run the eight REQ-EVAL cases; scores to ../evidence/rubric-scores.jsonl"
	@echo "  make sim          build, write pupil messages, freeze, and verify the dataset in SIM_DATASET_DIR"
	@echo "  make sim-build    build the dataset and plan.json from cached sources"
	@echo "  make sim-pupil-messages  the role model writes each pupil message in plan.json"
	@echo "  make sim-freeze   write the manifest"
	@echo "  make sim-run      Tier 1 against the API; a new evidence/runs/<run_id>/ each time"
	@echo "                    SIM_RUN_ID=<run_id> continues an unfinished run"
	@echo "  make sim-episodes Tier 2 episodes; writes evidence/runs/<run_id>/ with transcripts"
	@echo "  make sim-report   score the latest finished run (SIM_RUN_ID=<run_id> for another)"
	@echo "  make sim-db       create tutor_sim, migrate it, seed C1 and C2"
	@echo "  make sim-serve    the API in simulation mode, on tutor_sim"

sync:
	$(UV) --directory "$(REPO)" sync --frozen --group dev

print-model-sha:
	@PYTHONPATH="$(REPO)" $(UV) --directory "$(REPO)" run python -c "from tests.support.runtime_pin import RuntimePin; print(RuntimePin().weights_sha())"

lint-imports:
	PYTHONPATH="$(REPO)/tutor-core/src:$(REPO)/tutor-api/src:$(REPO)/tutor-sim/src" $(UV) --directory "$(REPO)" run lint-imports

# Alembic runs these two on each generated script via [post_write_hooks].
# This target is the catch-up pass for scripts written before the hooks
# existed, or edited by hand after generation.
lint-migrations:
	$(UV) --directory "$(REPO)" run ruff check --fix "$(CURDIR)/alembic/versions"
	$(UV) --directory "$(REPO)" run ruff format "$(CURDIR)/alembic/versions"

test: sync
	$(UV) --directory "$(REPO)" run pytest

# A second Postgres, not the one `make up` keeps. The compose file does not
# read tutor-api/.env. The runner first removes any project a killed run left,
# then migrates the empty `sandbox` database through the Alembic CLI. Each
# integration test still creates its own database; test_instant_columns
# audits the migrated one. The project and its volume are removed when pytest
# exits, including when pytest fails.
sandbox-test: sync
	$(RUN) python -m tutor_api.sandbox

# Starts and removes the real sandbox project. Not part of `make test`, and
# skipped while a `make sandbox-test` holds the project.
sandbox-lifecycle: sync
	$(UV) --directory "$(REPO)" run pytest --no-cov -m sandbox_lifecycle tests/integration/test_sandbox_stack.py

check: sync
	cd "$(REPO)" && uvx prek run --all-files
	$(UV) --directory "$(REPO)" run pytest

up:
	docker compose up

migrate:
	@echo "[migrate] alembic upgrade head"
	@$(RUN) alembic upgrade head

seed:
	@echo "[seed] prototype policy and knowledge base"
	@$(RUN) python -m tutor_api.curation.prototype_seed

evidence:
	@echo "[evidence] evidence pack"
	@SIMULATION_REPORTS_DIR="$(SIM_EVIDENCE_DIR)/runs" $(RUN) python -m tutor_api.evidence

serve:
	SIMULATION_REPORTS_DIR="$(SIM_EVIDENCE_DIR)/runs" $(RUN) tutor-api

down:
	docker compose down

smoke-model:
	@echo "[1/1] pinned model (config/runtime.toml [model]) on local Ollama"
	@PYTHONPATH="$(REPO):$(REPO)/tutor-core/src:$(CURDIR)/src" \
		$(UV) --directory "$(REPO)" run python "$(REPO)/infra/ollama/smoke.py"

purge:
	@echo "[purge] retention: expired learner data"
	@$(RUN) python -m tutor_api.retention

# The eight scripted cases on a throwaway database, scored on observed
# behaviour. One JSON line per case; the file is rewritten each run.
eval: sync
	rm -f "$(REPO)/evidence/rubric-scores.jsonl"
	RUBRIC_REPORT="$(REPO)/evidence/rubric-scores.jsonl" $(UV) --directory "$(REPO)" run pytest --no-cov -q "tests/integration/test_dashboard_and_scenarios.py::TestScriptedScenarios"

# Offline: reads the pinned artefacts from .cache/sim and checks each digest.
# Build never calls the role model; the fixture flag only lets the CLI wire
# without a [role_model] pin. pupil-messages still needs the real pin.
# Each harness target prints one step line, a progress bar where the command
# loops (pupil-messages, run, episodes), then the command's own summary line.
sim-build:
	@echo "[build] dataset and plan.json from the pinned sources in .cache/sim"
	@SIM_OFFLINE=true SIM_ROLE_FIXTURE=true $(SIM_ENV) $(RUN) python -m tutor_sim build

sim-pupil-messages:
	@echo "[pupil-messages] pupil messages from the role model ([role_model] pin)"
	@$(SIM_ENV) $(RUN) python -m tutor_sim pupil-messages

sim-freeze:
	@echo "[freeze] manifest and test-split digest"
	@$(SIM_ENV) $(RUN) python -m tutor_sim freeze

sim: sim-build sim-pupil-messages sim-freeze
	@echo "[verify] rebuild check against the manifest"
	@$(SIM_ENV) $(RUN) python -m tutor_sim verify

sim-run:
	@echo "[run] Tier 1 cases against the API at SIM_API_BASE_URL (make sim-serve)"
	@$(SIM_ENV) $(RUN) python -m tutor_sim run

sim-episodes:
	@echo "[episodes] Tier 2 closed-loop episodes with tutor roles T1-T4"
	@$(SIM_ENV) $(RUN) python -m tutor_sim episodes

sim-report:
	@echo "[report] score the Tier 1 run"
	@$(SIM_ENV) $(RUN) python -m tutor_sim report

# Recreates tutor_sim each time, so a seed never mixes with an older one.
# If tutor_sim holds audit records from simulation runs it stops instead;
# SIM_DB_DISCARD_AUDIT=1 drops them too. Quiet by design: one line per step,
# the seed's progress bar, then its summary. Step output goes to a temporary
# log, printed only on failure.
SIM_DB_DISCARD_AUDIT ?=
sim-db:
	@KB="$(SIM_KB)"; \
	if [ -z "$$KB" ]; then \
		KB="$(SIM_DATASET_DIR)/restricted/kb/documents.jsonl"; \
		[ -f "$$KB" ] || KB="$(SIM_DATASET_DIR)/public/kb/documents.jsonl"; \
	fi; \
	LOG=$$(mktemp -t sim-db); \
	echo "[1/3] database tutor_sim (dropped and recreated)"; \
	SIM_URL=$$($(RUN) python -m tutor_api.curation.simulation_database --reset \
		$(if $(SIM_DB_DISCARD_AUDIT),--discard-audit) 2>"$$LOG") \
		|| { cat "$$LOG"; exit 1; }; \
	echo "[2/3] migrations"; \
	DATABASE_URL="$$SIM_URL" $(RUN) alembic upgrade head >"$$LOG" 2>&1 \
		|| { cat "$$LOG"; exit 1; }; \
	echo "[3/3] knowledge base and learners from $${KB#$(REPO)/}"; \
	DATABASE_URL="$$SIM_URL" $(RUN) python -m tutor_api.curation.simulation_seed \
		"$$KB" "$(SIM_ROSTER)" || exit 1; \
	echo "done"

sim-serve:
	TUTOR_MODE=simulation POSTGRES_DB=tutor_sim \
		SIMULATION_REPORTS_DIR="$(SIM_EVIDENCE_DIR)/runs" $(RUN) tutor-api
