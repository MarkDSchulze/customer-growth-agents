from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from growth.auth import Identity, require
from growth.engine import DomainError
from growth.enterprise.contracts import (
    ApprovalDecision,
    BudgetDraft,
    CustomerContext,
    IdentityBinding,
    SignalEvent,
    TenantConfig,
)
from growth.enterprise.service import EnterpriseService
from growth.enterprise.storage import unit


def routes(
    service: EnterpriseService,
    execution: str,
    source_bindings: str = "{}",
    runtime_mode: str = "development",
) -> APIRouter:
    router = APIRouter(prefix="/v2", tags=["Enterprise orchestration"])

    @router.put("/tenants")
    def provision(body: TenantConfig, identity: Identity) -> dict[str, str]:
        require(identity, "platform_admin")
        service.provision(body, identity.subject)
        return {"tenantId": body.tenantId, "region": body.region}

    @router.put("/identity-bindings")
    def identity_binding(body: IdentityBinding, identity: Identity) -> dict[str, str]:
        require(identity, "admin")
        from uuid import uuid4

        from growth.enterprise.contracts import Scope
        from growth.enterprise.models import IdentityRecord
        from growth.enterprise.storage import digest, journal

        with unit(service.db, identity.tenant, body.customerRef) as session:
            config = service.config(session, identity.tenant, identity.region)
            if body.region != identity.region:
                raise DomainError("REGION_DENIED", 403)
            session.merge(
                IdentityRecord(
                    tenant=identity.tenant,
                    customer=body.customerRef,
                    shopify_customer=body.shopifyCustomer,
                    binding=body.model_dump(mode="json"),
                )
            )
            scope = Scope(
                tenantId=identity.tenant,
                region=identity.region,
                customerRef=body.customerRef,
                purpose="cart_recovery",
                correlationId=str(uuid4()),
                workflowId=digest([identity.tenant, body.customerRef, "identity"]),
                policyVersion=config.policyVersion,
                actor=identity.subject,
            )
            journal(session, scope, "identity.binding", "UPDATED")
        return {"status": "IDENTITY_BINDING_UPDATED"}

    @router.post("/webhooks/shopify/orders", status_code=202)
    async def shopify_order(request: Request) -> dict[str, Any]:
        from growth.adapters import PermanentVendorError

        if service.connector_registry is None:
            raise DomainError("WEBHOOK_CONNECTOR_NOT_CONFIGURED", 404)
        payload = bytearray()
        async for chunk in request.stream():
            payload.extend(chunk)
            if len(payload) > 65536:
                raise DomainError("SOURCE_MESSAGE_TOO_LARGE", 413)
        try:
            profile, order, occurred = service.connector_registry.authenticate_order(
                request.headers.get("X-Shopify-Shop-Domain", ""),
                request.headers.get("X-Shopify-Hmac-Sha256", ""),
                bytes(payload),
            )
        except (ValueError, KeyError, TypeError, PermanentVendorError):
            raise DomainError("SOURCE_SIGNATURE_OR_CONTRACT_DENIED", 401) from None
        accepted = service.record_order(
            profile.tenantId, profile.region, profile.customerRef, order, occurred
        )
        return {"accepted": accepted, "duplicate": not accepted}

    @router.post("/simulation/demo")
    def demo(identity: Identity) -> dict[str, Any]:
        require(identity, "admin")
        if runtime_mode != "development":
            raise DomainError("SYNTHETIC_FIXTURE_API_DISABLED", 403)
        from growth.enterprise.demo import seed

        return {"workflows": seed(service, identity, execution)}

    @router.get("/tenant")
    def tenant(identity: Identity) -> dict[str, Any]:
        require(identity, "viewer", "operator", "admin", "platform_admin")
        with unit(service.db, identity.tenant) as session:
            config = service.config(session, identity.tenant, identity.region)
            return {
                **config.model_dump(),
                "killSwitch": service.killed(session, config),
                "runtimeRegion": service.region,
                "execution": execution,
                "liveActionsEnabled": False,
            }

    @router.put("/simulation/context")
    def fixture(body: CustomerContext, identity: Identity) -> dict[str, str]:
        require(identity, "admin")
        if runtime_mode != "development":
            raise DomainError("SYNTHETIC_FIXTURE_API_DISABLED", 403)
        service.fixture(identity, body)
        return {"status": "SYNTHETIC_CONTEXT_UPDATED"}

    @router.post("/events", status_code=202)
    def ingest(body: SignalEvent, identity: Identity) -> dict[str, Any]:
        require(identity, "producer", "admin")
        import json

        binding = json.loads(source_bindings).get(body.source)
        if (
            not binding
            or binding.get("tenantId") != identity.tenant
            or binding.get("region") != identity.region
        ):
            raise DomainError("SOURCE_BINDING_DENIED", 403)
        result = service.ingest(identity, body)
        if execution == "inline":
            service.plan(identity.tenant, result["workflowId"])
            service.execute(identity.tenant, result["workflowId"])
        return result

    @router.get("/workflows")
    def workflows(
        identity: Identity,
        cursor: str | None = None,
        limit: int = Query(default=50, ge=1, le=200),
        state: str | None = Query(
            default=None,
            pattern=(
                "^(RECEIVED|PLANNED|EXECUTING|APPROVAL_PENDING|COMPLETED|SUPPRESSED|"
                "HOLDOUT|CANCELLED|EXPIRED|FAILED_REVIEW|DRY_RUN)$"
            ),
        ),
        customer: str | None = Query(default=None, min_length=1, max_length=96),
    ) -> dict[str, Any]:
        require(identity, "viewer", "operator", "admin")
        return service.list_workflows(identity, cursor, limit, state, customer)

    @router.get("/workflows/{wid}")
    def workflow(wid: str, identity: Identity) -> dict[str, Any]:
        require(identity, "viewer", "operator", "admin")
        return service.get(identity, wid)

    @router.post("/workflows/{wid}/plan")
    def plan(wid: str, identity: Identity) -> dict[str, Any]:
        require(identity, "operator", "admin")
        service.get(identity, wid)
        return service.plan(identity.tenant, wid, identity.subject)

    @router.post("/workflows/{wid}/execute")
    def execute(wid: str, identity: Identity, request: Request) -> dict[str, Any]:
        require(identity, "operator", "admin")
        service.get(identity, wid)
        if request.headers.get("Idempotency-Key") != wid:
            raise DomainError("IDEMPOTENCY_KEY_MUST_MATCH_WORKFLOW", 400)
        return service.execute(identity.tenant, wid)

    @router.post("/workflows/{wid}/approval")
    def approve(wid: str, body: ApprovalDecision, identity: Identity) -> dict[str, Any]:
        service.get(identity, wid)
        return service.approve(identity, wid, body.decision, body.planHash)

    @router.post("/workflows/{wid}/cancel")
    def cancel(wid: str, identity: Identity) -> dict[str, Any]:
        require(identity, "operator", "admin")
        service.get(identity, wid)
        return service.control(identity, wid, "cancel")

    @router.post("/workflows/{wid}/replay")
    def replay(wid: str, identity: Identity) -> dict[str, Any]:
        require(identity, "operator", "admin")
        service.get(identity, wid)
        return service.control(identity, wid, "replay")

    @router.get("/audit/export")
    def audit(identity: Identity) -> StreamingResponse:
        import json

        require(identity, "admin", "operator")
        records = service.iter_audit(identity)
        # Begin iteration before sending headers so authorization failures remain a JSON 403.
        first = next(records, None)

        def lines() -> Iterator[str]:
            if first is not None:
                yield json.dumps(first, sort_keys=True) + "\n"
            for record in records:
                yield json.dumps(record, sort_keys=True) + "\n"

        return StreamingResponse(
            lines(),
            media_type="application/x-ndjson",
            headers={"Content-Disposition": 'attachment; filename="growth-audit.ndjson"'},
        )

    @router.post("/advertising/budget-drafts")
    def budget_draft(body: BudgetDraft, identity: Identity) -> dict[str, Any]:
        require(identity, "operator", "admin")
        if "audience_activation" not in identity.purposes:
            raise DomainError("PURPOSE_DENIED", 403)
        with unit(service.db, identity.tenant) as session:
            service.config(session, identity.tenant, identity.region)
        from growth.enterprise.budgets import recommend

        return recommend(body)

    @router.get("/connectors")
    def connectors(identity: Identity) -> dict[str, Any]:
        require(identity, "admin", "operator")
        with unit(service.db, identity.tenant) as session:
            service.config(session, identity.tenant, identity.region)
        return {
            "liveActionsEnabled": False,
            "providers": service.connector_registry.capabilities(identity.tenant)
            if service.connector_registry
            else [
                {"provider": p, "configuredProfiles": 0, "mode": "synthetic"}
                for p in ["Salesforce", "Adobe Experience Platform", "Shopify"]
            ],
        }

    @router.get("/operations")
    def operations(identity: Identity) -> dict[str, Any]:
        require(identity, "admin", "operator")
        from sqlalchemy import func, select

        from growth.enterprise.models import Action, Outbox, Workflow

        with unit(service.db, identity.tenant) as session:
            service.config(session, identity.tenant, identity.region)
            counts = dict(
                session.execute(
                    select(Workflow.state, func.count())
                    .where(
                        Workflow.tenant == identity.tenant, Workflow.purpose.in_(identity.purposes)
                    )
                    .group_by(Workflow.state)
                ).all()
            )
            denied = dict(
                session.execute(
                    select(Action.reason, func.count())
                    .join(
                        Workflow,
                        (Workflow.tenant == Action.tenant) & (Workflow.id == Action.workflow),
                    )
                    .where(
                        Action.tenant == identity.tenant,
                        Workflow.purpose.in_(identity.purposes),
                        Action.state == "SUPPRESSED",
                    )
                    .group_by(Action.reason)
                ).all()
            )
            pending = session.scalar(
                select(func.count())
                .select_from(Outbox)
                .join(
                    Workflow, (Workflow.tenant == Outbox.tenant) & (Workflow.id == Outbox.workflow)
                )
                .where(
                    Outbox.tenant == identity.tenant,
                    Workflow.purpose.in_(identity.purposes),
                    Outbox.published.is_(False),
                )
            )
            action_counts = dict(
                session.execute(
                    select(Action.state, func.count())
                    .join(
                        Workflow,
                        (Workflow.tenant == Action.tenant) & (Workflow.id == Action.workflow),
                    )
                    .where(
                        Action.tenant == identity.tenant, Workflow.purpose.in_(identity.purposes)
                    )
                    .group_by(Action.state)
                ).all()
            )
            return {
                "actions": action_counts,
                "workflows": counts,
                "policyDenials": denied,
                "outboxPending": pending,
                "region": service.region,
                "policyAuthority": "deterministic",
            }

    return router
