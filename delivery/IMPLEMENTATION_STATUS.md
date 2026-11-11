# Implementation status — 2026-11-11

Version 0.2 implements the requested vendor-neutral core for all five domains, with AWS deployment assets and pluggable Salesforce, Adobe and Shopify connectors. Production certification and account-specific integration acceptance are separate release gates.

| Area | Implementation |
|---|---|
| Five agents | Bounded dependency-aware assessment/planning; deterministic baseline and optional constrained model advice |
| Domain workflows | Six signals, five executable governed tools, suppression and human Advertising review |
| Durable runtime | Normalized PostgreSQL state, Kafka transactional outbox, regional Temporal orchestration, replay generations |
| Trust and governance | Verified role/tenant/region/purpose/source, forced RLS, identity-version binding, execution-time eligibility, kill controls |
| Limits and recovery | Ingest minute quotas, active-workflow/action caps, contact frequency, bounded retries and authoritative receipt reconciliation |
| Operators | Portfolio, five agent reports, approvals, cancellation/replay, connector capability view and audit export |
| Connectors | Salesforce sandbox context/task upsert, Adobe profile purpose/consent, Shopify read-only context/signed orders, tenant HTTP bridge |
| Audit and telemetry | Hash-chain append-only audit, bounded server export, S3 KMS/Object Lock writer, redacted OTel/Prometheus |
| Infrastructure | Private regional AWS Terraform and hardened replicated Helm workloads; not applied to an account |
| Compatibility | Original v1 contracts/recovery/experiment reporting preserved |

Executed locally: 83 policy/API/adapter/concurrency/recovery/E2E tests; Python and TypeScript lint/types; OpenAPI and both AsyncAPI contract validators; Helm rendering/security validation and Terraform initialization/validation. Browser, dependency security and full-stack remote evidence are recorded after final validation in the PR checks and retained CI artifacts. Earlier v1 CI quality, browser and durable-stack checks passed.

Remaining acceptance: actual vendor sandbox schemas/permissions and delivery bridge, workload-specific capacity/SLO and chaos/restore evidence, regional provider/data residency assurance, OIDC/role governance, production telemetry routing, security/privacy/business sign-off and controlled rollout. No native Adobe activation, media spend, pricing, discounts or free-form live messaging is claimed.
