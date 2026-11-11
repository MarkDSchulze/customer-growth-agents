import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from jwt import PyJWKClient
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from growth.auth import Identity, require
from growth.config import Settings, settings
from growth.contracts import (
    ActionIntent,
    ApprovalCommand,
    DecisionRequest,
    Event,
    FaultCommand,
    KillCommand,
    Snapshot,
)
from growth.db import Audit, Base, VendorBase, VendorFault, engine, transaction
from growth.engine import DomainError, GrowthEngine
from growth.policy import Policy
from growth.telemetry import configure

logger = logging.getLogger("growth")
REQUESTS = Counter("growth_http_requests_total", "Requests", ["method", "status"])
LATENCY = Histogram("growth_http_seconds", "Request latency")


def create_app(config: Settings | None = None, core: GrowthEngine | None = None) -> FastAPI:
    configure()
    config = config or settings()
    if core is None:
        db, vendor_db = engine(config.database_url), engine(config.vendor_database_url)
        core = GrowthEngine(db, vendor_db, Policy.load(config.policy_path))
    growth = core

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Local bootstrap only. Docker/CI use the versioned migrate command first.
        if growth.db.dialect.name == "sqlite":
            Base.metadata.create_all(growth.db)
            VendorBase.metadata.create_all(growth.vendor_db)
        yield

    app = FastAPI(title="Customer Growth Agents", version="1.0.0", lifespan=lifespan)
    app.state.config = config
    app.state.engine = growth
    if config.oidc_issuer:
        if not config.oidc_jwks_url.startswith("https://"):
            raise ValueError("OIDC JWKS requires HTTPS")
        app.state.jwks = PyJWKClient(config.oidc_jwks_url)

    @app.middleware("http")
    async def telemetry(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        start = time.monotonic()
        try:
            correlation = str(UUID(request.headers.get("X-Correlation-ID", str(uuid4()))))
        except ValueError:
            return JSONResponse({"detail": "INVALID_CORRELATION_ID"}, status_code=400)
        request.state.correlation = correlation
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        REQUESTS.labels(request.method, str(response.status_code)).inc()
        LATENCY.observe(time.monotonic() - start)
        logger.info(
            "request",
            extra={
                "correlationId": correlation,
                "tenantId": getattr(request.state, "tenant", None),
                "purpose": "cart_recovery",
                "status": response.status_code,
            },
        )
        return response

    @app.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse({"detail": exc.code}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Omit rejected inputs to keep secrets and PII out of responses.
        return JSONResponse({"detail": "CONTRACT_VALIDATION_FAILED"}, status_code=422)

    @app.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "ok", "mode": "synthetic"}

    @app.get("/readyz")
    def ready() -> dict[str, str]:
        try:
            with growth.db.connect() as conn:
                conn.execute(text("SELECT 1"))
            with growth.vendor_db.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception:
            raise HTTPException(503, "DATABASE_UNAVAILABLE") from None
        if not config.oidc_issuer and len(config.auth_secret) < 32:
            raise HTTPException(503, "AUTH_NOT_CONFIGURED")
        return {"status": "ready", "execution": config.execution}

    @app.get("/metrics")
    def metrics(identity: Identity) -> Response:
        require(identity, "admin", "operator")
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/v1/status")
    def status(identity: Identity) -> dict[str, Any]:
        with transaction(growth.db, identity.tenant) as session:
            return {
                "tenantId": identity.tenant,
                "killSwitch": growth._killed(session, identity.tenant),
                "mode": "synthetic",
                "execution": config.execution,
                "policy": growth.policy.model_dump(),
            }

    @app.post("/v1/events", status_code=202)
    def ingest(event: Event, identity: Identity) -> dict[str, Any]:
        require(identity, "producer", "admin")
        result = growth.ingest(identity.tenant, event)
        if config.execution == "inline" and result.get("workflowId"):
            workflow_id = result["workflowId"]
            growth.plan(identity.tenant, workflow_id)
            for _ in range(growth.policy.maxAttempts):
                action = growth.execute(identity.tenant, ActionIntent(workflowId=workflow_id))
                if action["state"] != "RETRY_PENDING":
                    break
        return result

    @app.get("/v1/workflows")
    def workflows(identity: Identity) -> list[dict[str, Any]]:
        require(identity, "viewer", "operator", "admin")
        return growth.rows(identity.tenant, "workflow")

    @app.get("/v1/workflows/{workflow_id}")
    def workflow(workflow_id: str, identity: Identity) -> dict[str, Any]:
        require(identity, "viewer", "operator", "admin")
        return growth.get(identity.tenant, "workflow", workflow_id)

    @app.post("/v1/workflows/{workflow_id}/cancel")
    def cancel(workflow_id: str, identity: Identity) -> dict[str, Any]:
        require(identity, "operator", "admin")
        return growth.cancel(identity.tenant, workflow_id, identity.subject)

    @app.post("/v1/workflows/{workflow_id}/replay")
    def replay(workflow_id: str, identity: Identity) -> dict[str, Any]:
        require(identity, "operator", "admin")
        return growth.replay(identity.tenant, workflow_id, identity.subject)

    @app.post("/v1/approvals/{workflow_id}/decisions")
    def approval(workflow_id: str, body: ApprovalCommand, identity: Identity) -> dict[str, Any]:
        require(identity, "admin")
        if identity.identityType != "human":
            raise HTTPException(403, "HUMAN_IDENTITY_REQUIRED")
        return growth.approve(identity.tenant, workflow_id, body.decision, identity.subject)

    @app.get("/v1/dlq")
    def dlq(identity: Identity) -> list[dict[str, Any]]:
        require(identity, "operator", "admin")
        return growth.rows(identity.tenant, "dlq")

    @app.post("/v1/decisions")
    def decide(body: DecisionRequest, identity: Identity) -> dict[str, Any]:
        require(identity, "operator", "admin")
        return growth.plan(identity.tenant, body.workflowId)

    @app.get("/v1/decisions/{workflow_id}")
    def decision(workflow_id: str, identity: Identity) -> dict[str, Any]:
        require(identity, "viewer", "operator", "admin")
        return growth.get(identity.tenant, "decision", workflow_id)

    @app.post("/v1/actions")
    def act(body: ActionIntent, request: Request, identity: Identity) -> dict[str, Any]:
        require(identity, "operator", "admin")
        if request.headers.get("Idempotency-Key") != body.workflowId:
            raise HTTPException(400, "IDEMPOTENCY_KEY_MUST_MATCH_WORKFLOW")
        return growth.execute(identity.tenant, body)

    @app.get("/v1/actions/{workflow_id}")
    def action(workflow_id: str, identity: Identity) -> dict[str, Any]:
        require(identity, "viewer", "operator", "admin")
        return growth.get(identity.tenant, "action", workflow_id)

    @app.get("/v1/customers/{customer_id}/context")
    def context(customer_id: str, cartId: str, identity: Identity) -> dict[str, Any]:
        require(identity, "operator", "admin")
        with transaction(growth.db, identity.tenant) as session:
            return growth.context.read(session, identity.tenant, customer_id, cartId).model_dump()

    @app.put("/v1/control/kill-switch")
    def kill(body: KillCommand, request: Request, identity: Identity) -> dict[str, bool]:
        require(identity, "admin")
        growth.kill(identity.tenant, body.enabled, identity.subject, request.state.correlation)
        return {"enabled": body.enabled}

    @app.put("/v1/control/global-kill-switch")
    def global_kill(body: KillCommand, request: Request, identity: Identity) -> dict[str, bool]:
        require(identity, "platform_admin")
        growth.kill("__global__", body.enabled, identity.subject, request.state.correlation)
        return {"enabled": body.enabled}

    @app.get("/v1/audit")
    def audit(identity: Identity, correlationId: str | None = None) -> list[dict[str, Any]]:
        require(identity, "viewer", "operator", "admin")
        with transaction(growth.db, identity.tenant) as session:
            query = select(Audit).where(Audit.tenant == identity.tenant)
            if correlationId:
                query = query.where(Audit.correlation == correlationId)
            return [
                {
                    "sequence": a.seq,
                    "correlationId": a.correlation,
                    "workflowId": a.workflow,
                    "operation": a.operation,
                    "outcome": a.outcome,
                    "actor": a.actor,
                    "policyVersion": a.policy,
                    "purpose": a.purpose,
                    "at": a.created.isoformat(),
                }
                for a in session.scalars(query.order_by(Audit.seq.desc()).limit(500))
            ]

    @app.get("/v1/experiments/report")
    def report(identity: Identity) -> dict[str, Any]:
        require(identity, "viewer", "operator", "admin")
        return growth.report(identity.tenant)

    @app.put("/v1/simulation/context")
    def mock_context(body: Snapshot, identity: Identity) -> dict[str, str]:
        require(identity, "admin")
        growth.source(identity.tenant, body)
        return {"status": "synthetic_context_updated"}

    @app.post("/v1/simulation/enable")
    def simulation(identity: Identity) -> dict[str, str]:
        require(identity, "admin")
        growth.enable_simulation(identity.tenant)
        return {"status": "mock_execution_enabled"}

    @app.put("/v1/simulation/vendor-fault")
    def fault(body: FaultCommand, identity: Identity) -> dict[str, str]:
        require(identity, "admin")
        with Session(growth.vendor_db) as session, session.begin():
            session.merge(VendorFault(tenant=identity.tenant, mode=body.mode))
        return {"mode": body.mode}

    return app


app = create_app()
