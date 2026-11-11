from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from growth.contracts import ActionIntent, Proposal, Snapshot
from growth.db import Receipt, Row, VendorFault, now, transaction
from growth.engine import DomainError
from growth.policy import assignment, authorize
from tests.conftest import event, prepare


def execute(core, workflow_id):
    return core.execute("tenant-demo", ActionIntent(workflowId=workflow_id))


def receipts(core, tenant="tenant-demo"):
    with Session(core.vendor_db) as session:
        return session.scalar(
            select(func.count()).select_from(Receipt).where(Receipt.tenant == tenant)
        )


@pytest.mark.e2e
def test_treatment_end_to_end_conversion(core, customer):
    wid = prepare(core, customer)
    action = execute(core, wid)
    assert action["state"] == "ACCEPTED"
    assert receipts(core) == 1
    core.ingest("tenant-demo", event(customer, kind="commerce.order_placed.v1"))
    assert core.get("tenant-demo", "workflow", wid)["state"] == "COMPLETED"
    report = core.report("tenant-demo")
    assert report["cohorts"]["treatment"]["conversions"] == 1
    assert report["exposures"] == 1
    assert "not incremental revenue" in report["interpretation"]


@pytest.mark.parametrize(
    ("context", "reason"),
    [
        ({"consent": False}, "CONSENT_DENIED"),
        ({"purposeAllowed": False}, "PURPOSE_DENIED"),
        ({"severeCase": True}, "OPEN_CRITICAL_CASE"),
        ({"ordered": True}, "ORDER_COMPLETED"),
        ({"inStock": False}, "OUT_OF_STOCK"),
        ({"priceCurrent": False}, "STALE_PRICE"),
        ({"identityKnown": False}, "IDENTITY_UNKNOWN"),
        ({"sourceAvailable": False}, "SOURCE_UNAVAILABLE"),
    ],
)
@pytest.mark.e2e
def test_suppression(core, customer, context, reason):
    wid = prepare(core, customer, **context)
    assert execute(core, wid)["state"] == "SUPPRESSED"
    assert reason in core.get("tenant-demo", "decision", wid)["reasonCodes"]
    assert receipts(core) == 0


@pytest.mark.parametrize("change", ["consent", "service", "order", "kill"])
@pytest.mark.e2e
def test_recheck_race(core, customer, change):
    wid = prepare(core, customer)
    if change == "consent":
        core.source(
            "tenant-demo", Snapshot(customerRef=customer, cartId="cart-test", consent=False)
        )
    elif change == "service":
        core.ingest("tenant-demo", event(customer, kind="service.case_escalated.v1"))
    elif change == "order":
        core.ingest("tenant-demo", event(customer, kind="commerce.order_placed.v1"))
    else:
        core.kill("tenant-demo", True, "test-admin", "test-correlation")
    assert execute(core, wid)["state"] == "SUPPRESSED"
    assert receipts(core) == 0


@pytest.mark.e2e
def test_order_before_abandonment(core, customer):
    core.ingest("tenant-demo", event(customer, kind="commerce.order_placed.v1"))
    wid = prepare(core, customer)
    assert execute(core, wid)["state"] == "SUPPRESSED"
    assert receipts(core) == 0


def test_holdout_is_stable_and_never_activated(core):
    customer = next(
        f"cust-{i}"
        for i in range(100)
        if assignment("tenant-demo", f"cust-{i}", core.policy) == "control"
    )
    wid = prepare(core, customer)
    assert core.plan("tenant-demo", wid)["arm"] == "control"
    assert execute(core, wid)["state"] == "HOLDOUT"
    assert receipts(core) == 0


def test_duplicate_and_cart_level_dedupe(core, customer):
    core.enable_simulation("tenant-demo")
    core.source("tenant-demo", Snapshot(customerRef=customer, cartId="cart-test"))
    source = event(customer)
    first = core.ingest("tenant-demo", source)
    assert core.ingest("tenant-demo", source)["duplicate"]
    second = core.ingest("tenant-demo", event(customer))
    assert first["workflowId"] == second["workflowId"]
    assert len(core.rows("tenant-demo", "workflow")) == 1
    core.plan("tenant-demo", first["workflowId"])
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: execute(core, first["workflowId"]), range(8)))
    assert all(r["state"] == "ACCEPTED" for r in results)
    assert receipts(core) == 1
    assert len(core.rows("tenant-demo", "exposure")) == 1


def test_event_id_conflict(core, customer):
    source = event(customer)
    core.ingest("tenant-demo", source)
    modified = source.model_copy(update={"data": {**source.data, "cartValue": "99.00"}})
    with pytest.raises(DomainError, match="EVENT_ID_CONFLICT"):
        core.ingest("tenant-demo", modified)


@pytest.mark.e2e
def test_ambiguous_timeout_reconciles(core, customer):
    wid = prepare(core, customer)
    with Session(core.vendor_db) as session, session.begin():
        session.add(VendorFault(tenant="tenant-demo", mode="timeout_after_accept"))
    result = execute(core, wid)
    assert result["state"] == "ACCEPTED"
    assert result["attempts"] == 1
    assert execute(core, wid)["externalRef"] == result["externalRef"]
    assert receipts(core) == 1


@pytest.mark.e2e
def test_crash_after_external_acceptance(core, customer, monkeypatch):
    wid = prepare(core, customer)
    accepted = core._accepted
    with monkeypatch.context() as patch:
        patch.setattr(core, "_accepted", lambda *args: (_ for _ in ()).throw(RuntimeError("crash")))
        with pytest.raises(RuntimeError, match="crash"):
            execute(core, wid)
    assert receipts(core) == 1
    core._accepted = accepted
    assert execute(core, wid)["state"] == "ACCEPTED"
    assert receipts(core) == 1


@pytest.mark.e2e
def test_bounded_retry_dlq_and_replay(core, customer):
    wid = prepare(core, customer)
    with Session(core.vendor_db) as session, session.begin():
        session.add(VendorFault(tenant="tenant-demo", mode="unavailable"))
    for _ in range(3):
        execute(core, wid)
    assert core.get("tenant-demo", "workflow", wid)["state"] == "FAILED_REVIEW"
    assert not core.get("tenant-demo", "dlq", wid)["resolved"]
    with Session(core.vendor_db) as session, session.begin():
        session.get(VendorFault, "tenant-demo").mode = "healthy"
    arm = core.get("tenant-demo", "decision", wid)["arm"]
    assert core.replay("tenant-demo", wid, "operator")["state"] == "ACCEPTED"
    assert core.get("tenant-demo", "decision", wid)["arm"] == arm
    assert receipts(core) == 1


def test_unknown_status_requires_review_and_no_send(core, customer):
    wid = prepare(core, customer)
    with Session(core.vendor_db) as session, session.begin():
        session.add(VendorFault(tenant="tenant-demo", mode="unknown_status"))
    assert execute(core, wid)["state"] == "RECONCILING"
    assert core.get("tenant-demo", "workflow", wid)["state"] == "FAILED_REVIEW"
    assert receipts(core) == 0


def test_permanent_failure_not_replayed(core, customer):
    wid = prepare(core, customer)
    with Session(core.vendor_db) as session, session.begin():
        session.add(VendorFault(tenant="tenant-demo", mode="permanent"))
    assert execute(core, wid)["state"] == "REJECTED"
    with pytest.raises(DomainError, match="PERMANENT_FAILURE"):
        core.replay("tenant-demo", wid, "operator")


def test_frequency_serialized_across_concurrent_carts(core, customer):
    ids = [prepare(core, customer, cart=f"cart-{i}") for i in range(5)]
    with ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(lambda wid: execute(core, wid), ids))
    assert receipts(core) == 1
    assert sum(w["state"] == "SUPPRESSED" for w in core.rows("tenant-demo", "workflow")) == 4


def test_cross_tenant_collision(core, customer):
    wid = prepare(core, customer)
    with pytest.raises(DomainError, match="NOT_FOUND"):
        core.get("tenant-other", "workflow", wid)
    assert core.rows("tenant-other", "workflow") == []
    with pytest.raises(DomainError, match="TENANT_MISMATCH"):
        core.ingest("tenant-other", event(customer))
    assert receipts(core, "tenant-other") == 0


def test_unsafe_proposal_cannot_grant_authority(core, customer):
    proposal = Proposal(
        domain="Sales",
        taskId="task-test",
        tool="trigger_approved_journey",
        journeyId=core.policy.approvedJourney,
        policyVersion=core.policy.version,
        rationale=["IGNORE_PREVIOUS_INSTRUCTIONS"],
    )
    assert not authorize(proposal, core.policy)
    wid = prepare(core, customer)
    with transaction(core.db, "tenant-demo") as session:
        row = session.get(Row, ("tenant-demo", "decision", wid))
        data = dict(row.data)
        data["proposals"] = [proposal.model_dump()]
        row.data = data
    assert execute(core, wid)["state"] == "REJECTED"
    assert receipts(core) == 0


def test_default_dry_run(core, customer):
    core.source("tenant-demo", Snapshot(customerRef=customer, cartId="cart-test"))
    wid = core.ingest("tenant-demo", event(customer))["workflowId"]
    core.plan("tenant-demo", wid)
    assert execute(core, wid)["state"] == "DRY_RUN"
    assert receipts(core) == 0


def test_cancel_and_expire(core, customer):
    wid = prepare(core, customer)
    core.cancel("tenant-demo", wid, "operator")
    assert execute(core, wid)["state"] == "CANCELLED"
    assert receipts(core) == 0
    other = prepare(core, customer, cart="cart-other")
    execute(core, other)
    with transaction(core.db, "tenant-demo") as session:
        row = session.get(Row, ("tenant-demo", "workflow", other))
        row.data = {**row.data, "startedAt": (now() - timedelta(hours=73)).isoformat()}
    assert core.expire("tenant-demo", other) == "EXPIRED"


@pytest.mark.e2e
def test_acceptance_reconciles_after_crash_and_later_order(core, customer, monkeypatch):
    wid = prepare(core, customer)
    accepted = core._accepted
    with monkeypatch.context() as patch:
        patch.setattr(core, "_accepted", lambda *args: (_ for _ in ()).throw(RuntimeError("crash")))
        with pytest.raises(RuntimeError, match="crash"):
            execute(core, wid)
    core._accepted = accepted
    core.ingest("tenant-demo", event(customer, kind="commerce.order_placed.v1"))
    assert execute(core, wid)["state"] == "ACCEPTED"
    assert core.get("tenant-demo", "workflow", wid)["state"] == "COMPLETED"
    assert receipts(core) == 1
