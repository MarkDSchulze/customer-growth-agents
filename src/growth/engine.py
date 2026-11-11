import hashlib
import json
import math
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from growth.adapters import (
    AmbiguousVendorError,
    ContextAdapter,
    JourneyAdapter,
    MockContextAdapter,
    MockJourneyAdapter,
    PermanentVendorError,
    RetryableVendorError,
)
from growth.agents import AGENTS, AgentTask
from growth.contracts import ActionIntent, Event, Proposal, Snapshot
from growth.db import Audit, Row, Tenant, now, transaction
from growth.policy import Policy, assignment, authorize, reasons

TERMINAL = {
    "SUPPRESSED",
    "HOLDOUT",
    "COMPLETED",
    "EXPIRED",
    "CANCELLED",
    "FAILED_REVIEW",
    "DRY_RUN",
}


class DomainError(Exception):
    def __init__(self, code: str, status: int = 409):
        self.code = code
        self.status = status
        super().__init__(code)


class GrowthEngine:
    def __init__(self, db: Engine, vendor_db: Engine, policy: Policy):
        self.db = db
        self.vendor_db = vendor_db
        self.policy = policy
        self.context: ContextAdapter = MockContextAdapter()
        self.vendor: JourneyAdapter = MockJourneyAdapter(vendor_db)

    @staticmethod
    def put(session: Session, tenant: str, kind: str, key: str, data: dict[str, Any]) -> Row:
        row = session.get(Row, (tenant, kind, key))
        if row:
            row.data = dict(data)
        else:
            row = Row(tenant=tenant, kind=kind, id=key, data=dict(data))
            session.add(row)
        session.flush()
        return row

    def audit(
        self,
        session: Session,
        tenant: str,
        workflow: dict[str, Any],
        operation: str,
        outcome: str,
        actor: str = "workflow-worker",
    ) -> None:
        # Allowlisted metadata only: never log payloads, customer context, exceptions or tokens.
        session.add(
            Audit(
                tenant=tenant,
                correlation=workflow["correlationId"],
                workflow=workflow.get("workflowId", ""),
                operation=operation,
                outcome=outcome,
                actor=actor,
                policy=self.policy.version,
            )
        )

    def rows(self, tenant: str, kind: str) -> list[dict[str, Any]]:
        with transaction(self.db, tenant) as session:
            return [
                dict(r.data)
                for r in session.scalars(
                    select(Row).where(Row.tenant == tenant, Row.kind == kind).order_by(Row.created)
                ).all()
            ]

    def get(self, tenant: str, kind: str, key: str) -> dict[str, Any]:
        with transaction(self.db, tenant) as session:
            row = session.get(Row, (tenant, kind, key))
            if row is None:
                raise DomainError("NOT_FOUND", 404)
            return dict(row.data)

    def tenant(self, session: Session, tenant: str) -> Tenant:
        control = session.get(Tenant, tenant)
        if control is None:
            control = Tenant(id=tenant, killed=False)
            session.add(control)
            session.flush()
        return control

    def _killed(self, session: Session, tenant: str) -> bool:
        global_control = session.get(Tenant, "__global__")
        return self.tenant(session, tenant).killed or bool(global_control and global_control.killed)

    def source(self, tenant: str, snapshot: Snapshot) -> None:
        with transaction(self.db, tenant) as session:
            self.tenant(session, tenant)
            self.put(session, tenant, "mock_context", snapshot.cartId, snapshot.model_dump())

    def enable_simulation(self, tenant: str) -> None:
        with transaction(self.db, tenant) as session:
            self.tenant(session, tenant)
            self.put(session, tenant, "config", "simulation", {"enabled": True})
            self.audit(
                session,
                tenant,
                {"correlationId": str(uuid4())},
                "simulation.enabled",
                "MOCK_ONLY",
                "admin",
            )

    def kill(self, tenant: str, enabled: bool, actor: str, correlation: str) -> None:
        with transaction(self.db, tenant) as session:
            self.tenant(session, tenant).killed = enabled
            self.audit(
                session,
                tenant,
                {"correlationId": correlation},
                "kill_switch",
                "ENABLED" if enabled else "DISABLED",
                actor,
            )

    def ingest(self, tenant: str, event: Event) -> dict[str, Any]:
        if event.tenantId != tenant:
            raise DomainError("TENANT_MISMATCH", 403)
        if event.occurredAt > now() + timedelta(minutes=5):
            raise DomainError("EVENT_TIME_IN_FUTURE", 422)
        if event.eventType == "growth.action_executed.v1":
            raise DomainError("INTERNAL_EVENT_ONLY", 403)
        with transaction(self.db, tenant) as session:
            self.tenant(session, tenant)
            key = str(event.eventId)
            existing = session.get(Row, (tenant, "event", key))
            if existing:
                if existing.data["event"] != event.model_dump(mode="json"):
                    raise DomainError("EVENT_ID_CONFLICT")
                return {**existing.data["result"], "duplicate": True}
            payload = event.data
            workflow_id = hashlib.sha256(
                json.dumps([tenant, event.aggregateId, "cart_recovery"]).encode()
            ).hexdigest()
            result: dict[str, Any] = {"eventId": key, "duplicate": False}
            if event.eventType == "commerce.cart_abandoned.v1":
                result["workflowId"] = workflow_id
                if session.get(Row, (tenant, "workflow", workflow_id)) is None:
                    workflow = {
                        "workflowId": workflow_id,
                        "cartId": payload["cartId"],
                        "customerRef": payload["customerRef"],
                        "triggerEventId": key,
                        "correlationId": str(event.correlationId),
                        "state": "RECEIVED",
                        "reasonCodes": [],
                        "startedAt": now().isoformat(),
                        "eventTime": event.occurredAt.isoformat(),
                        "policyVersion": self.policy.version,
                        "purpose": "cart_recovery",
                        "region": event.region,
                    }
                    self.put(session, tenant, "workflow", workflow_id, workflow)
                    self.audit(session, tenant, workflow, "event.ingested", "RECEIVED")
                    self.put(
                        session,
                        tenant,
                        "outbox",
                        f"start-{workflow_id}",
                        {
                            "event": event.model_dump(mode="json"),
                            "workflowId": workflow_id,
                            "published": False,
                            "kind": "start",
                        },
                    )
            elif event.eventType == "commerce.order_placed.v1":
                prior = session.get(Row, (tenant, "order", payload["cartId"]))
                if prior and prior.data["customerRef"] != payload["customerRef"]:
                    raise DomainError("ORDER_CUSTOMER_MISMATCH")
                self.put(session, tenant, "order", payload["cartId"], payload)
                outcome = session.get(Row, (tenant, "outcome", payload["orderId"]))
                if outcome is None:
                    self.put(
                        session,
                        tenant,
                        "outcome",
                        payload["orderId"],
                        {
                            **payload,
                            "occurredAt": event.occurredAt.isoformat(),
                            "correlationId": str(event.correlationId),
                        },
                    )
                row = session.get(Row, (tenant, "workflow", workflow_id))
                if row and row.data["customerRef"] == payload["customerRef"]:
                    workflow = dict(row.data)
                    if workflow["state"] == "AWAITING_OUTCOME":
                        workflow["state"] = "COMPLETED"
                        workflow["completedAt"] = now().isoformat()
                        workflow["reasonCodes"] = ["ORDER_OBSERVED"]
                    elif workflow["state"] not in TERMINAL:
                        workflow["state"] = "SUPPRESSED"
                        workflow["reasonCodes"] = ["ORDER_COMPLETED"]
                    row.data = workflow
                    self.audit(session, tenant, workflow, "order.observed", workflow["state"])
            elif event.eventType == "service.case_escalated.v1":
                self.put(session, tenant, "case", payload["caseId"], payload)
            self.put(
                session,
                tenant,
                "event",
                key,
                {
                    "event": event.model_dump(mode="json"),
                    "result": result,
                },
            )
            self.audit(
                session,
                tenant,
                {"correlationId": str(event.correlationId)},
                "event.receipt",
                event.eventType,
            )
            return result

    def _frequency(self, session: Session, tenant: str, customer: str) -> bool:
        contacts = session.scalars(select(Row).where(Row.tenant == tenant, Row.kind == "action"))
        cutoff = now() - timedelta(hours=self.policy.frequencyHours)
        return any(
            r.data["customerRef"] == customer
            and r.data["state"] in {"ACCEPTED", "RECONCILING"}
            and datetime.fromisoformat(r.data["attemptedAt"]) >= cutoff
            for r in contacts
        )

    def _context(self, session: Session, tenant: str, w: dict[str, Any]) -> Snapshot:
        return self.context.read(session, tenant, w["customerRef"], w["cartId"])

    def plan(self, tenant: str, workflow_id: str) -> dict[str, Any]:
        with transaction(self.db, tenant) as session:
            row = session.get(Row, (tenant, "workflow", workflow_id))
            if row is None:
                raise DomainError("NOT_FOUND", 404)
            w = dict(row.data)
            existing = session.get(Row, (tenant, "decision", workflow_id))
            if existing:
                return dict(existing.data)
            snapshot = self._context(session, tenant, w)
            digest = hashlib.sha256(snapshot.model_dump_json().encode()).hexdigest()
            denied = reasons(
                snapshot,
                killed=self._killed(session, tenant),
                frequency=self._frequency(session, tenant, w["customerRef"]),
            )
            if w["state"] in TERMINAL and not denied:
                denied = ["WORKFLOW_TERMINAL"]
            if now() >= datetime.fromisoformat(w["eventTime"]) + timedelta(
                hours=self.policy.observationHours
            ):
                denied.append("WINDOW_EXPIRED")
            arm = None
            if not denied:
                arm_row = session.get(Row, (tenant, "assignment", w["customerRef"]))
                if arm_row:
                    arm = arm_row.data["arm"]
                else:
                    arm = assignment(tenant, w["customerRef"], self.policy)
                    self.put(
                        session,
                        tenant,
                        "assignment",
                        w["customerRef"],
                        {
                            "customerRef": w["customerRef"],
                            "arm": arm,
                            "experimentId": self.policy.experiment,
                            "assignedAt": now().isoformat(),
                        },
                    )
            proposals = [
                agent.propose(
                    AgentTask(
                        task_id=f"{workflow_id[:16]}-{agent.domain}",
                        tenant=tenant,
                        customer=w["customerRef"],
                        purpose="cart_recovery",
                        snapshot_hash=digest,
                        allowed_tools=tuple(self.policy.allowedTools[agent.domain]),
                    ),
                    snapshot,
                    self.policy,
                ).model_dump()
                for agent in AGENTS
            ]
            disposition = "suppressed" if denied else "holdout" if arm == "control" else "eligible"
            decision = {
                "decisionId": str(uuid4()),
                "workflowId": workflow_id,
                "disposition": disposition,
                "reasonCodes": denied
                or (["EXPERIMENT_CONTROL"] if arm == "control" else ["ELIGIBLE"]),
                "arm": arm,
                "policyVersion": self.policy.version,
                "rankerVersion": "deterministic-v1",
                "contextHash": digest,
                "proposals": proposals,
                "score": 0.72 if disposition == "eligible" else 0,
                "purpose": "cart_recovery",
            }
            w["state"] = {
                "suppressed": "SUPPRESSED",
                "holdout": "HOLDOUT",
                "eligible": "POLICY_CHECKED",
            }[disposition]
            w["reasonCodes"] = decision["reasonCodes"]
            if disposition == "eligible" and self.policy.requireApproval:
                w["state"] = "APPROVAL_PENDING"
                self.put(
                    session,
                    tenant,
                    "approval",
                    workflow_id,
                    {
                        "workflowId": workflow_id,
                        "state": "pending",
                        "expiresAt": (now() + timedelta(hours=1)).isoformat(),
                        "requestedBy": "workflow-worker",
                        "policyVersion": self.policy.version,
                    },
                )
            row.data = w
            self.put(session, tenant, "decision", workflow_id, decision)
            self.audit(session, tenant, w, "decision.recorded", disposition)
            for agent in AGENTS:
                self.audit(session, tenant, w, f"agent.{agent.domain}", "PROPOSED")
            return decision

    def execute(self, tenant: str, intent: ActionIntent) -> dict[str, Any]:
        # Commit request audit before external effects so crashes cannot erase intent.
        with transaction(self.db, tenant) as session:
            requested = session.get(Row, (tenant, "workflow", intent.workflowId))
            if requested is not None:
                self.audit(session, tenant, requested.data, "tool.request", "RECEIVED")
        with transaction(self.db, tenant) as session:
            row = session.get(Row, (tenant, "workflow", intent.workflowId))
            decision_row = session.get(Row, (tenant, "decision", intent.workflowId))
            if row is None or decision_row is None:
                raise DomainError("DECISION_REQUIRED")
            w = dict(row.data)
            decision = decision_row.data
            action_row = session.get(Row, (tenant, "action", intent.workflowId))
            action = (
                dict(action_row.data)
                if action_row
                else {
                    "actionId": str(uuid4()),
                    "workflowId": intent.workflowId,
                    "customerRef": w["customerRef"],
                    "tool": intent.tool,
                    "journeyId": intent.journeyId,
                    "purpose": intent.purpose,
                    "state": "PENDING",
                    "attempts": 0,
                    "externalRef": None,
                    "attemptedAt": now().isoformat(),
                    "idempotencyKey": intent.workflowId,
                    "decisionId": decision["decisionId"],
                    "policyVersion": self.policy.version,
                }
            )
            if intent.journeyId != self.policy.approvedJourney:
                self.audit(session, tenant, w, "tool.denied", "JOURNEY_NOT_APPROVED")
                return {"state": "REJECTED", "reasonCodes": ["JOURNEY_NOT_APPROVED"]}
            if action["state"] == "ACCEPTED":
                return action
            if w["state"] in TERMINAL:
                # Vendor acceptance can outlive a local rollback and a later order or cancellation.
                if decision["disposition"] == "eligible":
                    try:
                        external = self.vendor.status(tenant, intent.workflowId)
                    except AmbiguousVendorError:
                        external = None
                    if external:
                        return self._accepted(session, tenant, row, w, action, external)
                return w
            proposal = Proposal.model_validate(decision["proposals"][0])
            if decision["disposition"] != "eligible" or not authorize(proposal, self.policy):
                self.audit(session, tenant, w, "tool.denied", "POLICY_DENIED")
                return {"state": "REJECTED", "reasonCodes": ["POLICY_DENIED"]}
            if self.policy.requireApproval:
                approval = session.get(Row, (tenant, "approval", intent.workflowId))
                if not approval or approval.data["state"] != "approved":
                    self.audit(session, tenant, w, "tool.wait", "APPROVAL_REQUIRED")
                    return {"state": "APPROVAL_PENDING"}
                if now() >= datetime.fromisoformat(approval.data["expiresAt"]):
                    w["state"], w["reasonCodes"] = "EXPIRED", ["APPROVAL_EXPIRED"]
                    row.data = w
                    return w
            # Reconcile before retries, including after opt-out. Status queries send nothing.
            try:
                external = self.vendor.status(tenant, intent.workflowId)
            except AmbiguousVendorError:
                action["state"] = "RECONCILING"
                w["state"] = "FAILED_REVIEW"
                w["reasonCodes"] = ["STATUS_UNKNOWN"]
                return self._save_action(session, tenant, row, w, action)
            if external:
                return self._accepted(session, tenant, row, w, action, external)
            snapshot = self._context(session, tenant, w)
            denied = reasons(
                snapshot,
                killed=self._killed(session, tenant),
                frequency=self._frequency(session, tenant, w["customerRef"]),
            )
            if now() >= datetime.fromisoformat(w["eventTime"]) + timedelta(
                hours=self.policy.observationHours
            ):
                denied.append("WINDOW_EXPIRED")
            if denied:
                w["state"], w["reasonCodes"] = "SUPPRESSED", denied
                action["state"], action["reasonCodes"] = "SUPPRESSED", denied
                return self._save_action(session, tenant, row, w, action)
            simulation = session.get(Row, (tenant, "config", "simulation"))
            if not simulation or not simulation.data["enabled"]:
                w["state"], w["reasonCodes"] = "DRY_RUN", ["DRY_RUN"]
                action["state"] = "DRY_RUN"
                return self._save_action(session, tenant, row, w, action)
            if action["attempts"] >= self.policy.maxAttempts:
                w["state"], w["reasonCodes"] = "FAILED_REVIEW", ["ATTEMPTS_EXHAUSTED"]
                return self._save_action(session, tenant, row, w, action)
            action["attempts"] += 1
            action["attemptedAt"] = now().isoformat()
            self.audit(session, tenant, w, "tool.attempt", "MOCK_JOURNEY")
            try:
                external = self.vendor.trigger(tenant, intent.workflowId, intent.journeyId)
            except AmbiguousVendorError:
                try:
                    external = self.vendor.status(tenant, intent.workflowId)
                except AmbiguousVendorError:
                    external = None
                if external:
                    return self._accepted(session, tenant, row, w, action, external)
                action["state"] = "RECONCILING"
                w["state"], w["reasonCodes"] = "FAILED_REVIEW", ["STATUS_UNKNOWN"]
            except RetryableVendorError:
                action["state"] = "RETRY_PENDING"
                w["state"] = (
                    "RETRY_PENDING"
                    if action["attempts"] < self.policy.maxAttempts
                    else ("FAILED_REVIEW")
                )
                w["reasonCodes"] = ["VENDOR_UNAVAILABLE"]
            except PermanentVendorError:
                action["state"] = "REJECTED"
                w["state"], w["reasonCodes"] = "FAILED_REVIEW", ["VENDOR_REJECTED"]
            else:
                return self._accepted(session, tenant, row, w, action, external)
            return self._save_action(session, tenant, row, w, action)

    def _save_action(
        self, session: Session, tenant: str, row: Row, w: dict[str, Any], action: dict[str, Any]
    ) -> dict[str, Any]:
        row.data = w
        self.put(session, tenant, "action", w["workflowId"], action)
        self.audit(session, tenant, w, "action.state", action["state"])
        if w["state"] == "FAILED_REVIEW":
            self.put(
                session,
                tenant,
                "dlq",
                w["workflowId"],
                {
                    "workflowId": w["workflowId"],
                    "reasonCodes": w["reasonCodes"],
                    "resolved": False,
                },
            )
        return action

    def _accepted(
        self,
        session: Session,
        tenant: str,
        row: Row,
        w: dict[str, Any],
        action: dict[str, Any],
        external: str,
    ) -> dict[str, Any]:
        action["state"], action["externalRef"] = "ACCEPTED", external
        if session.get(Row, (tenant, "order", w["cartId"])) is not None:
            w["state"], w["reasonCodes"] = "COMPLETED", ["ORDER_OBSERVED"]
        elif w["state"] not in TERMINAL:
            w["state"], w["reasonCodes"] = "AWAITING_OUTCOME", ["MOCK_JOURNEY_ACCEPTED"]
        self.put(
            session,
            tenant,
            "exposure",
            action["actionId"],
            {
                "actionId": action["actionId"],
                "customerRef": w["customerRef"],
                "workflowId": w["workflowId"],
                "externalRef": external,
                "exposedAt": action["attemptedAt"],
                "experimentId": self.policy.experiment,
                "evidence": "mock_delivery_confirmed",
            },
        )
        # Mock acceptance confirms delivery. Real connectors require delivery callbacks.
        event = Event(
            eventId=uuid4(),
            eventType="growth.action_executed.v1",
            tenantId=tenant,
            aggregateId=w["workflowId"],
            occurredAt=now(),
            correlationId=w["correlationId"],
            source="policy-gateway",
            data={
                "actionId": action["actionId"],
                "workflowId": w["workflowId"],
                "customerRef": w["customerRef"],
                "externalRef": external,
            },
        )
        if session.get(Row, (tenant, "outbox", f"action-{action['actionId']}")) is None:
            self.put(
                session,
                tenant,
                "outbox",
                f"action-{action['actionId']}",
                {
                    "event": event.model_dump(mode="json"),
                    "kind": "outcome",
                    "published": False,
                },
            )
        return self._save_action(session, tenant, row, w, action)

    def approve(self, tenant: str, workflow_id: str, decision: str, actor: str) -> dict[str, Any]:
        with transaction(self.db, tenant) as session:
            approval = session.get(Row, (tenant, "approval", workflow_id))
            row = session.get(Row, (tenant, "workflow", workflow_id))
            if approval is None or row is None:
                raise DomainError("NOT_FOUND", 404)
            if approval.data["requestedBy"] == actor:
                raise DomainError("SEPARATION_OF_DUTIES", 403)
            if approval.data["state"] != "pending":
                raise DomainError("APPROVAL_ALREADY_DECIDED")
            if now() >= datetime.fromisoformat(approval.data["expiresAt"]):
                raise DomainError("APPROVAL_EXPIRED")
            approval.data = {**approval.data, "state": decision, "approver": actor}
            w = dict(row.data)
            w["state"] = "POLICY_CHECKED" if decision == "approved" else "CANCELLED"
            w["reasonCodes"] = ["HUMAN_APPROVED" if decision == "approved" else "HUMAN_REJECTED"]
            row.data = w
            self.audit(session, tenant, w, "approval.decision", decision, actor)
            return dict(approval.data)

    def replay(self, tenant: str, workflow_id: str, actor: str) -> dict[str, Any]:
        with transaction(self.db, tenant) as session:
            row = session.get(Row, (tenant, "workflow", workflow_id))
            if row is None:
                raise DomainError("NOT_FOUND", 404)
            w = dict(row.data)
            if w["state"] != "FAILED_REVIEW":
                raise DomainError("NOT_REPLAYABLE")
            action = session.get(Row, (tenant, "action", workflow_id))
            if action and action.data["state"] == "REJECTED":
                raise DomainError("PERMANENT_FAILURE")
            w["state"] = "POLICY_CHECKED"
            row.data = w
            if action:
                action.data = {**action.data, "attempts": 0}
            self.audit(session, tenant, w, "workflow.replay", "REQUESTED", actor)
            dlq = session.get(Row, (tenant, "dlq", workflow_id))
            if dlq:
                dlq.data = {**dlq.data, "resolved": True}
        return self.execute(tenant, ActionIntent(workflowId=workflow_id))

    def cancel(self, tenant: str, workflow_id: str, actor: str) -> dict[str, Any]:
        with transaction(self.db, tenant) as session:
            row = session.get(Row, (tenant, "workflow", workflow_id))
            if row is None:
                raise DomainError("NOT_FOUND", 404)
            w = dict(row.data)
            if w["state"] not in TERMINAL:
                w["state"], w["reasonCodes"] = "CANCELLED", ["OPERATOR_CANCELLED"]
                row.data = w
                self.audit(session, tenant, w, "workflow.cancel", "CANCELLED", actor)
            return w

    def expire(self, tenant: str, workflow_id: str) -> str:
        with transaction(self.db, tenant) as session:
            row = session.get(Row, (tenant, "workflow", workflow_id))
            if row is None:
                raise DomainError("NOT_FOUND", 404)
            w = dict(row.data)
            if w["state"] == "APPROVAL_PENDING":
                approval = session.get(Row, (tenant, "approval", workflow_id))
                if approval and now() >= datetime.fromisoformat(approval.data["expiresAt"]):
                    w["state"], w["reasonCodes"] = "EXPIRED", ["APPROVAL_EXPIRED"]
                    row.data = w
                    self.audit(session, tenant, w, "approval.expire", "EXPIRED")
            if w["state"] in {"AWAITING_OUTCOME", "APPROVAL_PENDING"} and now() >= (
                datetime.fromisoformat(w["startedAt"])
                + timedelta(hours=self.policy.observationHours)
            ):
                w["state"], w["reasonCodes"] = "EXPIRED", ["OBSERVATION_WINDOW_ENDED"]
                row.data = w
                self.audit(session, tenant, w, "workflow.expire", "EXPIRED")
            return str(w["state"])

    def report(self, tenant: str) -> dict[str, Any]:
        assignments = self.rows(tenant, "assignment")
        outcomes = self.rows(tenant, "outcome")
        cohorts: dict[str, Any] = {}
        for arm in ("control", "treatment"):
            people = [a for a in assignments if a["arm"] == arm]
            converted: set[str] = set()
            revenue: dict[str, float] = {}
            for person in people:
                start = datetime.fromisoformat(person["assignedAt"])
                end = start + timedelta(hours=self.policy.observationHours)
                for outcome in outcomes:
                    if (
                        outcome["customerRef"] == person["customerRef"]
                        and start <= (datetime.fromisoformat(outcome["occurredAt"])) <= end
                    ):
                        converted.add(person["customerRef"])
                        currency = outcome["currency"]
                        revenue[currency] = revenue.get(currency, 0) + float(outcome["amount"])
            n = len(people)
            cohorts[arm] = {
                "n": n,
                "conversions": len(converted),
                "conversionRate": len(converted) / n if n else None,
                "attributedRevenueByCurrency": revenue,
            }
        t, c = cohorts["treatment"], cohorts["control"]
        difference, interval = None, None
        if t["n"] and c["n"]:
            difference = t["conversionRate"] - c["conversionRate"]

            # Wilson/Newcombe interval remains informative for tiny samples and zero conversions.
            def wilson(k: int, n: int) -> tuple[float, float]:
                p, z = k / n, 1.96
                center = (p + z * z / (2 * n)) / (1 + z * z / n)
                half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
                return center - half, center + half

            tl, tu = wilson(t["conversions"], t["n"])
            cl, cu = wilson(c["conversions"], c["n"])
            interval = [tl - cu, tu - cl]
        return {
            "experimentId": self.policy.experiment,
            "cohorts": cohorts,
            "absoluteLift": difference,
            "conservative95Interval": interval,
            "exposures": len(self.rows(tenant, "exposure")),
            "interpretation": "Synthetic descriptive estimate; small samples and immature windows. "
            "Attributed revenue is not incremental revenue.",
        }
