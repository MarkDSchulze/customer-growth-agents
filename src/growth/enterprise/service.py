from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from growth.adapters import AmbiguousVendorError, PermanentVendorError, RetryableVendorError
from growth.contracts import Principal
from growth.db import Tenant, now
from growth.engine import DomainError
from growth.enterprise.contracts import (
    SIGNAL_PURPOSE,
    TOOLS,
    CustomerContext,
    Decision,
    Purpose,
    Region,
    Scope,
    SignalEvent,
    TenantConfig,
    Tool,
)
from growth.enterprise.execution import Executor, SyntheticExecutor, validate_parameters
from growth.enterprise.models import (
    Action,
    Assignment,
    CustomerFixture,
    IngestWindow,
    Journal,
    OrderEvidence,
    Organization,
    Outbox,
    Receipt,
    Workflow,
)
from growth.enterprise.planning import DeterministicGateway, ModelGateway, build, eligibility
from growth.enterprise.storage import aware, digest, journal, unit

FINAL = {"COMPLETED", "SUPPRESSED", "HOLDOUT", "CANCELLED", "EXPIRED", "FAILED_REVIEW", "DRY_RUN"}
ACTION_FINAL = {"ACCEPTED", "SUPPRESSED", "HOLDOUT", "REJECTED", "DRY_RUN", "CANCELLED", "EXPIRED"}
CONTACT_TOOLS = {"trigger_approved_journey", "activate_approved_audience"}


class EnterpriseService:
    def __init__(
        self,
        db: Engine,
        vendor_db: Engine,
        region: str = "us-east-1",
        gateway: ModelGateway | None = None,
        executor: Executor | None = None,
    ):
        self.db, self.vendor_db, self.region = db, vendor_db, region
        self.context_resolver: Any = None
        self.connector_registry: Any = None
        self.gateway = gateway or DeterministicGateway()
        self.executor = executor or SyntheticExecutor(vendor_db)

    def provision(self, config: TenantConfig, actor: str = "platform-bootstrap") -> None:
        if config.region != self.region:
            raise DomainError("REGION_DENIED", 403)
        with unit(self.db, config.tenantId, exclusive=True) as session:
            row = session.get(Organization, config.tenantId)
            if row:
                if row.region != config.region:
                    raise DomainError("TENANT_REGION_IMMUTABLE")
                old = TenantConfig.model_validate(row.config)
                if old.policyVersion == config.policyVersion and old.model_dump(
                    exclude={"simulationEnabled"}
                ) != config.model_dump(exclude={"simulationEnabled"}):
                    raise DomainError("POLICY_VERSION_REQUIRED")
                row.config = config.model_dump(mode="json")
            else:
                session.add(
                    Organization(
                        id=config.tenantId,
                        region=config.region,
                        config=config.model_dump(mode="json"),
                    )
                )
            scope = Scope(
                tenantId=config.tenantId,
                region=config.region,
                customerRef="system",
                purpose="cart_recovery",
                correlationId=str(uuid4()),
                workflowId=digest([config.tenantId, "policy"]),
                policyVersion=config.policyVersion,
                actor=actor,
            )
            journal(session, scope, "tenant.policy", "CONFIGURED")

    def observe(self, tenant: str, wid: str) -> str:
        with unit(self.db, tenant) as session:
            w = self._workflow(session, tenant, wid)
            if w.state not in FINAL:
                for action in session.scalars(
                    select(Action).where(Action.tenant == tenant, Action.workflow == wid)
                ):
                    if (
                        action.state == "AWAITING_APPROVAL"
                        and action.approval_expires
                        and aware(action.approval_expires) <= now()
                    ):
                        action.state, action.reason = "EXPIRED", "APPROVAL_EXPIRED"
                if aware(w.deadline) <= now():
                    w.state, w.reason = "EXPIRED", "WINDOW_EXPIRED"
                else:
                    self._rollup(session, w)
            return w.state

    def config(self, session: Session, tenant: str, region: str) -> TenantConfig:
        row = session.get(Organization, tenant)
        if not row:
            raise DomainError("TENANT_NOT_PROVISIONED", 404)
        config = TenantConfig.model_validate(row.config)
        if config.region != region or region != self.region:
            raise DomainError("REGION_DENIED", 403)
        if not config.enabled:
            raise DomainError("TENANT_DISABLED", 403)
        return config

    @staticmethod
    def scope(w: Workflow, actor: str = "enterprise-worker") -> Scope:
        return Scope(
            tenantId=w.tenant,
            region=cast(Region, w.region),
            customerRef=w.customer,
            purpose=cast(Purpose, w.purpose),
            correlationId=w.correlation,
            workflowId=w.id,
            policyVersion=w.policy,
            actor=actor,
        )

    def fixture(self, identity: Principal, context: CustomerContext) -> None:
        with unit(self.db, identity.tenant, context.customerRef) as session:
            self.config(session, identity.tenant, identity.region)
            if context.region != identity.region:
                raise DomainError("REGION_DENIED", 403)
            row = session.get(CustomerFixture, (identity.tenant, context.customerRef))
            if row:
                row.context = context.model_dump(mode="json")
            else:
                session.add(
                    CustomerFixture(
                        tenant=identity.tenant,
                        customer=context.customerRef,
                        context=context.model_dump(mode="json"),
                    )
                )

    def context(self, session: Session, w: Workflow) -> CustomerContext:
        if self.context_resolver is not None:
            context = CustomerContext.model_validate(
                self.context_resolver.read(self.scope(w)).model_dump()
            )
        else:
            row = session.get(CustomerFixture, (w.tenant, w.customer))
            context = (
                CustomerContext.model_validate(row.context)
                if row
                else CustomerContext(
                    customerRef=w.customer,
                    region=cast(Region, w.region),
                    observedAt=now(),
                    identityKnown=False,
                    sourceAvailable=False,
                )
            )
        if context.region != w.region or context.customerRef != w.customer:
            raise DomainError("CONTEXT_SCOPE_MISMATCH", 403)
        recent = session.scalar(
            select(OrderEvidence.order_ref)
            .where(
                OrderEvidence.tenant == w.tenant,
                OrderEvidence.customer == w.customer,
                OrderEvidence.occurred >= now() - timedelta(hours=72),
            )
            .limit(1)
        )
        context.ordered |= bool(recent)
        return context

    def record_order(
        self, tenant: str, region: Region, customer: str, order_ref: str, occurred: datetime
    ) -> bool:
        if occurred.tzinfo is None or occurred > now() + timedelta(minutes=5):
            raise DomainError("ORDER_TIME_INVALID", 422)
        with unit(self.db, tenant, customer) as session:
            config = self.config(session, tenant, region)
            existing = session.get(OrderEvidence, (tenant, order_ref))
            if existing:
                if existing.customer != customer:
                    raise DomainError("ORDER_IDENTITY_CONFLICT")
                return False
            session.add(
                OrderEvidence(
                    tenant=tenant, order_ref=order_ref, customer=customer, occurred=occurred
                )
            )
            scope = Scope(
                tenantId=tenant,
                region=region,
                customerRef=customer,
                purpose="cart_recovery",
                correlationId=str(uuid4()),
                workflowId=digest([tenant, order_ref]),
                policyVersion=config.policyVersion,
                actor="shopify-webhook",
            )
            journal(session, scope, "order.observed", "AUTHORITATIVE_ORDER")
        return True

    def killed(self, session: Session, config: TenantConfig) -> bool:
        org = session.get(Organization, config.tenantId)
        legacy = session.get(Tenant, config.tenantId)
        global_control = session.get(Tenant, "__global__")
        return bool(
            (org and org.killed)
            or (legacy and legacy.killed)
            or (global_control and global_control.killed)
        )

    def ingest(self, identity: Principal, event: SignalEvent) -> dict[str, Any]:
        if event.tenantId != identity.tenant or event.region != identity.region:
            raise DomainError("TENANT_OR_REGION_MISMATCH", 403)
        purpose = SIGNAL_PURPOSE[event.signal]
        if purpose not in identity.purposes:
            raise DomainError("PURPOSE_DENIED", 403)
        if event.occurredAt > now() + timedelta(minutes=5):
            raise DomainError("EVENT_TIME_IN_FUTURE", 422)
        wid = digest([event.tenantId, event.region, event.signal, event.aggregateId, purpose])
        with unit(self.db, identity.tenant, event.customerRef) as session:
            config = self.config(session, identity.tenant, event.region)
            if purpose not in config.allowedPurposes:
                raise DomainError("PURPOSE_DENIED", 403)
            receipt = session.get(Receipt, (identity.tenant, str(event.eventId)))
            if receipt:
                if receipt.digest != digest(event.model_dump(mode="json")):
                    raise DomainError("EVENT_ID_CONFLICT")
                return {"workflowId": receipt.workflow, "duplicate": True}
            if self.db.dialect.name == "postgresql":
                session.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:tenant,3))"),
                    {"tenant": identity.tenant},
                )
            minute = int(now().timestamp()) // 60
            bucket = session.get(IngestWindow, (identity.tenant, minute))
            if bucket is None:
                bucket = IngestWindow(tenant=identity.tenant, minute=minute, count=0)
                session.add(bucket)
            if bucket.count >= config.signalsPerMinute:
                raise DomainError("TENANT_INGEST_RATE_LIMIT", 429)
            bucket.count += 1
            w = session.get(Workflow, (identity.tenant, wid))
            if w and w.customer != event.customerRef:
                raise DomainError("AGGREGATE_CUSTOMER_MISMATCH")
            if not w:
                if self.db.dialect.name == "postgresql":
                    session.execute(
                        text("SELECT pg_advisory_xact_lock(hashtextextended(:tenant,3))"),
                        {"tenant": identity.tenant},
                    )
                pending = (
                    session.scalar(
                        select(func.count())
                        .select_from(Workflow)
                        .where(Workflow.tenant == identity.tenant, Workflow.state.not_in(FINAL))
                    )
                    or 0
                )
                if pending >= config.maxPending:
                    raise DomainError("TENANT_BACKPRESSURE", 429)
                w = Workflow(
                    tenant=identity.tenant,
                    id=wid,
                    region=event.region,
                    customer=event.customerRef,
                    purpose=purpose,
                    aggregate=event.aggregateId,
                    signal=event.signal,
                    source=event.source,
                    event_id=str(event.eventId),
                    correlation=str(event.correlationId),
                    policy=config.policyVersion,
                    state="RECEIVED",
                    deadline=event.occurredAt + timedelta(hours=72),
                )
                session.add(w)
                session.add(
                    Outbox(
                        tenant=identity.tenant,
                        id=wid,
                        region=event.region,
                        workflow=wid,
                        event=event.model_dump(mode="json"),
                    )
                )
                journal(session, self.scope(w, identity.subject), "event.accepted", "RECEIVED")
            session.add(
                Receipt(
                    tenant=identity.tenant,
                    id=str(event.eventId),
                    digest=digest(event.model_dump(mode="json")),
                    workflow=wid,
                )
            )
        return {"workflowId": wid, "duplicate": False}

    def _workflow(self, session: Session, tenant: str, wid: str) -> Workflow:
        w = session.get(Workflow, (tenant, wid))
        if not w:
            raise DomainError("NOT_FOUND", 404)
        self.config(session, tenant, w.region)
        return w

    def plan(self, tenant: str, wid: str, actor: str = "enterprise-worker") -> dict[str, Any]:
        # Locate customer under RLS first; then acquire only that customer's execution guard.
        with unit(self.db, tenant) as session:
            customer = self._workflow(session, tenant, wid).customer
        with unit(self.db, tenant, customer) as session:
            w = self._workflow(session, tenant, wid)
            if w.decision:
                return dict(w.decision)
            config = self.config(session, tenant, w.region)
            context = self.context(session, w)
            plan = build(w.signal, w.purpose, context, config, self.gateway)
            experiment = f"{w.purpose}:{w.policy}"
            assigned = session.get(Assignment, (tenant, experiment, customer))
            if not assigned:
                arm = (
                    "treatment"
                    if w.purpose == "service_recovery"
                    else (
                        "control"
                        if int(digest([tenant, customer, experiment])[:16], 16) / 2**64
                        < config.holdoutFraction
                        else "treatment"
                    )
                )
                assigned = Assignment(
                    tenant=tenant, experiment=experiment, customer=customer, arm=arm
                )
                session.add(assigned)
            arm = cast(Any, assigned.arm)
            decision = Decision(
                requestedBy=actor,
                workflowId=wid,
                policyVersion=w.policy,
                arm=arm,
                contextHash=digest(context.model_dump(mode="json")),
                identityVersion=context.identityVersion,
                candidates=plan.candidates,
                agents=plan.agents,
            )
            w.decision = decision.model_dump(mode="json")
            w.plan_hash = digest(w.decision)
            for candidate in plan.candidates:
                key = digest(
                    [tenant, wid, candidate.domain, candidate.tool, candidate.parameters, w.policy]
                )
                state = (
                    "SUPPRESSED"
                    if candidate.disposition == "suppressed"
                    else "HOLDOUT"
                    if (arm == "control" and candidate.domain != "Service")
                    else "AWAITING_APPROVAL"
                    if (candidate.domain in config.requireApproval)
                    else "PLANNED"
                )
                session.add(
                    Action(
                        tenant=tenant,
                        id=key,
                        workflow=wid,
                        customer=customer,
                        domain=candidate.domain,
                        tool=candidate.tool,
                        parameters=candidate.parameters,
                        state=state,
                        reason=candidate.reasonCodes[0],
                        approval_expires=now() + timedelta(hours=1)
                        if state == "AWAITING_APPROVAL"
                        else None,
                    )
                )
            if aware(w.deadline) <= now():
                w.state, w.reason = "EXPIRED", "WINDOW_EXPIRED"
            elif self.killed(session, config):
                w.state, w.reason = "SUPPRESSED", "KILL_SWITCH"
            else:
                w.state = "PLANNED"
            for agent in plan.agents:
                journal(session, self.scope(w), f"agent.{agent['domain']}", "COMPLETED")
            journal(session, self.scope(w), "plan.recorded", w.state)
            session.flush()
            self._rollup(session, w)
            return dict(w.decision)

    def _rollup(self, session: Session, w: Workflow) -> None:
        if w.state in {"CANCELLED", "EXPIRED", "SUPPRESSED"}:
            return
        actions = list(
            session.scalars(
                select(Action).where(Action.tenant == w.tenant, Action.workflow == w.id)
            )
        )
        states = {a.state for a in actions}
        if "AWAITING_APPROVAL" in states:
            w.state = "APPROVAL_PENDING"
        elif states & {"RECONCILING", "FAILED_REVIEW", "REJECTED"}:
            w.state = "FAILED_REVIEW"
        elif states & {"RETRY_PENDING", "PLANNED", "EXECUTING"}:
            w.state = "EXECUTING"
        elif "ACCEPTED" in states:
            w.state = "COMPLETED"
        elif states == {"EXPIRED"}:
            w.state = "EXPIRED"
        elif states == {"CANCELLED"}:
            w.state = "CANCELLED"
        elif states == {"HOLDOUT"}:
            w.state = "HOLDOUT"
        elif "DRY_RUN" in states:
            w.state = "DRY_RUN"
        else:
            w.state = "SUPPRESSED"

    def _denied(
        self,
        session: Session,
        w: Workflow,
        a: Action,
        config: TenantConfig,
        context: CustomerContext,
    ) -> list[str]:
        denied = eligibility(context, w.purpose)
        if context.identityVersion != (w.decision or {}).get("identityVersion", "synthetic-v1"):
            denied.append("IDENTITY_CHANGED")
        if self.killed(session, config):
            denied.append("KILL_SWITCH")
        if w.policy != config.policyVersion:
            denied.append("POLICY_CHANGED")
        if w.purpose not in config.allowedPurposes or a.domain not in config.allowedDomains:
            denied.append("DOMAIN_OR_PURPOSE_DENIED")
        if TOOLS.get(a.domain) != a.tool:
            denied.append("TOOL_DENIED")
        if w.state in {"CANCELLED", "EXPIRED", "SUPPRESSED"} or aware(w.deadline) <= now():
            denied.append("WORKFLOW_NOT_EXECUTABLE")
        fresh = build(w.signal, w.purpose, context, config, DeterministicGateway(), assess=False)
        match = next(
            (c for c in fresh.candidates if c.tool == a.tool and c.parameters == a.parameters), None
        )
        if not match:
            denied.append("CANDIDATE_CHANGED")
        elif match.disposition != "eligible":
            denied.extend(match.reasonCodes)
        if a.domain in config.requireApproval and (
            a.approved_hash != w.plan_hash
            or not a.approval_expires
            or aware(a.approval_expires) <= now()
        ):
            denied.append("APPROVAL_REQUIRED")
        if a.tool in CONTACT_TOOLS:
            contacted = session.scalar(
                select(Action.id)
                .where(
                    Action.tenant == w.tenant,
                    Action.customer == w.customer,
                    Action.id != a.id,
                    Action.tool.in_(CONTACT_TOOLS),
                    Action.state.in_(["ACCEPTED", "RECONCILING", "EXECUTING"]),
                    Action.reserved >= now() - timedelta(hours=config.contactHours),
                )
                .limit(1)
            )
            if contacted:
                denied.append("FREQUENCY_CAP")
        return list(dict.fromkeys(denied))

    def _reserve(self, tenant: str, wid: str, action_id: str) -> bool:
        with unit(self.db, tenant) as session:
            w = self._workflow(session, tenant, wid)
            a = session.get(Action, (tenant, action_id))
            if (
                not a
                or a.workflow != wid
                or a.state in ACTION_FINAL
                or a.state == "AWAITING_APPROVAL"
            ):
                return False
            config = self.config(session, tenant, w.region)
            if not a.reserved:
                if self.db.dialect.name == "postgresql":
                    session.execute(
                        text("SELECT pg_advisory_xact_lock(hashtextextended(:tenant,3))"),
                        {"tenant": tenant},
                    )
                count = (
                    session.scalar(
                        select(func.count())
                        .select_from(Action)
                        .where(
                            Action.tenant == tenant, Action.reserved >= now() - timedelta(hours=1)
                        )
                    )
                    or 0
                )
                if count >= config.actionsPerHour:
                    a.state, a.reason = "RETRY_PENDING", "ACTION_QUOTA"
                    journal(session, self.scope(w), "action.quota", "ACTION_QUOTA")
                    return False
                a.reserved = now()
            journal(session, self.scope(w), "action.intent", "RECORDED")
            return True

    def execute(self, tenant: str, wid: str) -> dict[str, Any]:
        with unit(self.db, tenant) as session:
            w = self._workflow(session, tenant, wid)
            if not w.decision:
                raise DomainError("PLAN_REQUIRED")
            customer = w.customer
            ids = list(
                session.scalars(
                    select(Action.id)
                    .where(Action.tenant == tenant, Action.workflow == wid)
                    .order_by(Action.id)
                )
            )
        for action_id in ids:
            if not self._reserve(tenant, wid, action_id):
                continue
            with unit(self.db, tenant, customer) as session:
                w = self._workflow(session, tenant, wid)
                a = session.get(Action, (tenant, action_id))
                if not a or a.state in ACTION_FINAL:
                    continue
                config = self.config(session, tenant, w.region)
                scope = self.scope(w)
                tool = cast(Tool, a.tool)
                try:
                    external = self.executor.status(scope, a.id, tool, a.parameters)
                except AmbiguousVendorError:
                    a.state, a.reason = "RECONCILING", "STATUS_UNKNOWN"
                    journal(session, scope, "action.reconcile", "STATUS_UNKNOWN")
                    continue
                except PermanentVendorError:
                    a.state, a.reason = "REJECTED", "CONNECTOR_REJECTED"
                    continue
                if external:
                    a.state, a.external_ref = "ACCEPTED", external
                    journal(session, scope, "action.reconciled", "ACCEPTED")
                    continue
                denied = self._denied(session, w, a, config, self.context(session, w))
                if denied:
                    a.state, a.reason = "SUPPRESSED", denied[0]
                    journal(session, scope, "action.denied", denied[0])
                    continue
                if not config.simulationEnabled:
                    a.state, a.reason = "DRY_RUN", "OBSERVE_ONLY"
                    journal(session, scope, "action.observe", "DRY_RUN")
                    continue
                if a.attempts >= 3:
                    a.state, a.reason = "FAILED_REVIEW", "ATTEMPTS_EXHAUSTED"
                    continue
                validate_parameters(a.tool, a.parameters)
                a.attempts += 1
                try:
                    external = self.executor.execute(scope, a.id, tool, a.parameters)
                except AmbiguousVendorError:
                    a.state, a.reason = "RECONCILING", "ACK_TIMEOUT"
                except RetryableVendorError:
                    a.state = "RETRY_PENDING" if a.attempts < 3 else "FAILED_REVIEW"
                    a.reason = "VENDOR_UNAVAILABLE"
                except PermanentVendorError:
                    a.state, a.reason = "REJECTED", "VENDOR_REJECTED"
                else:
                    a.state, a.external_ref = "ACCEPTED", external
                journal(session, scope, "action.result", a.state)
        with unit(self.db, tenant, customer) as session:
            w = self._workflow(session, tenant, wid)
            self._rollup(session, w)
            return self._view(session, w)

    def approve(
        self, identity: Principal, wid: str, decision: str, plan_hash: str
    ) -> dict[str, Any]:
        if identity.identityType != "human" or identity.role != "admin":
            raise DomainError("HUMAN_ADMIN_REQUIRED", 403)
        with unit(self.db, identity.tenant, exclusive=True) as session:
            w = self._workflow(session, identity.tenant, wid)
            if w.plan_hash != plan_hash:
                raise DomainError("APPROVAL_PLAN_MISMATCH")
            if aware(w.deadline) <= now():
                raise DomainError("WORKFLOW_EXPIRED")
            if w.state != "APPROVAL_PENDING":
                raise DomainError("APPROVAL_NOT_PENDING")
            if identity.subject == (w.decision or {}).get("requestedBy", "enterprise-worker"):
                raise DomainError("SEPARATION_OF_DUTIES", 403)
            for a in session.scalars(
                select(Action).where(Action.tenant == identity.tenant, Action.workflow == wid)
            ):
                if a.state == "AWAITING_APPROVAL":
                    if a.approval_expires and aware(a.approval_expires) <= now():
                        raise DomainError("APPROVAL_EXPIRED")
                    a.state = "PLANNED" if decision == "approved" else "CANCELLED"
                    a.approved_hash = w.plan_hash
                    a.approver = identity.subject
                    a.approval_expires = now() + timedelta(hours=1)
            journal(session, self.scope(w, identity.subject), "approval.decision", decision)
            self._rollup(session, w)
            return self._view(session, w)

    def control(self, identity: Principal, wid: str, operation: str) -> dict[str, Any]:
        with unit(self.db, identity.tenant, exclusive=True) as session:
            w = self._workflow(session, identity.tenant, wid)
            if operation == "cancel":
                if w.state not in FINAL:
                    w.state = "CANCELLED"
            elif operation == "replay":
                if w.state != "FAILED_REVIEW":
                    raise DomainError("NOT_REPLAYABLE")
                for a in session.scalars(
                    select(Action).where(Action.tenant == w.tenant, Action.workflow == wid)
                ):
                    if a.state in {"FAILED_REVIEW", "RECONCILING", "RETRY_PENDING"}:
                        a.state, a.attempts = "PLANNED", 0
                w.state = "PLANNED"
                w.generation += 1
                event = SignalEvent.model_validate(
                    {
                        "eventId": str(uuid4()),
                        "tenantId": w.tenant,
                        "region": w.region,
                        "aggregateId": w.aggregate,
                        "customerRef": w.customer,
                        "signal": w.signal,
                        "occurredAt": now(),
                        "correlationId": w.correlation,
                        "source": w.source,
                    }
                )
                session.add(
                    Outbox(
                        tenant=w.tenant,
                        id=digest([wid, "replay", w.generation]),
                        region=w.region,
                        workflow=wid,
                        event=event.model_dump(mode="json"),
                    )
                )
            else:
                raise DomainError("CONTROL_DENIED", 403)
            journal(session, self.scope(w, identity.subject), f"workflow.{operation}", w.state)
            return self._view(session, w)

    def _view(self, session: Session, w: Workflow) -> dict[str, Any]:
        actions = list(
            session.scalars(
                select(Action).where(Action.tenant == w.tenant, Action.workflow == w.id)
            )
        )
        return {
            "workflowId": w.id,
            "generation": w.generation,
            "tenantId": w.tenant,
            "region": w.region,
            "customerRef": w.customer,
            "purpose": w.purpose,
            "signal": w.signal,
            "state": w.state,
            "correlationId": w.correlation,
            "policyVersion": w.policy,
            "planHash": w.plan_hash,
            "decision": w.decision,
            "createdAt": aware(w.created).isoformat(),
            "reasonCode": w.reason,
            "actions": [
                {
                    "actionId": a.id,
                    "domain": a.domain,
                    "tool": a.tool,
                    "state": a.state,
                    "reasonCode": a.reason,
                    "attempts": a.attempts,
                    "externalRef": a.external_ref,
                    "parameters": a.parameters,
                }
                for a in actions
            ],
        }

    def get(self, identity: Principal, wid: str) -> dict[str, Any]:
        with unit(self.db, identity.tenant) as session:
            self.config(session, identity.tenant, identity.region)
            w = self._workflow(session, identity.tenant, wid)
            if w.purpose not in identity.purposes:
                raise DomainError("PURPOSE_DENIED", 403)
            return self._view(session, w)

    def list_workflows(
        self, identity: Principal, cursor: str | None = None, limit: int = 50
    ) -> dict[str, Any]:
        with unit(self.db, identity.tenant) as session:
            self.config(session, identity.tenant, identity.region)
            query = select(Workflow).where(
                Workflow.tenant == identity.tenant, Workflow.purpose.in_(identity.purposes)
            )
            if cursor:
                query = query.where(Workflow.id > cursor)
            rows = list(session.scalars(query.order_by(Workflow.id).limit(limit + 1)))
            return {
                "items": [self._view(session, w) for w in rows[:limit]],
                "nextCursor": rows[limit - 1].id if len(rows) > limit else None,
            }

    def iter_audit(self, identity: Principal) -> Iterator[dict[str, Any]]:
        with unit(self.db, identity.tenant) as session:
            config = self.config(session, identity.tenant, identity.region)
            if not set(config.allowedPurposes).issubset(identity.purposes):
                raise DomainError("AUDIT_SCOPE_REQUIRED", 403)
            high = (
                session.scalar(
                    select(func.max(Journal.sequence)).where(Journal.tenant == identity.tenant)
                )
                or 0
            )
        cursor = 0
        while cursor < high:
            batch = []
            with unit(self.db, identity.tenant) as session:
                self.config(session, identity.tenant, identity.region)
                records = session.scalars(
                    select(Journal)
                    .where(
                        Journal.tenant == identity.tenant,
                        Journal.sequence > cursor,
                        Journal.sequence <= high,
                    )
                    .order_by(Journal.sequence)
                    .limit(500)
                )
                for record in records:
                    fields = {
                        name: getattr(record, name)
                        for name in (
                            "tenant",
                            "sequence",
                            "correlation",
                            "workflow",
                            "actor",
                            "operation",
                            "outcome",
                            "policy",
                            "purpose",
                            "region",
                            "previous_hash",
                            "record_hash",
                        )
                    }
                    fields["created"] = aware(record.created).isoformat()
                    batch.append(fields)
            if not batch:
                break
            yield from batch
            cursor = int(batch[-1]["sequence"])

    def audit_export(self, identity: Principal) -> list[dict[str, Any]]:
        return list(self.iter_audit(identity))
