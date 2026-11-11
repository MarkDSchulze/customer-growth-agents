# ADR-007: Deployable synthetic reference slice

Status: implemented for the mock MVP; enterprise release approval remains open.

The remote repository was empty. The six supplied documents are retained as design inputs. Their references to pre-existing technical assets did not correspond to files in the empty repository; this change creates version 1 contracts and supporting assets rather than claiming to preserve unseen versions.

Use one versioned Python package deployed as API, event dispatcher/consumer and Temporal worker processes. Domain agents, decisioning, policy gateway and adapters are separate modules with typed boundaries. Independent service extraction can follow measured scaling or ownership needs. The five agents are deterministic structured planners; no model provider, model keys or free-form generation is required. Marketing alone can propose the approved synthetic journey; Sales and Advertising are explicitly recommendation-only expansion seams.

Operational aggregates use a tenant/kind/key primary key and schema-validated JSON values in PostgreSQL, with forced RLS and a non-superuser application role. This compact reference store differs from the normalized proposed design in DATA_MODEL.md. Kind-specific indexes, normalized foreign keys, partitioning and storage retention must be designed against real workload evidence before enterprise rollout. Synthetic source snapshots live under a separate mock namespace and must be replaced with authoritative read adapters for a sandbox pilot.

SQLite is an optional fast local runner for policy and browser testing. It uses BEGIN IMMEDIATE to exercise atomic boundaries. Docker uses PostgreSQL, Kafka's native development image and Temporal's persistent SQLite dev server. These are local, single-node components, not a production topology. Dev-server volume initialization uses root; the application and console containers run unprivileged. Production requires managed/HA services and workload identities.

The tenant transaction/advisory lock serializes contact-cap checks, authoritative synthetic source updates, kill-switch checks and mock activation. Normal tenant transactions take a shared global guard; the global emergency switch takes its exclusive guard. This provides a linearization point for known local updates. It cannot make an external CMP or CRM transaction atomic with an unrelated vendor send. Real connectors need an approved consistency/freshness protocol and vendor delivery semantics. Tenant-level serialization and synchronous reads limit throughput; do not infer enterprise SLOs from this implementation.

Mock vendor receipts commit independently of workflow state. Reconciliation by stable tenant/action key recovers an acceptance if the API acknowledgement or local commit is lost. Real connectors must implement idempotent acceptance and status lookup before replacing this adapter. Mock acceptance also explicitly confirms delivery; a real provider must record exposure only after delivery evidence.

Default observe-only mode produces no adapter writes. Explicitly enabling a tenant's simulation permits only synthetic receipts. No implementation selects a real SaaS endpoint, controls advertising spend, changes prices or discounts, or sends customer content.

Migration 001 is additive and append-only audit protection is enforced in PostgreSQL. Roll back the application image while retaining receipts, workflow histories, audit records and offsets. A schema rollback that deletes these records is unsafe; future changes need expand/contract migrations and compatibility tests.
