# Product Requirements Document — Enterprise Customer Growth AI Agent System

**Status:** Proposed v1.0 | **Date:** 2026-11-11 | **Owner:** Product (TBD) | **MVP:** Service-aware cart recovery

## 1. Vision and outcome
Enable enterprises to identify, prioritize, execute, and measure incremental customer-growth opportunities across Sales CRM, Service CRM, Marketing Automation, Advertising, E-Commerce, and customer intelligence without replacing those applications' systems of record. Deliver *measurable incremental value* with deterministic safeguards and reviewable AI recommendations.

**Product hypothesis:** Cross-channel growth is under-optimized because customer signals, sales actions, customer service issues, and activation channels are fragmented. A shared decisioning and governed orchestration plane can improve response quality and execution speed without uncontrolled automation.

## 2. Target users and jobs to be done
| Persona | Job to be done | Product experience | MVP inclusion |
|---|---|---|---|
| Growth / lifecycle marketing manager | Recover customers responsibly and measure incremental impact | Configure approved journeys, see recommendations and results | Primary |
| Commerce manager | Improve cart-to-order conversion without inaccurate offers | Review abandoned-cart eligibility and commerce outcomes | Primary |
| Service operations manager | Prevent promotional outreach during unresolved severe incidents | Configure severity-based suppression; inspect decisions | Primary |
| Privacy / security approver | Verify consent, purpose, tenant and tool authority before contact | Review rules, logs, and exception reports | Primary |
| Growth analyst / experimentation lead | Quantify causal lift, not just attributed revenue | Treatment/control exposures, conversions, lift dashboard | Primary |
| Sales leader / account executive | Prioritize leads and expansion opportunities | Seller follow-up recommendations and CRM tasks | Post-MVP |
| Paid media leader | Optimize audience spend safely | Audience drafts, controlled activation recommendations | Post-MVP |
| Platform operator / SRE | Diagnose cross-system workflows and safe rollback | Trace, DLQ, replay, status and emergency disablement | Primary |
| Enterprise architect / integration developer | Onboard new systems with predictable contracts | Canonical events, adapters, API policies, contract tests | Primary |

## 3. Business problems
1. Disconnected first-party signals across CRM, service, commerce, marketing, advertising, CDP and ERP result in missed or conflicting next-best-actions.
2. Channel-specific teams independently contact the same customer, often despite opt-outs, frequency limits, or serious service issues.
3. Customer-growth actions are manual, slow to implement, and difficult to audit across vendors.
4. Campaign performance is often based on attributed conversions rather than causal incremental lift.
5. Enterprise AI demos rarely enforce realistic failure recovery, approvals, tenancy, and operational constraints.

## 4. Product principles and constraints
- **Federated intelligence, governed execution.** Domain agents advise and coordinate; source systems perform authoritative writes.
- **No LLM-only eligibility.** Consent, suppression, tenant isolation, approvals and budget limits are deterministic.
- **Observe before execute.** Default dry-run, traceability, and bounded actions; production outbound contact requires explicit configuration.
- **Vendor-neutral contracts.** First adapters are mocks; vendor-specific mappings require design approval.
- **Data minimization by design.** Pseudonymous references, purpose-scoped context, no sensitive customer data in prompts or traces.
- **Measure incremental impact.** Randomized holdouts and exposure/outcome events before making causal claims.

## 5. Functional requirements
Priority: P0 is required for MVP; P1 is first enterprise expansion; P2 is later scale.

| ID | Priority | Requirement | Testable acceptance criterion |
|---|---|---|---|
| FR-01 | P0 | Ingest canonical commerce cart-abandoned and order-placed events | Valid events are schema-checked and tracked; duplicates do not create additional workflows |
| FR-02 | P0 | Resolve tenant, pseudonymous customer and customer context | Unresolvable identity or purpose permissions result in hold/suppression, never send |
| FR-03 | P0 | Pull commerce order/cart status and inventory at decision time | Recovered/completed orders and unavailable items are suppressed |
| FR-04 | P0 | Read critical unresolved service cases | Critical open case blocks promotional recovery and records reason code |
| FR-05 | P0 | Enforce channel consent, frequency limits and purpose eligibility | Revocation immediately blocks subsequent execution, including after initial decision |
| FR-06 | P0 | Generate eligible growth actions and rank next-best-action | Result includes decision ID, policy version, disposition and reason codes |
| FR-07 | P0 | Record deterministic treatment/holdout assignment | Fixed tenant/customer/experiment consistently returns one assignment and logs exposures |
| FR-08 | P0 | Orchestrate a durable recovery workflow | Retries, approval waits, dedupe, timeout and cancellation are test-covered |
| FR-09 | P0 | Trigger only pre-approved marketing journeys through tool gateway | Exactly one accepted external execution per idempotency key; unauthorized tools blocked |
| FR-10 | P0 | Provide operator/admin interface for status, rules and kill switch | Operator can view correlation trace and disable all outbound actions |
| FR-11 | P0 | Audit every decision, approval, tool attempt and outcome | Queryable correlation chain with redacted metadata and immutable export design |
| FR-12 | P0 | Report outcomes and incremental lift by experiment | Dashboard distinguishes attributed conversions from lift and reports sample size |
| FR-13 | P1 | Qualify B2B leads, dedupe and create sales follow-up tasks | No direct writes to opportunity stage without CRM business rules |
| FR-14 | P1 | Coordinate service-case recovery with marketing suppression | High-severity case updates affect activation eligibility before send |
| FR-15 | P1 | Provide commerce product recommendations | Respect available inventory, price authority, entitlements and policy |
| FR-16 | P1 | Activate consented audiences through CDP and advertising adapters | Audience exports are purpose-filtered, logged and approvable |
| FR-17 | P2 | Support multiple regions, brands, tenants and approved model providers | Region pinning and isolation verified through automated tests |
| FR-18 | P2 | Recommend media budgets and offers | Never execute budget/discount changes without designated approval |

## 6. Primary user journeys
### Journey J1 — Cart abandonment (MVP happy path)
1. Customer leaves checkout; commerce emits `commerce.cart_abandoned.v1`.
2. Platform normalizes and deduplicates event, locates pseudonymous customer, and verifies marketing purpose and opt-in.
3. Workflow checks whether an order already occurred, inventory is in stock, and critical service cases are absent.
4. Decision engine generates approved recovery candidates, applies policies, ranks eligible candidate and assigns holdout vs treatment.
5. Treatment is revalidated immediately before execution. Tool gateway triggers a *previously approved* MarTech journey via idempotent adapter.
6. Order-placed event or observation-window expiry closes workflow. Dashboard shows conversion, suppression, exposure, and experimental lift.

### Journey J2 — Customer service suppression (MVP)
An unresolved critical service case arrives before a planned recovery send. Policy revalidation suppresses activation; operator can inspect `OPEN_CRITICAL_CASE`. Marketing recovery resumes only after case resolution and a new eligibility check.

### Journey J3 — Operator intervention (MVP)
Operator finds stalled workflow, inspects redacted trace, disables outbound actions globally or per tenant, and replays safely from DLQ. Previously executed action must never be sent twice.

### Journey J4 — Lead-to-opportunity (P1)
Web lead arrives → CDP identity and consent → qualification/duplicate check → sales next-best-action → CRM seller task or approved nurture → CRM conversion outcome.

### Journey J5 — Expansion across sales and commerce (P1/P2)
Product usage and purchase data identify expansion opportunity → check service risk/entitlements → choose seller task for strategic account vs commerce recommendation for self-service → measure incremental outcome.

## 7. MVP boundaries
**In:** One mocked enterprise tenant/brand, one commerce event source, mocked CDP/CMP, mocked Service CRM, mocked commerce order/inventory service, one mocked MarTech journey adapter, one workflow engine, deterministic eligibility/NBA policy, configurable experiment holdout, action audit, API and event contracts, simple operator UI, automated tests, local development runtime.

**Out:** Autonomous ad spending, pricing and discount decisions, free-form customer communications, multiple real SaaS connectors, live PII, universal B2B account graphs, enterprise data migration, enterprise-scale multi-region deployment, production-grade attribution modeling, self-training agents, automatic CRM opportunity stage changes.

**Pilot expansion:** Replace exactly one mock adapter with a real sandbox connector after architectural/security approval, retaining mock fixtures in CI.

## 8. Nonfunctional requirements (targets; confirm with client)
| Category | Initial target | Verification |
|---|---|---|
| Reliability | ≥99.9% monthly internal decision API availability; outbound execution safely fail-closed | Synthetic probes, fault injection |
| Latency | Cached-context NBA decision p95 ≤1.5 s; event-to-decision p95 ≤60 s at agreed load | Load test with production-shaped fixtures |
| Data integrity | No duplicate external send for same action/idempotency key | Retry/timeout/dedup integration tests |
| Privacy | 100% consent and critical-case suppression enforcement in test matrix | Policy table tests, race condition tests |
| Multi-tenancy | No cross-tenant data exposure, including cache, tool credentials, and observability | Isolation / authorization tests |
| Security | Workload identity, scoped service auth, encrypted transport/storage, secrets excluded from repository | SAST, DAST, IAM review |
| Resilience | Broker replay + DLQ + reconciliation; proposed RPO 15m / RTO 60m | DR game day |
| AI quality | Every model-driven recommendation has deterministic validation and cited/structured context where relevant | Evaluation suite, adversarial prompts |
| Audit | Every impactful decision and attempted action correlated and redacted | Trace completeness checks |
| Accessibility | Operator UI targets WCAG 2.2 AA | Automated and manual accessibility testing |

## 9. Metrics and analytics
- **North star:** incremental contribution margin per eligible customer, estimated via randomized control/treatment where feasible.
- **Pilot business metrics:** cart recovery conversion lift; incremental recovered orders/revenue; suppression rate; time-to-action; contact frequency.
- **Guardrails:** complaints/unsubscribes; inappropriate sends; duplicate sends; customer service escalation; model/tool cost per action; failed actions.
- **Experiment schema:** experiment ID, eligibility snapshot, assignment, exposure, outcome, observation window, segment, cost. Define estimand and power before interpreting results. Never call raw attributed revenue incremental revenue.

## 10. Release acceptance criteria
- All P0 FRs pass automated tests, including duplicate, out-of-order, consent revoked, open critical case, order completed mid-flight, adapter outage, ambiguous timeout and kill switch.
- End-to-end mock cart abandonment reaches a verified approved journey exactly once, or is suppressed with a persisted reason.
- Control subjects receive no activation; treatment subjects can receive at most one governed action per workflow.
- Product, security/privacy, platform, service, commerce, and marketing owners review execution policy and data mappings.
- Correlation IDs trace trigger through outcome; developer can reproduce locally with synthetic data.
- SLO dashboard, alerts, runbook, and rollback switch demonstrated; no production customer data required.

## 11. Dependencies, risks and open decisions
**Dependencies:** test tenant/vendor sandboxes; owner-approved contact policies; CMP and CDP capability; contract versioning; operations/security sign-off; analytics event instrumentation.

**Risks:** differing customer identities; stale consent/case data; vendor API rate limits; account hierarchy complexity; incomplete attribution; regional residency; unauthorized marketing contact. Mitigate by authoritative rechecks and mock-driven contracts.

**Decisions needed:** cloud; source systems; B2B/B2C emphasis; selected geographies; contact policies; SLOs; data retention; volume and cost budget; experiment design. These do not block a mock-based MVP.

## 12. Reference specifications
See [ARCHITECTURE.md](ARCHITECTURE.md), [DATA_MODEL.md](DATA_MODEL.md), [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md), [contracts/openapi.yaml](contracts/openapi.yaml), [contracts/asyncapi.yaml](contracts/asyncapi.yaml), and [delivery/NFR-and-tests.md](delivery/NFR-and-tests.md).
