from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient

from growth.api import create_app
from growth.config import Settings
from growth.contracts import Event, Snapshot
from growth.db import Base, VendorBase, engine
from growth.engine import GrowthEngine
from growth.policy import Policy, assignment


@pytest.fixture
def core(tmp_path):
    db = engine(f"sqlite:///{tmp_path}/growth.db")
    vendor = engine(f"sqlite:///{tmp_path}/vendor.db")
    Base.metadata.create_all(db)
    VendorBase.metadata.create_all(vendor)
    return GrowthEngine(db, vendor, Policy.load("workflows/agent-policies.yaml"))


@pytest.fixture
def customer(core):
    for index in range(100):
        ref = f"cust-test-{index}"
        if assignment("tenant-demo", ref, core.policy) == "treatment":
            return ref
    raise AssertionError("No treatment fixture")


def event(
    customer="cust-test",
    cart="cart-test",
    tenant="tenant-demo",
    kind="commerce.cart_abandoned.v1",
    **data,
):
    payload = {
        "cartId": cart,
        "customerRef": customer,
        "currency": "USD",
        "cartValue": "120.00",
        "itemIds": ["sku-test"],
    }
    if kind == "commerce.order_placed.v1":
        payload = {
            "cartId": cart,
            "customerRef": customer,
            "orderId": "order-test",
            "currency": "USD",
            "amount": "120.00",
        }
    elif kind == "service.case_escalated.v1":
        payload = {"customerRef": customer, "caseId": "case-test", "severity": "critical"}
    payload.update(data)
    return Event(
        eventId=uuid4(),
        eventType=kind,
        tenantId=tenant,
        aggregateId=cart,
        occurredAt=datetime.now(UTC),
        correlationId=uuid4(),
        source="synthetic-test",
        data=payload,
    )


def prepare(core, customer, cart="cart-test", **context):
    core.enable_simulation("tenant-demo")
    core.source("tenant-demo", Snapshot(customerRef=customer, cartId=cart, **context))
    result = core.ingest("tenant-demo", event(customer, cart))
    core.plan("tenant-demo", result["workflowId"])
    return result["workflowId"]


def token(role="admin", tenant="tenant-demo", **extra):
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": "test-operator",
            "identityType": "human",
            "tenant": tenant,
            "region": "us-east-1",
            "role": role,
            "purposes": ["cart_recovery"],
            "iss": "growth-local",
            "aud": "growth-api",
            "iat": now,
            "exp": now + timedelta(hours=1),
            **extra,
        },
        "test-secret-with-at-least-32-characters",
        algorithm="HS256",
    )


@pytest.fixture
def client(core):
    app = create_app(Settings(auth_secret="test-secret-with-at-least-32-characters"), core)
    with TestClient(app, headers={"Authorization": f"Bearer {token()}"}) as client:
        yield client
