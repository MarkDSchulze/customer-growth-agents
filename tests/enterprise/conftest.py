from datetime import UTC, datetime
from uuid import uuid4

import pytest

from growth.contracts import Principal
from growth.db import Base, VendorBase, engine
from growth.enterprise.contracts import CustomerContext, Product, SignalEvent, TenantConfig
from growth.enterprise.service import EnterpriseService


def identity(tenant="tenant-demo", region="us-east-1", purposes=None, role="admin"):
    return Principal(
        subject="human-operator",
        tenant=tenant,
        region=region,
        role=role,
        identityType="human",
        purposes=purposes
        or [
            "cart_recovery",
            "lead_qualification",
            "audience_activation",
            "commerce_personalization",
            "service_recovery",
        ],
    )


def context(customer="cust-enterprise", region="us-east-1", **values):
    return CustomerContext.model_validate(
        {
            "customerRef": customer,
            "region": region,
            "observedAt": datetime.now(UTC),
            "emailConsent": True,
            "advertisingConsent": True,
            "leadFit": 90,
            "engagement": 80,
            "severeCase": False,
            "serviceRecovered": True,
            "products": [Product(productRef="sku-001", inStock=True).model_dump()],
            **values,
        }
    )


def signal(kind="lead_submitted", customer="cust-enterprise", aggregate=None, **values):
    return SignalEvent(
        eventId=uuid4(),
        tenantId="tenant-demo",
        region="us-east-1",
        aggregateId=aggregate or f"aggregate-{uuid4().hex[:10]}",
        customerRef=customer,
        signal=kind,
        occurredAt=datetime.now(UTC),
        correlationId=uuid4(),
        source="console-enterprise-demo",
        **values,
    )


@pytest.fixture
def enterprise(tmp_path):
    db = engine(f"sqlite:///{tmp_path}/enterprise.db")
    vendor = engine(f"sqlite:///{tmp_path}/enterprise-vendor.db")
    Base.metadata.create_all(db)
    VendorBase.metadata.create_all(vendor)
    core = EnterpriseService(db, vendor)
    core.provision(
        TenantConfig(
            tenantId="tenant-demo", region="us-east-1", holdoutFraction=0, simulationEnabled=True
        )
    )
    core.fixture(identity(), context())
    return core
