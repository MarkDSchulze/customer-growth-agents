"""Reproducible synthetic load evidence; measured workload limits are explicit."""

import argparse
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import jwt

from growth.config import settings

parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://localhost:8000")
parser.add_argument("--requests", type=int, default=100)
parser.add_argument("--concurrency", type=int, default=8)
parser.add_argument("--token-file", type=Path)
parser.add_argument("--output", type=Path, default=Path("work/load-result.json"))
parser.add_argument("--max-p95-seconds", type=float, default=60)
args = parser.parse_args()
if not 1 <= args.requests <= 5000 or not 1 <= args.concurrency <= 128:
    raise SystemExit("Choose 1-5000 requests and 1-128 clients")
if args.token_file:
    token = args.token_file.read_text().strip()
else:
    config = settings()
    if len(config.auth_secret) < 32 or config.oidc_issuer:
        raise SystemExit("Provide an operator token file for an OIDC deployment")
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": "synthetic-load-operator",
            "identityType": "human",
            "tenant": "tenant-demo",
            "region": "us-east-1",
            "role": "admin",
            "purposes": [
                "cart_recovery",
                "lead_qualification",
                "audience_activation",
                "commerce_personalization",
                "service_recovery",
            ],
            "iss": "growth-local",
            "aud": "growth-api",
            "iat": now,
            "exp": now + timedelta(hours=1),
        },
        config.auth_secret,
        algorithm="HS256",
    )
headers = {"Authorization": "Bearer " + token}
run = uuid4().hex[:10]


def exercise(index: int) -> tuple[float, float, str]:
    customer = f"cust-load-{run}-{index}"
    with httpx.Client(base_url=args.url, headers=headers, timeout=90) as client:
        client.put(
            "/v2/simulation/context",
            json={
                "customerRef": customer,
                "region": "us-east-1",
                "observedAt": datetime.now(UTC).isoformat(),
                "leadFit": 90,
                "engagement": 80,
                "products": [{"productRef": "sku-load", "inStock": True}],
            },
        ).raise_for_status()
        event = {
            "eventId": str(uuid4()),
            "tenantId": "tenant-demo",
            "region": "us-east-1",
            "aggregateId": f"load-{run}-{index}",
            "customerRef": customer,
            "signal": "product_interest",
            "occurredAt": datetime.now(UTC).isoformat(),
            "correlationId": str(uuid4()),
            "source": "console-enterprise-demo",
        }
        start = time.perf_counter()
        result = client.post("/v2/events", json=event)
        result.raise_for_status()
        ingest = time.perf_counter() - start
        wid = result.json()["workflowId"]
        while time.perf_counter() - start < 90:
            response = client.get(f"/v2/workflows/{wid}")
            response.raise_for_status()
            state = response.json()["state"]
            if state in {
                "COMPLETED",
                "SUPPRESSED",
                "HOLDOUT",
                "FAILED_REVIEW",
                "EXPIRED",
                "DRY_RUN",
            }:
                return ingest, time.perf_counter() - start, state
            time.sleep(0.2)
        return ingest, 90, "TIMEOUT"


start = time.perf_counter()
with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
    results = list(pool.map(exercise, range(args.requests)))
seconds = time.perf_counter() - start


def percentile(values: list[float], fraction: float) -> float:
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]


report = {
    "requests": args.requests,
    "concurrency": args.concurrency,
    "durationSeconds": seconds,
    "completedPerSecond": args.requests / seconds,
    "ingestP95Seconds": percentile([r[0] for r in results], 0.95),
    "endToEndP50Seconds": percentile([r[1] for r in results], 0.5),
    "endToEndP95Seconds": percentile([r[1] for r in results], 0.95),
    "endToEndP99Seconds": percentile([r[1] for r in results], 0.99),
    "states": {
        state: sum(r[2] == state for r in results) for state in sorted({r[2] for r in results})
    },
    "scope": "Synthetic product-interest workflows with PostgreSQL/Kafka/Temporal/HTTP sandbox; "
    "not production capacity, availability or DR certification.",
}
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
if any(r[2] != "COMPLETED" for r in results) or report["endToEndP95Seconds"] > args.max_p95_seconds:
    raise SystemExit("Synthetic workload gate failed")
