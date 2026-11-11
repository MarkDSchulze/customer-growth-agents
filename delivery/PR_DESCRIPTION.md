Build the five-domain customer growth platform with a vendor-neutral regional core and AWS, Salesforce, Adobe Experience Platform and Shopify integration boundaries.

- Add v2 typed workflows, dependency-aware agents, deterministic execution controls, identity bindings, approval separation, quotas, immutable audit and recoverable regional Kafka/Temporal execution while preserving v1.
- Add the enterprise operator console, optional constrained model gateway, tenant-scoped sandbox connectors, signed Shopify orders, descriptive budget drafts and S3 audit archiving.
- Add private AWS infrastructure, hardened Helm deployment, additive RLS migration, runbooks and complete-stack/load CI evidence.

Validation: Python/TypeScript checks, versioned contracts, synthetic policy/API/adapter/E2E tests, browser accessibility tests, real PostgreSQL/Kafka/Temporal tests, Terraform/Helm validation and complete-container/load jobs. See PR checks and artifacts for final results.

Deployment boundary: no paid infrastructure applied or live customer actions enabled. Provider sandbox acceptance, production volume/restore drills and business/security/privacy approval remain account-specific release gates. Adobe activation requires an approved idempotent bridge with delivery confirmation; Salesforce writes are sandbox internal tasks only.
