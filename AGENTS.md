# AGENTS.md — Repository Instructions

This repository is a **vendor-neutral enterprise Customer Growth AI Agent System**. Build contract-first, mock-first and safety-first. The initial end-to-end slice is **service-aware cart recovery**; do not silently broaden to autonomous ad budgets, price changes, discounts, free-form messaging, or live customer data.

## Read before changes
1. [PRD.md](PRD.md) — personas, capabilities, P0 scope, acceptance criteria.
2. [ARCHITECTURE.md](ARCHITECTURE.md) — stack, boundaries, L2/L3 interactions, security.
3. [DATA_MODEL.md](DATA_MODEL.md) — identity, event envelope, physical and logical entities.
4. [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) — milestones, dependencies, DoD.
5. [contracts/openapi.yaml](contracts/openapi.yaml), [contracts/asyncapi.yaml](contracts/asyncapi.yaml), [workflows/agent-policies.yaml](workflows/agent-policies.yaml) — executable contract intent.

## Conventions
- Prefer Python/FastAPI/Pydantic for backend, Temporal for durable workflows, PostgreSQL for operational metadata, Kafka-compatible events, TypeScript/Next.js for UI. Dependency versions must be pinned once code exists.
- Keep code separated by service and domain; define typed DTOs and adapter interfaces before vendor implementations. Do not write directly into vendor databases.
- Preserve existing canonical contract versions. Version breaking API/events explicitly and update producer, consumer, fixtures, tests and docs together.
- Attach authenticated `tenantId`, `correlationId`, `purpose`, workflow/action ID and policy version to all requests; never trust tenant scope supplied solely by clients.
- Make every side effect idempotent and auditable. Retry only safe failures; reconcile ambiguous vendor timeouts; recheck consent and service status **just before** outreach.
- Any AI-generated output is untrusted until schema-validated and policy checked. LLMs do not grant authorization or determine lawful contact eligibility.
- Use synthetic customer data only; redact PII, credentials and secrets from logs, prompts, fixtures, commits and traces. Keep real secrets in vaults, never `.env` committed.
- Use small, focused commits/PRs; include tests, documentation and migration/rollback notes for behavior changes. Document proposed architectural changes with an ADR.

## Quality gates
- Required: lint/format, static typing, unit tests, API/event contract checks, adapter tests, security/secret scans, synthetic E2E workflow tests.
- Must test: opt-out, critical case, duplicate/out-of-order events, order completion, kill switch, vendor timeout/retry, cross-tenant isolation and policy bypass attempts.
- Do not claim an integration, `make` command or test passes until it actually exists and has been executed. Documentation-only baseline is not a runnable application.
- Never enable live messaging, spend or price mutation without explicit business/security/privacy approval and verified sandbox-to-production controls.

## Execution sequence
Implement [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) phases in order, starting with Phase 1 skeleton and Phase 2 synthetic integrations. Preserve the existing L2/L3 design assets under `architecture/`, contracts under `contracts/`, DB reference under `schemas/`, policies under `workflows/`, and requirements under `delivery/`.
