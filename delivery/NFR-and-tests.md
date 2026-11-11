# Verification and remaining release gates

The proposed availability, p95, throughput, RPO and RTO values in PRD.md are targets, not measurements. No customer-specific workload, residency policy or SLO has been supplied.

| Requirement | Executable evidence |
|---|---|
| FR-01, FR-02 | event/runtime/schema tests, authenticated tenant and purpose tests |
| FR-03–FR-06 | suppression matrix, execution-time consent/service/order races, typed agent authorization |
| FR-07 | deterministic assignment, holdout sends zero, replay preserves assignment |
| FR-08 | Temporal/Kafka integration, worker restart, optional approvals/expiry, cancellation, retry/DLQ |
| FR-09 | independent mock receipt store, duplicate/concurrent acceptance and lost-ack/crash tests |
| FR-10 | Playwright desktop/mobile operator controls and workflow inspection |
| FR-11 | correlation audit queries, database append-only protection, input redaction |
| FR-12 | customer-cohort denominators, conversion-window matching, currency-separated revenue, uncertainty |
| Isolation/security | forced PostgreSQL RLS with NOSUPERUSER/NOBYPASSRLS, JWT scope, tool injection rejection |

Run `make lint test test-e2e security`, `make test-integration` with the infrastructure services running, and `npm test` in `apps/growth-console` after its production build. CI runs these in separate jobs and uploads browser and integration evidence.

Still required for enterprise release: business/security/privacy acceptance; real connector sandbox contracts; OIDC issuer/claims and human identity assurance; broker identities/ACLs; HA workflow/broker/database design; encryption and retention controls; immutable external audit archive; regional placement; agreed-volume load/chaos/DR tests; restore rehearsal; manual accessibility assessment; production rollout/canary approvals. This repository does not mark those gates complete.
