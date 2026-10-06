# Operator entrypoint. Run every backend command from this directory.
# uv 0.12.5; Conda uv 0.5.x will fail — use `uvx uv@0.12.5` via UV.

UV ?= uvx uv@0.12.5
REPO := $(abspath ..)
# The environment lives at $(REPO)/.venv — the one tutor.code-workspace,
# prek and CI all resolve. Do not relocate it per-member.

.PHONY: help sync test check up down smoke-model lint-imports print-model-sha \
	lint-migrations migrate seed serve sandbox-test sandbox-lifecycle evidence purge eval

# Source roots are explicit: macOS marks .venv files hidden and Python
# >=3.12.7 skips hidden .pth files, so the editable installs are not enough.
SRC := PYTHONPATH="$(REPO)/tutor-core/src:$(CURDIR)/src"
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

sync:
	$(UV) --directory "$(REPO)" sync --frozen --group dev

print-model-sha:
	@PYTHONPATH="$(REPO)" $(UV) --directory "$(REPO)" run python -c "from tests.support.runtime_pin import RuntimePin; print(RuntimePin().weights_sha())"

lint-imports:
	PYTHONPATH="$(REPO)/tutor-core/src:$(REPO)/tutor-api/src" $(UV) --directory "$(REPO)" run lint-imports

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
	$(RUN) alembic upgrade head

seed:
	$(RUN) python -m tutor_api.curation.prototype_seed

evidence:
	$(RUN) python -m tutor_api.evidence

serve:
	$(RUN) tutor-api

down:
	docker compose down

smoke-model:
	PYTHONPATH="$(REPO)" $(UV) --directory "$(REPO)" run python "$(REPO)/infra/ollama/smoke.py"

purge:
	$(RUN) python -m tutor_api.retention

# The eight scripted cases on a throwaway database, scored on observed
# behaviour. One JSON line per case; the file is rewritten each run.
eval: sync
	rm -f "$(REPO)/evidence/rubric-scores.jsonl"
	RUBRIC_REPORT="$(REPO)/evidence/rubric-scores.jsonl" $(UV) --directory "$(REPO)" run pytest --no-cov -q "tests/integration/test_dashboard_and_scenarios.py::TestScriptedScenarios"
