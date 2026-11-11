# Implementation Plan — Enterprise Customer Growth AI Agent System

**Status:** Proposed v1.0 | **Date:** 2026-11-11 | **Delivery strategy:** Contract-first, mock-first, test-first vertical slices

## 1. Objective and MVP
Deliver a locally reproducible, governed **service-aware cart recovery** workflow connecting mock E-Commerce, CDP/consent, Service CRM, and MarTech systems; demonstrate cross-system decisioning, safe execution and experiment reporting. Scale to Sales, Paid Media and multi-region integrations later. See [PRD.md](PRD.md) and [ARCHITECTURE.md](ARCHITECTURE.md).

**Working principles:** First make a deterministic service work end-to-end with synthetic data. Add probabilistic AI only where it improves a measurable decision. Do not add live vendors, real customer contact, spend, discounting or direct SaaS writes until formally approved.

## 2. Delivery workstreams and ownership
| Workstream | Proposed owner | Responsibility |
|---|---|---|
| Product / growth | Product owner + Marketing/Commerce | User stories, KPI definition, journey approval, experiment design |
| Platform / SRE | Platform engineer | Local/dev infra, CI/CD, workflow runtime, secrets, telemetry |
| Data / identity | Data engineer + CDP owner | Canonical events, customer context, consent/identity adapters |
| Agent / decision | AI engineer + decision scientist | Candidate generation, NBA ranking, structured agent behavior, evaluation |
| Enterprise integration | Integration architect | CRM, MarTech, Commerce, Service adapters and contract tests |
| Security / privacy | Security engineer + legal/privacy | Tenant authorization, lawful purpose, contact policy, audit and approvals |
| QA | Test engineer | Contract, failure, race, E2E, load and accessibility tests |

## 3. Delivery phases, dependencies and exit criteria
Phases are sequential *gates* but tasks within a phase can be parallelized. Estimates intentionally not fixed until team capacity and vendors are known.

### Phase 0 — Baseline and decisions
**Deliver:** repository docs, ADRs, story slicing, sample data fixture inventory, initial threat model, experiment metric definition, target vendor capability matrix.

**Dependencies:** business owner, marketing journey rules, privacy/consent policy contact, architecture review.

**Tasks:**
- [ ] Confirm MVP tenant/brand, jurisdiction and synthetic cart dataset.
- [ ] Agree eligible/suppressed scenarios, email/contact caps, critical-case severity threshold and experiment holdout percentage.
- [ ] Decide stack versions and operational hosting; adopt or revise proposed technology ADRs.
- [ ] Review OpenAPI, AsyncAPI, SQL schema and policy YAML for consistency.
- [ ] Define customer journey diagram and outcome observation window.

**Verify/exit:** product and security/privacy acknowledge mock-only build; contracts lint clean; all MVP requirements mapped to tests.

### Phase 1 — Developer platform and contract skeleton (P0)
**Deliver:** runnable local environment and CI with typed, tested service skeletons.

**Dependencies:** Phase 0 contracts and initial stack approval.

**Tasks:**
- [ ] Create `apps/growth-console`, `services/growth-api`, `services/workflow-worker`, `services/decision-service`, `services/policy-gateway`, `adapters/mock-*`, `packages/contracts`, `tests/`.
- [ ] Define version-pinned Python/Node dependencies, lock files, formatting/lint/type-check commands.
- [ ] Set up local PostgreSQL, Kafka-compatible broker, Temporal dev, mock adapters; document `.env.example` with no secrets.
- [ ] Add `/healthz`, `/readyz`, structured traces and correlation IDs.
- [ ] Add database migrations; RLS/tenant safety plan; initial tenant and synthetic fixtures.
- [ ] Validate OpenAPI/AsyncAPI plus schema compatibility in CI.

**Verify/exit:** one-command local startup; API health and DB migration smoke tests pass; PR CI runs lint, types, unit tests, contract checks.

### Phase 2 — Trustworthy customer/event foundation (P0)
**Deliver:** validated event ingest, identity/context resolution, consent and service awareness.

**Dependencies:** mock commerce, CDP/CMP and Service CRM contract fixtures.

**Tasks:**
- [ ] Implement canonical envelope validation, duplicate receipt, topic consumer and DLQ.
- [ ] Build mock commerce cart/order/stock reader with idempotent event emitter.
- [ ] Build mock customer context / purpose/consent reader; require authenticated tenant.
- [ ] Build mock service case reader with high/critical suppression.
- [ ] Add TTL cache only for nonauthoritative data and explicit stale-data failure behavior.
- [ ] Add tests for unknown identity, opt-out, out-of-order order events and cross-tenant isolation.

**Verify/exit:** all source events validate; duplicates and late orders do not cause outreach; unknown consent or critical case failure results in suppression/hold.

### Phase 3 — NBA decisioning and deterministic guardrails (P0)
**Deliver:** consistent candidate selection, ranking, experiment assignment, and policy decisions.

**Dependencies:** Phase 2 context adapters; approved contact policy.

**Tasks:**
- [ ] Implement approved recovery candidate generator and explicit hard-gate order.
- [ ] Implement ranker as deterministic baseline; log policy/scoring versions and reason codes.
- [ ] Add experiment definition and stable holdout assignment; emit exposure events only on confirmed action.
- [ ] Persist decision and recommendation using idempotency uniqueness.
- [ ] Define typed agent task/proposal contracts; optional LLM explanations without tool permission.
- [ ] Build policy test matrix for consent, severe open case, completed order, stock, contact caps and tenant mismatch.

**Verify/exit:** every test fixture yields expected `eligible/suppressed/holdout/review_required` disposition; same input produces same decision under same versions; unsafe model suggestions cannot cause outbound action.

### Phase 4 — Durable execution and first end-to-end journey (P0)
**Deliver:** fully exercised service-aware cart recovery workflow and safe mocked MarTech activation.

**Dependencies:** Phase 3 policy gateway; mock MarTech adapter; Temporal state model.

**Tasks:**
- [ ] Start-or-signal workflow on cart event; persist correlation ID and workflow state.
- [ ] Recheck order status, consent and critical service case **immediately before** any action.
- [ ] Implement tool gateway allowlist, request schema validation, idempotency and vendor status reconciliation.
- [ ] Trigger only pre-approved marketing journey in mock adapter; never generate/send free-form messages.
- [ ] Implement bounded retries, timeout, cancellation, DLQ, safe replay and kill switch.
- [ ] Reconcile `order_placed` outcomes, emit treatment exposure/measurement and audit trail.
- [ ] Implement synthetic operator interface for action/decision lookup and kill switch.

**Verify/exit:** successful cart sends exactly one vendor action; suppression and holdout send zero; consent/service/order races caught; ambiguous timeout does not duplicate; kill switch prevents new sends.

### Phase 5 — Measurement, hardening and MVP release (P0)
**Deliver:** quality-gated demo, operator runbook, dashboards, launch review.

**Dependencies:** Phase 4 E2E, defined KPI/experiment windows, deployment credentials in dev only.

**Tasks:**
- [ ] Build conversion and treatment/control reporting; explicitly label sample sizes and confidence uncertainty.
- [ ] Add trace dashboards, policy-denial dashboards, action errors and event lag monitoring.
- [ ] Test authZ, cross-tenant isolation, prompt injection, PII redaction, race conditions, retention, and operator accessibility.
- [ ] Run load/resilience/chaos/DR scenarios against **agreed** target volume and SLOs.
- [ ] Complete security/privacy, architecture, product and data governance reviews for mock MVP; run observe-only/dry-run then synthetic canary.
- [ ] Write operator runbook for failed actions, DLQ, rollback, emergency disablement and restart.

**Verify/exit:** all [MVP definition of done](#5-mvp-definition-of-done) gates pass; release tag and demo script created.

### Phase 6 — Post-MVP enterprise expansion (P1/P2)
**Deliver:** enterprise-specific adapters and additional lifecycle agents, without widening action authority by default.

**Dependencies:** approved vendor sandboxes, residency/tenancy architecture, platform controls and scale budget.

**Sequence:**
1. Replace one mock connector with one vendor sandbox connector; preserve contract-mock CI.
2. Integrate Sales CRM lead qualification/seller tasks and Service recovery suppression.
3. Add commerce personalization, then CDP audience/AdTech recommendations with approvals.
4. Add advanced NBA/ML, lift optimization, brand/region federation and approval workflows for high-impact business actions.
5. Propose production pilot with formal legal/privacy, platform, security and business sign-off.

## 4. Engineering backlog and task priority
**Existing stories:** [delivery/backlog.csv](delivery/backlog.csv) contains 18 backlog items (CG-001 through CG-018). Use that CSV as the initial issue-import basis; reconcile individual acceptance criteria with [PRD.md](PRD.md) before implementation.

**Critical path:** event contracts → customer identity and current consent/service/cart context → deterministic policy/NBA → durable workflow → approved journey adapter → outcome/holdout measurement → operational/release gates.

**Parallel tracks:** console/UI and analytics can proceed on mock APIs; policy engine and customer adapters can proceed on fixtures; CI and observability start from Phase 1.

**Suggested milestone order:** M0 design approved → M1 local stack → M2 event + context foundation → M3 decisioning and holdouts → M4 mock action and E2E → M5 measured, secure MVP → M6 vendor sandbox pilot.

## 5. MVP definition of done
**Functional**
- [ ] Synthetic cart abandonment enters broker and creates one workflow, even under duplicate/replay.
- [ ] Consent, service status, cart/order status, inventory, tenant and channel frequency are checked with deterministic reason codes.
- [ ] Ineligible, critical-case, opted-out, already-ordered and holdout customers receive zero journey activations.
- [ ] Eligible treatment can activate a previously approved mocked MarTech journey, **at most once** per action idempotency key.
- [ ] Order/conversion outcome is correlated to treatment/control cohort and included in measurable dashboard.
- [ ] UI can view trace, status, suppression reasons and enable kill switch; no real customer messages sent.

**Engineering**
- [ ] Code format/lint/type-check/unit/contract/integration/E2E checks pass in CI.
- [ ] API and event schemas align with implementation; backward compatibility rules documented.
- [ ] Tenant isolation, authorized tools, consent race and prompt injection tests pass.
- [ ] No real PII, production credentials, secrets or unapproved vendor keys in tests, prompts or logs.
- [ ] Async retry, ambiguous timeout, vendor outage, DLQ replay and disaster-recovery smoke test pass.
- [ ] Structured logs/traces and alerts demonstrate end-to-end correlation, including policy/agent version.
- [ ] Developer runs full mock workflow from clean checkout with documented commands and fixtures.

**Governance / release**
- [ ] Product/Marketing, Commerce, Service, architecture, security/privacy, data governance and platform stakeholders approve scope and controls.
- [ ] Business metrics and experiment analysis rules documented, including no unqualified causal lift claims.
- [ ] Runbook, rollback/kill switch, support owner and release notes reviewed.
- [ ] Production connector and customer-contact features remain disabled pending separate approvals.

## 6. Verification command conventions (to implement)
Commands below are **desired targets**, not yet executable code in this documentation-only repository:
```bash
make setup       # install pinned dev dependencies and create local env
make dev         # launch local dependencies and services
make lint        # format/lint/type/static contract validation
make test        # fast unit and component tests
make test-e2e    # synthetic cross-system workflow tests
make security    # dependency/secret scanning and security tests
make down        # stop local stack
```

CI minimum stages: docs links & contracts → lint/type-check → unit → integration/adapter contract → E2E synthetic journey → security scan → packaging; require approvals for infrastructure/policy changes. Add performance and chaos gates for enterprise pilots.

## 7. Verification scenarios (minimum test matrix)
| Scenario | Expected |
|---|---|
| Valid opted-in cart / no service issue / no order | Exactly one approved journey activation for treatment |
| Same event delivered twice | One workflow and at most one action |
| Control cohort | No activation, treatment assignment recorded |
| Marketing opt-out | Suppressed with consent reason code |
| Consent withdrawn after recommendation | Suppressed at execution recheck |
| Unresolved critical service case | Suppressed, even if NBA score high |
| Order arrives before abandonment or while workflow waits | No recovery send after order is known |
| Sold-out product / stale price | Suppress or re-evaluate using current source truth |
| Vendor timeout after accepting action | Reconcile action status before retry; no duplicate |
| Vendor permanent error | Terminal failure with audit and operator visibility |
| Worker crash during workflow | Resumes without duplicate action |
| Cross-tenant customer ID collision | No data or action leaks |
| Untrusted model/tool suggestion | Denied by allowlist/policy |
| Global kill switch enabled | Zero new outbound activations |
| Broker replay / DLQ recovery | Replay safe, experiment assignment unchanged |

## 8. Open questions / decision log
- Which enterprise cloud, CRM, Service, Commerce, MarTech, CDP/CMP and iPaaS are actually in scope?
- Are we starting with B2C cart recovery, or is B2B lead-to-revenue more representative of the target client?
- Who owns channel eligibility, contact limits, suppression reason codes and legal basis?
- What is the target tenant/region count, event volume, acceptable model spend and SLA tier?
- Which measurable incremental business result must the pilot improve?

These questions do not block implementation of the mock reference MVP, but must be resolved before integrating a real enterprise tenant.

## 9. References
[PRD.md](PRD.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [DATA_MODEL.md](DATA_MODEL.md) · [AGENTS.md](AGENTS.md) · [delivery/backlog.csv](delivery/backlog.csv) · [delivery/NFR-and-tests.md](delivery/NFR-and-tests.md)
