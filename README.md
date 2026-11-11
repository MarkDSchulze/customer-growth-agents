# Customer Growth Agents

A runnable, vendor-neutral customer growth orchestration reference implementation with five bounded domain agents: **Marketing, Advertising, Sales, Commerce and Service**.

The first working journey is **service-aware cart recovery**. An authenticated cart signal enters a durable workflow, domain planners propose structured actions, deterministic policies decide eligibility, and a gateway activates one approved **mock** marketing journey or records suppression/holdout. The operator console shows decisions, correlated audit, experiment cohorts, replay and emergency controls.

**Current release: synthetic MVP, not an enterprise-certified production deployment.** Sales and Advertising expose recommendation boundaries; their vendor mutations, live messaging, media spend, pricing and discounts are not implemented. No paid AI keys or customer data are needed. Enterprise scale and release gates are tracked in [delivery/NFR-and-tests.md](delivery/NFR-and-tests.md).

![Synthetic operator console](docs/console.png)

## Run the complete local stack

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js 24, Docker Engine and Compose v2. Allow at least 12 GB of free disk for image/build layers; Docker's vfs storage driver can require more.

```bash
make setup     # frozen Python/npm dependencies and private generated local configuration
make dev       # PostgreSQL, Kafka, Temporal, API, workers and Next.js console
make token     # print a short-lived local admin token
```

Open **http://localhost:3000**, enter the token and select **Run synthetic demo**. The eight synthetic carts demonstrate eligible treatment, service/consent/stock suppression and holdout. Inspect a journey for all five agent proposals; open Governance to pause/resume the tenant. API documentation is at http://localhost:8000/docs and Temporal UI at http://localhost:8233.

The default is observe-only. The demo explicitly enables mock receipts for its authenticated tenant. This cannot activate a real vendor. Tokens stay in browser memory and expire after two hours. `make down` stops services while preserving database, broker and workflow volumes. `make demo` is a CLI alternative to the console demo.

For a smaller local runner, run `make setup`, `make local`, then `npm run dev` in `apps/growth-console` in another terminal. It uses SQLite and synchronous execution for developer testing; use Docker/Temporal for durable processing.

For managed environments with an inspecting HTTPS proxy, pass the trusted public CA as a build secret using [deployment/compose.proxy-build.yaml](deployment/compose.proxy-build.yaml). Do not disable TLS verification.

## Implemented behavior

- Strict versioned event/API DTOs; tenant derived from signed JWT/OIDC claims, not request bodies; role, purpose and region checks.
- Marketing, Advertising, Sales, Commerce and Service agents return schema-validated proposals. A deterministic baseline works without an LLM. Only the approved recovery journey can cause a mock write.
- Current identity, purpose, consent, severe service case, order, inventory, price freshness, frequency, cohort, optional human approval and emergency switch checks immediately before activation.
- PostgreSQL RLS with a NOSUPERUSER/NOBYPASSRLS app role, tenant transaction locks and append-only audit permissions/trigger.
- Transactional ingest/outbox, Kafka replay, stable Temporal workflow IDs, bounded safe retries, independent vendor idempotency/status lookup, ambiguous-result review and operator DLQ replay.
- Stable treatment/control assignment, confirmed mock exposure, customer-level conversion windows, currency-separated attributed revenue and conservative uncertainty intervals. Attributed revenue is never labeled incremental revenue.
- Responsive operator console with keyboard dialogs, protected proxy routes, authentication, trace inspection, search, audit and tenant kill switch.
- Health/readiness endpoints, redacted structured request logs, Prometheus metrics and reference scrape/alert configuration.

## Validate

```bash
make lint                  # Python formatting/lint/types, API drift, TS, ESLint, AsyncAPI parser
make test                  # policy, API, adapter, concurrency and recovery tests
make test-e2e              # synthetic journeys and race scenarios
make security              # source secret check, Bandit, Python and npm runtime audits
# Infrastructure must be running:
docker compose up -d postgres temporal broker
make test-integration      # real PostgreSQL RLS, Kafka→Temporal and worker restart
# Browser test (after setup):
cd apps/growth-console
npm run build
npx playwright install chromium
npm test
```

[GitHub Actions](.github/workflows/ci.yml) runs quality/security, durable-stack and browser jobs. CI results are separate from the locally executed evidence in [delivery/IMPLEMENTATION_STATUS.md](delivery/IMPLEMENTATION_STATUS.md). In managed environments with a preinstalled browser, set `PLAYWRIGHT_CHROMIUM_EXECUTABLE=/usr/bin/chromium`.

## Repository map

| Path | Purpose |
|---|---|
| `src/growth/api.py`, `auth.py` | Authenticated operator/producer API and tenant claims |
| `src/growth/engine.py` | Transactional decisions, gateway, lifecycle and measurement |
| `src/growth/agents.py`, `policy.py` | Five bounded planners and deterministic eligibility |
| `src/growth/adapters.py` | Typed adapter protocols and independent synthetic authority |
| `src/growth/temporal_worker.py`, `event_worker.py` | Durable execution, broker consumer and outbox dispatcher |
| `apps/growth-console/` | Next.js/React/TypeScript operator console |
| `contracts/`, `packages/contracts/` | OpenAPI 3.1, AsyncAPI 3.0, event JSON Schema, generated TS |
| `schemas/`, `scripts/migrate.py` | Additive migration, RLS and audit protection |
| `tests/` | Unit/API/event/E2E and real-infrastructure tests |
| `workflows/agent-policies.yaml` | Versioned approved journey, experiment, caps and retries |
| `deployment/`, `delivery/` | Reference deployment, runbook, acceptance map and backlog |

The supplied [PRD](PRD.md), [architecture](ARCHITECTURE.md), [data model](DATA_MODEL.md), [implementation plan](IMPLEMENTATION_PLAN.md) and [repository guidance](AGENTS.md) remain design context. [ADR-007](architecture/adr/007-local-reference-runtime.md) documents the implemented compact storage/runtime choices and the difference between this mock MVP and the proposed enterprise target.

## Extend safely

Replace a typed mock adapter with one approved sandbox connector, retaining the synthetic contract tests. The connector must support tenant-scoped credentials, source freshness, stable idempotency and authoritative status reconciliation. Configure approved OIDC issuer/audience/JWKS and verified human identity claims; the local token minting path is development only. Enterprise broker ACLs, immutable audit archiving, data retention/residency, HA topology and measured SLOs require explicit implementation and validation before a real pilot.

Operational procedures, rollback and failure recovery are in [delivery/RUNBOOK.md](delivery/RUNBOOK.md).
