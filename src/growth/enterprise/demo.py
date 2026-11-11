from typing import Any
from uuid import uuid4

from growth.contracts import Principal
from growth.db import now
from growth.enterprise.contracts import CustomerContext, Product, SignalEvent, TenantConfig
from growth.enterprise.models import Organization
from growth.enterprise.service import EnterpriseService
from growth.enterprise.storage import unit


def seed(core: EnterpriseService, identity: Principal, execution: str) -> list[dict[str, Any]]:
    with unit(core.db, identity.tenant) as session:
        record = session.get(Organization, identity.tenant)
        config = (
            TenantConfig.model_validate(record.config)
            if record
            else TenantConfig(tenantId=identity.tenant, region=identity.region, holdoutFraction=0)
        )
    core.provision(config.model_copy(update={"simulationEnabled": True}), identity.subject)
    results = []
    for index, signal in enumerate(
        [
            "cart_abandoned",
            "lead_submitted",
            "audience_requested",
            "product_interest",
            "service_risk",
            "case_resolved",
            "cart_abandoned",
        ]
    ):
        customer = f"cust-enterprise-{index:03}"
        core.fixture(
            identity,
            CustomerContext(
                customerRef=customer,
                region=identity.region,
                observedAt=now(),
                emailConsent=index != 6,
                advertisingConsent=True,
                severeCase=index == 4,
                serviceRecovered=index == 5,
                leadFit=90,
                engagement=85,
                products=[Product(productRef="sku-enterprise-001", inStock=True)],
            ),
        )
        event = SignalEvent.model_validate(
            {
                "eventId": str(uuid4()),
                "tenantId": identity.tenant,
                "region": identity.region,
                "aggregateId": f"enterprise-demo-{index:03}",
                "customerRef": customer,
                "signal": signal,
                "occurredAt": now(),
                "correlationId": str(uuid4()),
                "source": "console-enterprise-demo",
            }
        )
        result = core.ingest(identity, event)
        if execution == "inline":
            core.plan(identity.tenant, result["workflowId"])
            core.execute(identity.tenant, result["workflowId"])
        results.append(result)
    return results
