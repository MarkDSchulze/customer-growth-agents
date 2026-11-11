# Operator runbook

Use synthetic data only. `make setup` generates `.env` with private permissions; do not commit it or copy tokens into logs. Keep source-system credentials in an approved vault for a future sandbox pilot.

## Startup and diagnosis

1. `make setup && make dev`; then check `docker compose ps`, `/healthz` and `/readyz`.
2. `/healthz` is process liveness. `/readyz` verifies durable ingress storage and configured authentication; downstream workflow or broker outages can leave ingress ready because the outbox retains work.
3. `make token`; connect the console, then run its demo. The Temporal UI shows `growth-<workflowId>` on queue `growth-cart-recovery-v1`.
4. Search the workflow or filter `/v1/audit?correlationId=<uuid>` with an authenticated token. Audit fields deliberately omit raw event inputs, customer contact details, tokens and exception text.
5. `docker compose logs --tail 100 api event-worker workflow-worker` for structured request or worker failures. Broker/Temporal transient startup failures restart the workers. Monitor the authenticated `/metrics` endpoint using a separately managed operator token.

## Emergency controls

Governance → Pause all tenant actions blocks new activation at the same transaction boundary as execution. Previously accepted mock actions cannot be recalled. Resume only after investigating the suppression and pending workflow state.

A token with the separate `platform_admin` role can `PUT /v1/control/global-kill-switch` with `{"enabled":true}` to block all tenants. Tenant admin tokens cannot operate this endpoint. Local development can mint the role using `uv run python scripts/mint_token.py --role platform_admin`; production must use an approved issuer and separate platform authorization.

## Retries and ambiguous acceptance

Safe unavailability retries are bounded (three default attempts). Temporal schedules exponential backoff; the inline developer runner does immediate bounded retries for fast testing. Unknown status and exhausted attempts produce FAILED_REVIEW and a DLQ entry. Query `/v1/dlq`, inspect the correlated audit, restore mock vendor health through `PUT /v1/simulation/vendor-fault`, then replay from the workflow inspector or `POST /v1/workflows/{id}/replay`.

Replay first reconciles the independent vendor receipt by tenant/action key and never sends another accepted action. It also rechecks current policy. Permanent vendor rejections cannot be replayed. Duplicate source events or new abandonment event IDs for the same tenant/cart reuse one workflow. Do not delete receipts or change an idempotency key to force progress.

Vendor fault modes: `healthy`, `unavailable`, `permanent`, `timeout_after_accept`, `unknown_status`. They affect only synthetic adapter storage.

## Human review and expiry

Set `requireApproval: true` in the versioned policy before creating new workflows to require review. Decisions wait at APPROVAL_PENDING. An authenticated admin with `identityType=human` can `POST /v1/approvals/{workflowId}/decisions` with `{"decision":"approved"}` or `rejected`. Workload identities cannot approve; requestor and approver must differ. Approval expires after one hour; eligibility is rechecked after approval. The workflow observation window defaults to 72 hours. Policy changes require a new version and contract/regression checks.

The console currently exposes trace/kill/cancel/replay controls; approval decisions use the authenticated API. No broad production tool authority is granted by an approval.

## Rollback and recovery

`make down` preserves named volumes. Redeploy the previous compatible image using the same PostgreSQL, broker and Temporal data. Worker restart is covered by the integration test. Existing accepted mock actions reconcile by stable keys, while source events and workflow starts deduplicate.

Migration 001 is additive. Roll back application code, not audit or receipt history. Avoid `docker compose down -v` except deliberate destruction of a disposable synthetic environment. Do not truncate operational tables, reset consumer offsets or delete Temporal histories as a recovery mechanism.

For enterprise deployment, test encrypted backup restoration of PostgreSQL, broker and workflow state together in an isolated environment. The reference stack has not demonstrated the proposed 15-minute RPO/60-minute RTO, multi-region failover or production load targets. Configure external immutable audit export, operator alerts, retention and restore ownership before a real sandbox pilot.

## Synthetic experiment interpretation

Assignments use SHA-256 over tenant/customer/experiment and remain stable on replay. Only eligible customers enter the denominator. Control receives no activation. The mock provider confirms delivery on acceptance; real providers require delivery evidence. Outcomes match customer identity and event time within 72 hours of assignment. Revenue remains separated by currency. Lift is descriptive with a conservative interval; small samples and incomplete windows prevent business claims. Approve sample size/power, estimand and observation policy before a real experiment.

## Version 0.2 regional workflows

Open Enterprise workflows for the all-domain demo, agent reports and human Advertising approval. `/v2/workflows` uses cursor pagination; `/v2/operations` reports operational counts. The regional worker queue is `growth-enterprise-v2-<region>` with Temporal ID `enterprise-<region>-<workflowId>-<generation>`. `docker compose logs --tail 100 enterprise-worker sandbox` diagnoses its synthetic bridge. The original workers continue to serve v1.

Provision policy through platform-admin `PUT /v2/tenants`. Tenant/global switches, allowed domains/purposes, minute ingestion quota, hourly action reservations, pending workflow limit and contact caps are enforced server-side. Increasing limits requires a new policy version. Policy, identity, consent, order or source changes invalidate stale eligibility before effects. Human approvals bind the plan hash/version and expire; verified workload identities and the requestor cannot approve their own plans.

Cancel via `/v2/workflows/{id}/cancel`; replay recoverable review failures via `/v2/workflows/{id}/replay`. Replay starts a new Temporal generation while retaining action keys and provider receipts. Never delete accepted receipts or alter keys to force sending. Unknown provider status requires investigation rather than blind retry. Outbox publisher failures retain unpublished rows and broker redelivery is safe.

Use `/v2/audit/export` with an all-purpose-scoped tenant admin token for NDJSON hash-chain evidence. Export snapshots a high-water sequence and pages without holding a database transaction over the network. `scripts/archive_audit.py --token-file <private-file> --output <export.ndjson>` verifies the chain; optional `--bucket`, `--kms-key` and `--account` write a KMS-encrypted, 365-day COMPLIANCE Object Lock object. Run only with an approved AWS role. Avoid placing tokens on command lines. The operator CLI buffers the tenant export, so schedule bounded export sizes.

Migration 002 adds normalized v2 tables/RLS and leaves v1 data/contracts intact. Stop new v2 ingress and drain/reconcile pending actions before rolling back code; preserve all v2 audit, assignment, identity and receipt records. Restore databases and Temporal/broker checkpoints together in an isolated rehearsal before production. See [AWS setup](../infrastructure/aws/README.md) and [connector configuration](CONNECTORS.md).
