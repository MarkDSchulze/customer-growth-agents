"""Exercise every domain against the running complete Compose stack, including human review."""

import json
import time
from datetime import UTC, datetime, timedelta

import httpx
import jwt

from growth.config import settings
from growth.enterprise.archive import verify

config = settings()
now = datetime.now(UTC)
token = jwt.encode(
    {
        "sub": "synthetic-stack-operator",
        "identityType": "human",
        "tenant": "tenant-demo",
        "role": "admin",
        "region": "us-east-1",
        "purposes": [
            "cart_recovery",
            "lead_qualification",
            "audience_activation",
            "commerce_personalization",
            "service_recovery",
        ],
        "iat": now,
        "exp": now + timedelta(hours=1),
        "iss": "growth-local",
        "aud": "growth-api",
    },
    config.auth_secret,
    algorithm="HS256",
)
with httpx.Client(
    base_url="http://localhost:8000", headers={"Authorization": "Bearer " + token}, timeout=30
) as client:
    for _ in range(120):
        try:
            response = client.get("/readyz")
            if response.status_code == 200:
                break
        except httpx.HTTPError:
            pass
        time.sleep(1)
    else:
        raise SystemExit("Full stack API did not become ready")
    client.post("/v2/simulation/demo").raise_for_status()
    for _ in range(240):
        page = client.get("/v2/workflows?limit=200")
        page.raise_for_status()
        workflows = page.json()["items"]
        waiting = [w for w in workflows if w["state"] == "APPROVAL_PENDING"]
        for w in waiting:
            client.post(
                f"/v2/workflows/{w['workflowId']}/approval",
                json={"decision": "approved", "planHash": w["planHash"]},
            ).raise_for_status()
        if len(workflows) >= 7 and all(
            w["state"] in {"COMPLETED", "SUPPRESSED", "HOLDOUT"} for w in workflows
        ):
            break
        time.sleep(0.5)
    else:
        raise SystemExit("Domain workflows did not reach governed completion")
    accepted = [a for w in workflows for a in w["actions"] if a["state"] == "ACCEPTED"]
    if {a["domain"] for a in accepted} != {
        "Marketing",
        "Advertising",
        "Sales",
        "Commerce",
        "Service",
    }:
        raise SystemExit("Missing accepted domain actions")
    if len({a["externalRef"] for a in accepted}) != len(accepted):
        raise SystemExit("External receipt collision")
    if not any(a["reasonCode"] == "CONSENT_DENIED" for w in workflows for a in w["actions"]):
        raise SystemExit("Missing opt-out suppression")
    export = client.get("/v2/audit/export")
    export.raise_for_status()
    verify([json.loads(line) for line in export.text.splitlines()])
    print(
        f"Full stack passed: {len(workflows)} workflows across all five domains; "
        "approvals, consent and audit chain verified."
    )
