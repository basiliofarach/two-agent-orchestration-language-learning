# Operator entrypoint. Run every backend command from this directory.
# uv 0.12.5; Conda uv 0.5.x will fail — use `uvx uv@0.12.5` via UV.

UV ?= uvx uv@0.12.5
REPO := $(abspath ..)
# The environment lives at $(REPO)/.venv — the one tutor.code-workspace,
# prek and CI all resolve. Do not relocate it per-member.

.PHONY: help sync test check up down smoke-model lint-imports print-model-sha

help:
	@echo "Backend commands (cwd must be tutor-api):"
	@echo "  make sync          install the workspace from uv.lock"
	@echo "  make up            start Postgres + pgvector"
	@echo "  make down          stop Postgres"
	@echo "  make test          pytest (coverage gate in the workspace)"
	@echo "  make check         prek hooks + pytest"
	@echo "  make smoke-model   local Ollama completion (SHA-pinned)"
	@echo "HTTP serve is not in this phase. After the API ticket:"
	@echo "  $(UV) run uvicorn tutor_api.main:app --reload --host 127.0.0.1 --port 8000"

sync:
	$(UV) --directory "$(REPO)" sync --frozen --group dev

print-model-sha:
	@PYTHONPATH="$(REPO)" $(UV) --directory "$(REPO)" run python -c "from tests.support.runtime_pin import RuntimePin; print(RuntimePin().weights_sha())"

lint-imports:
	$(UV) --directory "$(REPO)" run lint-imports

test: sync
	$(UV) --directory "$(REPO)" run pytest

check: sync
	cd "$(REPO)" && uvx prek run --all-files
	$(UV) --directory "$(REPO)" run pytest

up:
	docker compose up -d postgres

down:
	docker compose down

smoke-model:
	PYTHONPATH="$(REPO)" $(UV) --directory "$(REPO)" run python "$(REPO)/infra/ollama/smoke.py"
