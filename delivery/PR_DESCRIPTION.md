## Build governed customer growth orchestration

The repository starts with design specifications and gains a runnable synthetic service-aware cart recovery system. Five typed domain planners coordinate context and recommendations; deterministic policy, authenticated tenant scope, approved journey configuration and an idempotent gateway govern mock execution. PostgreSQL, Kafka and Temporal preserve receipts and workflow state, and the Next.js operator console exposes decisions, correlated audit, experiments, replay and emergency controls.

The implementation includes contract exports/generated types, dependency locks, additive migrations with RLS and append-only audit, failure injection, local Compose services, CI and an operator runbook. ADR-007 documents the compact deployment/store choices and remaining enterprise release gates. Sales/Advertising remain recommendation-only; this change enables no live contact, spending, pricing or discount mutation.

Validation: 41 application/API/adapter/E2E tests; two real PostgreSQL/Kafka/Temporal tests including worker restart; two desktop/mobile browser tests; automated WCAG A/AA overview checks; Python lint/format/strict typing; TypeScript/ESLint; OpenAPI and AsyncAPI validation; secret/SAST and runtime dependency audits; production frontend build; both Docker image builds and unprivileged container smoke checks. Full-stack tests ran in stages due the build environment's disk capacity. Production load, HA/DR and external governance acceptance remain open.

Rollback: preserve operational/vendor receipts, broker offsets, audit records and Temporal histories; roll back a compatible application image. Migration 001 is additive. See delivery/RUNBOOK.md.
