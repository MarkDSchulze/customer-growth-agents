"""Load synthetic context and publish source events through the authenticated API."""

import argparse
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import jwt

from growth.config import settings

parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://localhost:8000")
args = parser.parse_args()
config = settings()
now = datetime.now(UTC)
token = jwt.encode(
    {
        "sub": "local-operator",
        "identityType": "human",
        "tenant": "tenant-demo",
        "region": "us-east-1",
        "role": "admin",
        "purposes": ["cart_recovery"],
        "iat": int(now.timestamp()),
        "exp": int(now.timestamp()) + 3600,
        "iss": "growth-local",
        "aud": "growth-api",
    },
    config.auth_secret,
    algorithm="HS256",
)
with httpx.Client(
    base_url=args.url, headers={"Authorization": f"Bearer {token}"}, timeout=30
) as client:
    client.post("/v1/simulation/enable").raise_for_status()
    for index, scenario in enumerate(
        [
            "eligible",
            "critical-case",
            "opted-out",
            "out-of-stock",
            "eligible",
            "eligible",
            "eligible",
            "eligible",
        ]
    ):
        # Fixed cart IDs make repeated demos idempotent at the workflow boundary.
        cart, customer = f"cart-demo-{index:03}", f"cust-demo-{index:03}"
        client.put(
            "/v1/simulation/context",
            json={
                "cartId": cart,
                "customerRef": customer,
                "consent": scenario != "opted-out",
                "severeCase": scenario == "critical-case",
                "inStock": scenario != "out-of-stock",
            },
        ).raise_for_status()
        event = {
            "eventId": str(uuid4()),
            "eventType": "commerce.cart_abandoned.v1",
            "tenantId": "tenant-demo",
            "aggregateId": cart,
            "occurredAt": now.isoformat(),
            "correlationId": str(uuid4()),
            "source": "commerce-adapter-mock",
            "data": {
                "cartId": cart,
                "customerRef": customer,
                "cartValue": "120.00",
                "currency": "USD",
                "itemIds": ["sku-demo-01"],
            },
        }
        client.post("/v1/events", json=event).raise_for_status()
        print(f"{cart}: {scenario}")
print("Synthetic events accepted. Open http://localhost:3000 and connect with make token.")
