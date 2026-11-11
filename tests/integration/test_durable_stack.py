import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from temporalio.client import Client
from temporalio.worker import Worker

from growth.config import Settings
from growth.contracts import Snapshot
from growth.db import Row, engine, transaction
from growth.engine import GrowthEngine
from growth.policy import Policy, assignment
from growth.temporal_worker import TASK_QUEUE, Activities, CartRecoveryWorkflow
from tests.conftest import event

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("GROWTH_INTEGRATION") != "1",
        reason="Run make test-integration with infrastructure",
    ),
]


@pytest.fixture
def stack_core():
    config = Settings()
    return GrowthEngine(
        engine(config.database_url),
        engine(config.vendor_database_url),
        Policy.load(config.policy_path),
    )


def test_postgres_role_rls_and_immutable_audit(stack_core):
    tenant = "tenant-isolation-" + uuid4().hex[:8]
    with transaction(stack_core.db, tenant) as session:
        stack_core.put(session, tenant, "test", "isolation-probe", {"safe": True})
        stack_core.audit(session, tenant, {"correlationId": str(uuid4())}, "test.probe", "OK")
    with Session(stack_core.db) as session:
        role = session.execute(
            text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user")
        ).one()
        assert role == (False, False)
        assert session.scalars(select(Row)).all() == []
    with transaction(stack_core.db, "another-tenant") as session:
        assert session.scalars(select(Row).where(Row.id == "isolation-probe")).all() == []
    with pytest.raises(DBAPIError):
        with transaction(stack_core.db, tenant) as session:
            session.execute(
                text("UPDATE audit_record SET outcome='ALTERED' WHERE tenant=:tenant"),
                {"tenant": tenant},
            )


def test_kafka_temporal_restart_outcome(stack_core):
    async def exercise():
        config = Settings()
        client = await Client.connect(config.temporal_address)
        customer = "cust-integration-" + uuid4().hex[:12]
        while assignment("tenant-demo", customer, stack_core.policy) != "treatment":
            customer = "cust-integration-" + uuid4().hex[:12]
        cart = "cart-integration-" + uuid4().hex[:12]
        stack_core.enable_simulation("tenant-demo")
        stack_core.source("tenant-demo", Snapshot(customerRef=customer, cartId=cart))
        source = event(customer, cart)
        wid = stack_core.ingest("tenant-demo", source)["workflowId"]
        activities = Activities(stack_core)
        with ThreadPoolExecutor(max_workers=8) as pool:

            def make_worker():
                return Worker(
                    client,
                    task_queue=TASK_QUEUE,
                    workflows=[CartRecoveryWorkflow],
                    activities=[activities.plan, activities.execute, activities.observe],
                    activity_executor=pool,
                )

            async with make_worker():
                for _ in range(200):
                    if (
                        stack_core.get("tenant-demo", "workflow", wid)["state"]
                        == "AWAITING_OUTCOME"
                    ):
                        break
                    await asyncio.sleep(0.2)
                else:
                    raise AssertionError(
                        "Broker-to-Temporal execution failed; inspect work/event-worker.log"
                    )
            with transaction(stack_core.db, "tenant-demo") as session:
                outbox = session.get(Row, ("tenant-demo", "outbox", "start-" + wid))
                assert outbox.data["published"]
            stack_core.ingest(
                "tenant-demo",
                event(
                    customer,
                    cart,
                    kind="commerce.order_placed.v1",
                    orderId="order-" + uuid4().hex[:12],
                ),
            )
            async with make_worker():
                result = await asyncio.wait_for(
                    client.get_workflow_handle("growth-" + wid).result(), 45
                )
            assert result == "COMPLETED"
            assert (
                len(
                    [
                        e
                        for e in stack_core.rows("tenant-demo", "exposure")
                        if e["workflowId"] == wid
                    ]
                )
                == 1
            )
            assert stack_core.ingest("tenant-demo", source)["duplicate"]

    asyncio.run(exercise())
