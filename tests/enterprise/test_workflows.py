from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from growth.db import VendorFault, now
from growth.engine import DomainError
from growth.enterprise.contracts import TenantConfig
from growth.enterprise.models import VendorRecord
from growth.enterprise.storage import digest, unit
from tests.enterprise.conftest import context, identity, signal


def run(core, kind="lead_submitted"):
    wid = core.ingest(identity(), signal(kind))["workflowId"]
    core.plan("tenant-demo", wid)
    return wid, core.execute("tenant-demo", wid)


@pytest.mark.e2e
@pytest.mark.parametrize(
    ("kind", "domains"),
    [
        ("cart_abandoned", {"Marketing", "Commerce"}),
        ("lead_submitted", {"Marketing", "Sales"}),
        ("audience_requested", {"Advertising"}),
        ("product_interest", {"Commerce", "Sales"}),
        ("service_risk", {"Service"}),
        ("case_resolved", {"Marketing", "Service"}),
    ],
)
def test_every_domain_executes_governed_workflow(enterprise, kind, domains):
    wid, workflow = run(enterprise, kind)
    if kind == "audience_requested":
        assert workflow["state"] == "APPROVAL_PENDING"
        enterprise.approve(identity(), wid, "approved", workflow["planHash"])
        workflow = enterprise.execute("tenant-demo", wid)
    assert {a["domain"] for a in workflow["actions"]} == domains
    assert all(a["state"] == "ACCEPTED" for a in workflow["actions"])
    assert len(workflow["decision"]["agents"]) == 5
    assert workflow["state"] == "COMPLETED"


@pytest.mark.e2e
@pytest.mark.parametrize(
    ("values", "reason"),
    [
        ({"identityKnown": False}, "IDENTITY_UNKNOWN"),
        ({"purposeAllowed": []}, "PURPOSE_DENIED"),
        ({"sourceAvailable": False}, "SOURCE_UNAVAILABLE"),
        ({"observedAt": now() - timedelta(minutes=10)}, "CONTEXT_STALE"),
    ],
)
def test_source_suppression(enterprise, values, reason):
    enterprise.fixture(identity(), context(**values))
    _, w = run(enterprise)
    assert w["state"] == "SUPPRESSED"
    assert all(a["reasonCode"] == reason for a in w["actions"])


@pytest.mark.e2e
@pytest.mark.parametrize("change", ["consent", "service", "order", "inventory", "policy", "kill"])
def test_revalidation_before_actions(enterprise, change):
    event = signal("cart_abandoned")
    wid = enterprise.ingest(identity(), event)["workflowId"]
    enterprise.plan("tenant-demo", wid)
    values = (
        {"emailConsent": False}
        if change == "consent"
        else {"severeCase": True}
        if change == "service"
        else (
            {"ordered": True}
            if change == "order"
            else {"products": []}
            if change == "inventory"
            else {}
        )
    )
    if change == "policy":
        enterprise.provision(
            TenantConfig(
                tenantId="tenant-demo",
                region="us-east-1",
                policyVersion="enterprise-policy-v2",
                holdoutFraction=0,
                simulationEnabled=True,
            )
        )
    elif change == "kill":
        from growth.enterprise.models import Organization

        with unit(enterprise.db, "tenant-demo", exclusive=True) as session:
            session.get(Organization, "tenant-demo").killed = True
    else:
        enterprise.fixture(identity(), context(**values))
    w = enterprise.execute("tenant-demo", wid)
    if change == "consent":
        assert next(a for a in w["actions"] if a["domain"] == "Marketing")["state"] == "SUPPRESSED"
    elif change == "inventory":
        assert next(a for a in w["actions"] if a["domain"] == "Commerce")["state"] == "SUPPRESSED"
    else:
        assert all(a["state"] == "SUPPRESSED" for a in w["actions"])


def test_severe_case_routes_service_task_without_promotional_contact(enterprise):
    enterprise.fixture(identity(), context(severeCase=True, emailConsent=False))
    _, w = run(enterprise, "service_risk")
    assert [a["domain"] for a in w["actions"]] == ["Service"]
    assert w["actions"][0]["state"] == "ACCEPTED"
    _, other = run(enterprise, "cart_abandoned")
    assert all(a["state"] == "SUPPRESSED" for a in other["actions"])


def test_holdout_and_dry_run(enterprise):
    enterprise.provision(
        TenantConfig(
            tenantId="tenant-demo",
            region="us-east-1",
            holdoutFraction=1,
            policyVersion="control-v1",
            simulationEnabled=True,
        )
    )
    _, w = run(enterprise)
    assert w["state"] == "HOLDOUT"
    enterprise.provision(
        TenantConfig(
            tenantId="tenant-demo",
            region="us-east-1",
            holdoutFraction=0,
            policyVersion="observe-v1",
            simulationEnabled=False,
        )
    )
    _, w = run(enterprise)
    assert w["state"] == "DRY_RUN"


def test_duplicate_and_concurrent_execution(enterprise):
    event = signal("product_interest")
    wid = enterprise.ingest(identity(), event)["workflowId"]
    assert enterprise.ingest(identity(), event)["duplicate"]
    enterprise.plan("tenant-demo", wid)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: enterprise.execute("tenant-demo", wid), range(6)))
    assert all(w["state"] == "COMPLETED" for w in results)
    with Session(enterprise.vendor_db) as session:
        assert session.scalar(select(func.count()).select_from(VendorRecord)) == 2


def test_approval_is_bound_to_plan_and_current_consent(enterprise):
    wid, w = run(enterprise, "audience_requested")
    with pytest.raises(DomainError, match="APPROVAL_PLAN_MISMATCH"):
        enterprise.approve(identity(), wid, "approved", "forged")
    enterprise.approve(identity(), wid, "approved", w["planHash"])
    enterprise.fixture(identity(), context(advertisingConsent=False))
    w = enterprise.execute("tenant-demo", wid)
    assert w["actions"][0]["reasonCode"] == "ADVERTISING_CONSENT_DENIED"


def test_backpressure_and_action_quota(enterprise):
    enterprise.provision(
        TenantConfig(
            tenantId="tenant-demo",
            region="us-east-1",
            policyVersion="quota-v1",
            holdoutFraction=0,
            maxPending=1,
            actionsPerHour=1,
            simulationEnabled=True,
        )
    )
    wid = enterprise.ingest(identity(), signal())["workflowId"]
    with pytest.raises(DomainError, match="TENANT_BACKPRESSURE"):
        enterprise.ingest(identity(), signal())
    enterprise.plan("tenant-demo", wid)
    w = enterprise.execute("tenant-demo", wid)
    assert sum(a["state"] == "ACCEPTED" for a in w["actions"]) == 1
    assert any(a["reasonCode"] == "ACTION_QUOTA" for a in w["actions"])


def test_lost_ack_reconciles_without_duplicate(enterprise):
    with Session(enterprise.vendor_db) as session, session.begin():
        session.add(VendorFault(tenant="tenant-demo", mode="timeout_after_accept"))
    wid, w = run(enterprise, "product_interest")
    assert w["state"] == "FAILED_REVIEW"
    enterprise.control(identity(), wid, "replay")
    w = enterprise.execute("tenant-demo", wid)
    assert w["state"] == "COMPLETED"
    with Session(enterprise.vendor_db) as session:
        assert session.scalar(select(func.count()).select_from(VendorRecord)) == 2


def test_audit_chain_detects_tamper(enterprise):
    run(enterprise)
    records = enterprise.audit_export(identity())
    previous = "0" * 64
    for r in records:
        assert r["previous_hash"] == previous
        assert digest({k: v for k, v in r.items() if k != "record_hash"}) == r["record_hash"]
        previous = r["record_hash"]
    records[0]["outcome"] = "FORGED"
    assert (
        digest({k: v for k, v in records[0].items() if k != "record_hash"})
        != records[0]["record_hash"]
    )


def test_tenant_region_and_purpose_isolation(enterprise):
    wid, _ = run(enterprise)
    with pytest.raises(DomainError, match="TENANT_NOT_PROVISIONED"):
        enterprise.get(identity(tenant="tenant-other"), wid)
    with pytest.raises(DomainError, match="REGION_DENIED"):
        enterprise.get(identity(region="eu-west-1"), wid)
    with pytest.raises(DomainError, match="PURPOSE_DENIED"):
        enterprise.get(identity(purposes=["service_recovery"]), wid)


def test_independent_customer_regions_and_colliding_ids(enterprise):
    from growth.enterprise.service import EnterpriseService

    eu = EnterpriseService(enterprise.db, enterprise.vendor_db, region="eu-west-1")
    eu.provision(
        TenantConfig(
            tenantId="tenant-eu", region="eu-west-1", holdoutFraction=0, simulationEnabled=True
        )
    )
    european = identity(tenant="tenant-eu", region="eu-west-1")
    eu.fixture(european, context(region="eu-west-1"))
    source = signal("product_interest").model_copy(
        update={"tenantId": "tenant-eu", "region": "eu-west-1"}
    )
    wid = eu.ingest(european, source)["workflowId"]
    eu.plan("tenant-eu", wid)
    assert eu.execute("tenant-eu", wid)["state"] == "COMPLETED"
    with pytest.raises(DomainError, match="NOT_FOUND"):
        enterprise.get(identity(), wid)


def test_pre_effect_crash_recovery_and_cancellation(enterprise, monkeypatch):
    event = signal("product_interest")
    wid = enterprise.ingest(identity(), event)["workflowId"]
    enterprise.plan("tenant-demo", wid)
    executor = enterprise.executor.execute

    def crash(*args):
        executor(*args)
        raise RuntimeError("synthetic crash after acceptance")

    with monkeypatch.context() as patch:
        patch.setattr(enterprise.executor, "execute", crash)
        with pytest.raises(RuntimeError):
            enterprise.execute("tenant-demo", wid)
    enterprise.control(identity(), wid, "cancel")
    w = enterprise.execute("tenant-demo", wid)
    assert w["state"] == "CANCELLED"
    with Session(enterprise.vendor_db) as session:
        assert session.scalar(select(func.count()).select_from(VendorRecord)) == 1
    assert any(a["state"] == "ACCEPTED" for a in w["actions"])


def test_order_evidence_before_signal_suppresses_recovery(enterprise):
    assert enterprise.record_order(
        "tenant-demo", "us-east-1", "cust-enterprise", "order-first", now()
    )
    assert not enterprise.record_order(
        "tenant-demo", "us-east-1", "cust-enterprise", "order-first", now()
    )
    _, workflow = run(enterprise, "cart_abandoned")
    assert all(a["state"] == "SUPPRESSED" for a in workflow["actions"])
    assert all(a["reasonCode"] == "ORDER_COMPLETED" for a in workflow["actions"])


def test_identity_change_invalidates_existing_plan(enterprise):
    wid = enterprise.ingest(identity(), signal("product_interest"))["workflowId"]
    enterprise.plan("tenant-demo", wid)
    enterprise.fixture(identity(), context(identityVersion="changed-binding"))
    workflow = enterprise.execute("tenant-demo", wid)
    assert all(
        a["state"] == "SUPPRESSED" and a["reasonCode"] == "IDENTITY_CHANGED"
        for a in workflow["actions"]
    )


def test_human_requestor_cannot_approve_own_plan(enterprise):
    event = signal("audience_requested")
    wid = enterprise.ingest(identity(), event)["workflowId"]
    decision = enterprise.plan("tenant-demo", wid, identity().subject)
    workflow = enterprise.get(identity(), wid)
    assert decision["requestedBy"] == identity().subject
    with pytest.raises(DomainError, match="SEPARATION_OF_DUTIES"):
        enterprise.approve(identity(), wid, "approved", workflow["planHash"])


def test_rate_limit_is_tenant_scoped_and_duplicates_are_free(enterprise):
    enterprise.provision(
        TenantConfig(
            tenantId="tenant-demo",
            region="us-east-1",
            policyVersion="rate-limit-v1",
            signalsPerMinute=1,
            holdoutFraction=0,
            simulationEnabled=True,
        )
    )
    event = signal()
    enterprise.ingest(identity(), event)
    assert enterprise.ingest(identity(), event)["duplicate"]
    with pytest.raises(DomainError, match="TENANT_INGEST_RATE_LIMIT"):
        enterprise.ingest(identity(), signal())


def test_model_is_not_called_without_identity_and_purpose(enterprise):
    class ForbiddenGateway:
        def advise(self, *args):
            raise AssertionError("Unauthorized context must never leave the deterministic boundary")

    enterprise.gateway = ForbiddenGateway()
    enterprise.fixture(identity(), context(purposeAllowed=[]))
    _, workflow = run(enterprise)
    assert workflow["state"] == "SUPPRESSED"
