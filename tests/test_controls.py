from datetime import timedelta

import pytest

from growth.contracts import Snapshot
from growth.db import Row, now, transaction
from growth.engine import DomainError
from tests.conftest import event, prepare, token
from tests.test_workflow import execute, receipts


def test_global_switch_requires_platform_admin(client, core, customer):
    wid = prepare(core, customer)
    assert client.put("/v1/control/global-kill-switch", json={"enabled": True}).status_code == 403
    response = client.put(
        "/v1/control/global-kill-switch",
        json={"enabled": True},
        headers={"Authorization": f"Bearer {token(role='platform_admin')}"},
    )
    assert response.status_code == 200
    assert execute(core, wid)["state"] == "SUPPRESSED"
    assert receipts(core) == 0


def test_approval_wait_recheck_and_separation(core, customer):
    core.policy = core.policy.model_copy(update={"requireApproval": True})
    wid = prepare(core, customer)
    assert execute(core, wid)["state"] == "APPROVAL_PENDING"
    with pytest.raises(DomainError, match="SEPARATION_OF_DUTIES"):
        core.approve("tenant-demo", wid, "approved", "workflow-worker")
    core.approve("tenant-demo", wid, "approved", "human-reviewer")
    core.source("tenant-demo", Snapshot(customerRef=customer, cartId="cart-test", consent=False))
    assert execute(core, wid)["state"] == "SUPPRESSED"
    assert receipts(core) == 0


def test_approval_expiry(core, customer):
    core.policy = core.policy.model_copy(update={"requireApproval": True})
    wid = prepare(core, customer)
    core.approve("tenant-demo", wid, "approved", "human-reviewer")
    with transaction(core.db, "tenant-demo") as session:
        row = session.get(Row, ("tenant-demo", "approval", wid))
        row.data = {**row.data, "expiresAt": (now() - timedelta(minutes=1)).isoformat()}
    assert execute(core, wid)["state"] == "EXPIRED"
    assert receipts(core) == 0


def test_stale_event_never_sends(core, customer):
    core.enable_simulation("tenant-demo")
    core.source("tenant-demo", Snapshot(customerRef=customer, cartId="cart-test"))
    source = event(customer).model_copy(update={"occurredAt": now() - timedelta(days=4)})
    wid = core.ingest("tenant-demo", source)["workflowId"]
    assert "WINDOW_EXPIRED" in core.plan("tenant-demo", wid)["reasonCodes"]
    assert execute(core, wid)["state"] == "SUPPRESSED"
    assert receipts(core) == 0


def test_future_event_rejected(core, customer):
    source = event(customer).model_copy(update={"occurredAt": now() + timedelta(days=1)})
    with pytest.raises(DomainError, match="EVENT_TIME_IN_FUTURE"):
        core.ingest("tenant-demo", source)


def test_approval_requires_verified_human(client, core, customer):
    core.policy = core.policy.model_copy(update={"requireApproval": True})
    wid = prepare(core, customer)
    machine = {"Authorization": f"Bearer {token(identityType='workload')}"}
    response = client.post(
        f"/v1/approvals/{wid}/decisions", json={"decision": "approved"}, headers=machine
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "HUMAN_IDENTITY_REQUIRED"
    assert (
        client.post(f"/v1/approvals/{wid}/decisions", json={"decision": "approved"}).status_code
        == 200
    )
    assert execute(core, wid)["state"] == "ACCEPTED"
