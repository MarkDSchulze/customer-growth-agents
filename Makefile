UV_CACHE_DIR ?= $(CURDIR)/work/uv-cache
export UV_CACHE_DIR
npm_config_cache ?= $(CURDIR)/work/npm-cache
export npm_config_cache
XDG_CACHE_HOME ?= $(CURDIR)/work/cache
export XDG_CACHE_HOME
.PHONY: setup dev local token demo lint test test-e2e test-integration security down contracts
setup:
	uv sync --frozen
	uv run python scripts/bootstrap.py
	cd apps/growth-console && npm ci

dev:
	docker compose up --build -d

local:
	uv run python scripts/migrate.py
	uv run uvicorn growth.api:app --host 127.0.0.1 --port 8000 --no-access-log

token:
	uv run python scripts/mint_token.py

demo:
	uv run python scripts/demo.py

contracts:
	uv run python scripts/export_contracts.py --check

lint: contracts
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy src scripts
	cd apps/growth-console && npm run typecheck && npm run lint && node scripts/validate-asyncapi.mjs

test:
	uv run pytest -m 'not integration' -q

test-e2e:
	uv run pytest -m e2e -q

test-integration:
	uv run python scripts/verify_stack.py

security:
	uv run python scripts/scan_secrets.py
	uv run bandit -r src scripts -q
	uv export --quiet --frozen --no-dev --no-emit-project --format requirements-txt -o work-requirements.txt
	uv run pip-audit -r work-requirements.txt --disable-pip
	rm work-requirements.txt
	cd apps/growth-console && npm audit --omit=dev --audit-level=high

down:
	docker compose down
