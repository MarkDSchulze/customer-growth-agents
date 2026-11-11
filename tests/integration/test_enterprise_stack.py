import os
import time
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from growth.config import Settings
from growth.enterprise.contracts import TenantConfig
from growth.enterprise.models import Action, Journal, VendorRecord, Workflow
from growth.enterprise.runtime import create_service
from growth.enterprise.storage import unit
from tests.enterprise.conftest import context, identity, signal

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("GROWTH_INTEGRATION") != "1", reason="Requires regional infrastructure"
    ),
]


def test_regional_normalized_rls_and_audit_immutability():
    core = create_service(Settings())
    core.provision(
        TenantConfig(
            tenantId="tenant-demo", region="us-east-1", holdoutFraction=0, simulationEnabled=True
        )
    )
    customer = "cust-http-" + uuid4().hex[:12]
    core.fixture(identity(), context(customer))
    wid = core.ingest(identity(), signal("product_interest", customer=customer))["workflowId"]
    for _ in range(180):
        result = core.get(identity(), wid)
        if result["state"] == "COMPLETED":
            break
        time.sleep(0.25)
    else:
        raise AssertionError("Regional Kafka/Temporal/HTTP execution did not complete")
    assert {a["domain"] for a in result["actions"]} == {"Commerce", "Sales"}
    assert all(a["state"] == "ACCEPTED" for a in result["actions"])
    with Session(core.vendor_db) as session:
        for action in result["actions"]:
            assert session.get(VendorRecord, ("tenant-demo", action["actionId"])) is not None
    with Session(core.db) as session:
        assert session.scalars(select(Workflow)).all() == []
        assert session.scalars(select(Action)).all() == []
        assert session.scalars(select(Journal)).all() == []
    with unit(core.db, "tenant-other") as session:
        assert session.get(Workflow, ("tenant-demo", wid)) is None
    with pytest.raises(DBAPIError):
        with unit(core.db, "tenant-demo") as session:
            session.execute(
                text("UPDATE enterprise_audit SET outcome='FORGED' WHERE tenant='tenant-demo'")
            )
