# Enterprise Customer Growth AI Agent System

> **Status: Architecture and build-specification starter repository (documentation only).** No runnable application, production integrations, or automated tests have been implemented yet.

A vendor-neutral enterprise AI orchestration system for customer acquisition, sales conversion, digital commerce, marketing and advertising optimization, service-led retention, loyalty and revenue expansion. It sits **above** incumbent Sales CRM, Service CRM, MarTech, AdTech, E-Commerce, CDP, ERP/OMS, CMS and analytics systems, coordinating governed growth decisions without replacing those systems of record.

## What the platform will do
1. Ingest enterprise customer signals (e.g. a cart-abandoned event or critical service case).
2. Resolve consent- and purpose-scoped customer context across enterprise systems.
3. Identify and rank eligible growth opportunities through deterministic policies and next-best-action decisioning.
4. Delegate bounded planning to domain AI agents (Marketing, Sales, Commerce, Service).
5. Execute approved actions through scoped vendor tool adapters and durable workflows, with idempotency, human review and audit logging.
6. Measure incremental outcomes using treatment/control experiments and authoritative conversion events.

**First MVP:** Service-aware cart recovery across mock commerce, customer identity/consent, Service CRM and marketing automation systems. Outbound sends require explicit consent and approved journey configuration; no uncontrolled budget/discount/pricing changes.

## Start here
| Document | Purpose |
|---|---|
| [PRD.md](PRD.md) | Product personas, problems, journeys, functional requirements, scope, acceptance criteria |
| [ARCHITECTURE.md](ARCHITECTURE.md) | L2/L3 architecture, reference stack, system components, APIs, orchestration, security |
| [DATA_MODEL.md](DATA_MODEL.md) | Canonical identity and business entities, event/data contracts, schema and lineage |
| [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) | Delivery phases, dependency graph, verification, MVP definition of done |
| [AGENTS.md](AGENTS.md) | Codex/AI coding-agent and engineering repo instructions |

### Additional existing technical specifications
| Path | Purpose |
|---|---|
| [architecture/L2-components.md](architecture/L2-components.md) | Detailed component topology and ownership matrix |
| [architecture/L3-sequences.md](architecture/L3-sequences.md) | Cross-system journey diagrams and failure recovery |
| [contracts/openapi.yaml](contracts/openapi.yaml) | Reference OpenAPI 3.1 synchronous interface |
| [contracts/asyncapi.yaml](contracts/asyncapi.yaml) | Reference AsyncAPI 3.0 event topics and payloads |
| [schemas/postgres.sql](schemas/postgres.sql) | Reference operational data DDL (requires hardening) |
| [workflows/agent-policies.yaml](workflows/agent-policies.yaml) | Proposed permissions, eligibility and approval policies |
| [deployment/kubernetes.yaml](deployment/kubernetes.yaml) | Illustrative Kubernetes manifest, **not** production-ready |
| [delivery/backlog.csv](delivery/backlog.csv) | 18 prioritized implementation items |
| [delivery/NFR-and-tests.md](delivery/NFR-and-tests.md) | Nonfunctional requirements, SLO targets and test matrix |

## Proposed technology stack (not yet implemented)
- **UI:** Next.js / React / TypeScript.
- **Services:** Python, FastAPI, Pydantic.
- **Workflow orchestration:** Temporal, with structured domain-agent services and an optional LLM model gateway.
- **Decision engine:** deterministic eligibility/ranking baseline; calibrated ML/LLMs only after validated need.
- **Integration/eventing:** Kafka-compatible event bus, schema registry, governed vendor tool adapters.
- **Operational data:** PostgreSQL; optional Redis cache; enterprise CDP/warehouse remains external authority.
- **Infrastructure:** local Docker Compose for development; Kubernetes/cloud managed services as enterprise deployment reference.
- **Quality:** pytest, contract validation, integration and E2E fixtures, security scanning, telemetry.

See [ARCHITECTURE.md](ARCHITECTURE.md) for alternatives and decision constraints.

## Intended developer workflow
**Today:** These are design artifacts, not a runnable codebase. Begin by reviewing PRD acceptance criteria and the target application/data assumptions, then follow [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) to create services and infrastructure.

1. Read [AGENTS.md](AGENTS.md), [PRD.md](PRD.md), and [ARCHITECTURE.md](ARCHITECTURE.md).
2. Review event/API schemas and safety policy; create or update contract tests before implementation.
3. Implement Phase 1 developer skeleton, local services and fixtures.
4. Implement the first vertical slice with synthetic cart/customer/case/order data and mock MarTech journey activation.
5. Run lint/types/unit/contract/E2E, security and race/replay tests; keep source-of-truth rechecks at execution time.
6. Propose changes via small PRs linking acceptance criteria; update ADRs, documentation, schemas and migrations together.

**Planned developer commands (not yet available):**
```bash
make setup       # install tools and create local configuration
make dev         # start synthetic local services
make lint        # lint, type checks, contracts
make test        # unit and component tests
make test-e2e    # cross-system synthetic journeys
make security    # scans and security-focused tests
make down        # stop local dependencies
```
Do not run these commands expecting success until the Makefile and application code have been created in Phase 1.

## Suggested future source layout
```text
enterprise-customer-growth-ai/
├── apps/growth-console/              # operator UI (future)
├── services/growth-api/              # HTTP interfaces (future)
├── services/decision-service/        # deterministic NBA + models (future)
├── services/policy-gateway/          # tools, consent, approvals (future)
├── services/workflow-worker/         # Temporal orchestration (future)
├── adapters/                         # mock and vendor adapters (future)
├── packages/contracts/               # generated clients and types (future)
├── tests/                            # unit/contract/E2E/chaos (future)
├── architecture/                     # existing detailed L2/L3 design
├── contracts/                        # existing OpenAPI/AsyncAPI
├── schemas/                          # existing reference DDL
├── workflows/                        # existing policy baseline
├── deployment/                       # illustrative infra
├── delivery/                         # NFRs and backlog
├── PRD.md
├── ARCHITECTURE.md
├── DATA_MODEL.md
├── IMPLEMENTATION_PLAN.md
├── AGENTS.md
└── README.md
```

## Trust and deployment posture
This is a **reference build package**, not an enterprise-approved product. No live end-user messaging, CRM mutation, advertising spend, pricing changes, personal information ingestion or production credentials are authorized by this repository. All production tool scopes, legal bases, data residency, vendor permissions, human approvals, performance SLOs and retention policies require client review and explicit approval.

## Suggested first engineering issue
**CG-001: Initialize the local development and CI contract-validation skeleton.** Deliver an executable FastAPI health endpoint, PostgreSQL migration harness, Temporal dev runtime, Kafka-compatible broker, synthetic adapters, contract linting and one smoke test. Success: a new engineer can clone the repo and run a complete synthetic stack with documented commands, without paid API keys.

## Project status / open decisions
- Vendor-neutral baseline; no enterprise system provider selected.
- Multi-region production topology is a proposal, not a deployment.
- B2B sales and paid media workflows are post-MVP expansion tracks.
- Business owner, marketing contact rules, experiment thresholds and production rollout policy must be defined with the target organization.
