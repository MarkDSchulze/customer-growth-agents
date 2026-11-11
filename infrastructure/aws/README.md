# AWS regional deployment foundation

The Terraform module creates paid resources only when an authorized operator runs apply. Repository setup and CI run formatting, initialization and validation only. No AWS deployment has been performed for this project.

Prerequisites: an AWS account, Terraform 1.13.4, an existing VPC with three private subnets in separate availability zones, approved private access/egress, regional DNS/CA trust, an OIDC issuer, a TLS-authenticated regional Temporal service and workload-specific capacity/cost approval. Configure a protected encrypted remote Terraform state backend before use; CI's `-backend=false` is validation only. Review availability and engine versions in the target region.

```bash
terraform init
terraform plan -var 'vpc_id=vpc-EXAMPLE' \
  -var 'private_subnet_ids=["subnet-A","subnet-B","subnet-C"]' -out=review.tfplan
# Review resource plan, cost, residency and access before an authorized apply.
```

The module provides private-endpoint EKS, managed workers across AZs, IAM CNI/network-policy support, encrypted EBS, multi-AZ encrypted PostgreSQL with forced TLS/backups/deletion protection, IAM-authenticated MSK Serverless, a regional KMS key, empty runtime Secrets Manager metadata, and a private Object Lock audit bucket. Audit objects use KMS and 365-day COMPLIANCE retention: retained objects cannot be deleted before expiry. Final snapshots and retained objects intentionally prevent casual destructive teardown.

Build and publish the API image to an approved registry; no release image is published by this PR. Configure private cluster access, namespace `growth`, and service account `growth-runtime` annotated with the Terraform workload-role ARN. This role is limited to the regional broker, runtime secret and tenant-prefixed archive location. Supply approved Secrets Manager material through your secrets operator; the module does not write application secrets into Terraform state or Kubernetes.

Inject `GROWTH_DATABASE_URL` and `GROWTH_VENDOR_DATABASE_URL` with `sslmode=verify-full` and trusted CA configuration, OIDC claims/JWKS, regional Kafka endpoints with SASL_SSL/OAUTHBEARER and regional Temporal namespace/credentials. For MSK IAM install the image's `aws` dependency extra. The application verifies enterprise prerequisites at startup. Restrict the database app role to NOSUPERUSER/NOBYPASSRLS and maintain separate migration privileges. Migration 002 is additive and must run before new workers; preserve audit/receipt tables on rollback.

Run the migration Job with a separately managed `growth-migration` secret and `migration.enabled=true`, then disable the job for routine releases. Provision the vendor receipt database ahead of time for managed PostgreSQL if CREATE DATABASE is not allowed. `scripts/migrate.py` handles local creation; regional deployments should use least-privilege preprovisioning. Keep owner credentials out of application pods.

```bash
helm lint deployment/helm/growth
helm template growth deployment/helm/growth -f approved-values.yaml
# Install only after validating the rendered manifests and account configuration.
```

Override image/tag, regional OIDC/broker/Temporal settings, existingSecret, optional tlsSecret, approved private/vendor egress CIDRs and ports, ingress namespace, replicas and resource limits. Empty egress CIDRs deliberately deny external traffic. Cluster DNS is allowed; prefer an approved egress gateway/proxy with destination policy for changing SaaS IPs. Supply a TLS ingress/gateway separately; the chart exposes only ClusterIP. HPA requires Metrics Server. Worker availability should be monitored through Temporal pollers, queue age and process metrics. The chart deploys v2 API and workers; deploy compatible v1 workers separately if retaining v1 durable traffic. The Next.js console requires its own approved hosting and private API access.

Set S3 archive lifecycle/retention and restore ownership before a real pilot. `scripts/archive_audit.py` exports/validates a tenant chain and optionally archives through an AWS role with explicit bucket/account/KMS inputs. That operator client currently buffers one tenant export; schedule bounded export sizes. S3 archiving is tested using a synthetic SDK double, not an AWS account.

Before production: vendor sandbox contract acceptance, OIDC role assurance, actual regional residency, secrets rotation, agreed-volume load/soak, failover/backup restore drills, recovery targets, observability routing, penetration/access review and business/privacy/security release approval. Terraform/Helm validation does not establish deployed HA or enterprise capacity.
