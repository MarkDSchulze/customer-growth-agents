from datetime import UTC, datetime, timedelta

import jwt
from fastapi.testclient import TestClient

from growth.api import create_app
from growth.config import Settings
from growth.enterprise.archive import S3AuditArchive, verify
from tests.enterprise.conftest import identity

SECRET = "enterprise-test-secret-with-more-than-32-characters"


def token(role="admin", purposes=None, region="us-east-1"):
    principal = identity(role=role, purposes=purposes, region=region)
    return jwt.encode(
        {
            "sub": principal.subject,
            "tenant": principal.tenant,
            "role": role,
            "region": region,
            "purposes": principal.purposes,
            "identityType": "human",
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(hours=1),
            "iss": "growth-local",
            "aud": "growth-api",
        },
        SECRET,
        algorithm="HS256",
    )


def test_api_full_portfolio_approval_and_export(enterprise):
    from growth.engine import GrowthEngine
    from growth.policy import Policy

    legacy = GrowthEngine(
        enterprise.db, enterprise.vendor_db, Policy.load("workflows/agent-policies.yaml")
    )
    app = create_app(Settings(auth_secret=SECRET), legacy)
    with TestClient(app, headers={"Authorization": "Bearer " + token()}) as client:
        response = client.post("/v2/simulation/demo")
        assert response.status_code == 200, response.text
        page = client.get("/v2/workflows?limit=2").json()
        assert len(page["items"]) == 2 and page["nextCursor"]
        rest = client.get("/v2/workflows?limit=200&cursor=" + page["nextCursor"]).json()["items"]
        assert len(rest) == 5
        all_workflows = client.get("/v2/workflows").json()["items"]
        audience = next(w for w in all_workflows if w["signal"] == "audience_requested")
        wid = audience["workflowId"]
        assert client.post(f"/v2/workflows/{wid}/execute").status_code == 400
        assert (
            client.post(
                f"/v2/workflows/{wid}/approval",
                json={"decision": "approved", "planHash": audience["planHash"]},
            ).status_code
            == 200
        )
        assert (
            client.post(f"/v2/workflows/{wid}/execute", headers={"Idempotency-Key": wid}).json()[
                "state"
            ]
            == "COMPLETED"
        )
        denied = {"Authorization": "Bearer " + token(purposes=["service_recovery"])}
        assert client.get(f"/v2/workflows/{wid}", headers=denied).status_code == 403
        assert client.post(f"/v2/workflows/{wid}/cancel", headers=denied).status_code == 403
        export = client.get("/v2/audit/export")
        assert (
            export.status_code == 200 and "application/x-ndjson" in export.headers["content-type"]
        )
        import json

        verify([json.loads(line) for line in export.text.splitlines()])
        assert client.get("/v2/connectors").json()["liveActionsEnabled"] is False


def test_immutable_archive_scope_and_encryption(enterprise):
    from tests.enterprise.test_workflows import run

    run(enterprise)
    requests = []

    class Storage:
        def put_object(self, **kwargs):
            requests.append(kwargs)

    archive = S3AuditArchive(
        "growth-audit", "arn:aws:kms:us-east-1:123456789012:key/example", "123456789012", Storage()
    )
    records = enterprise.audit_export(identity())
    result = archive.write("tenant-demo", "us-east-1", records)
    assert result["uri"].startswith("s3://growth-audit/us-east-1/tenant-demo/")
    assert requests[0]["IfNoneMatch"] == "*"
    assert requests[0]["ObjectLockMode"] == "COMPLIANCE"
    assert requests[0]["ServerSideEncryption"] == "aws:kms"


def test_traces_redact_queries_and_authentication(enterprise):
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from growth.engine import GrowthEngine
    from growth.observability import instrument_app
    from growth.policy import Policy

    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    legacy = GrowthEngine(
        enterprise.db, enterprise.vendor_db, Policy.load("workflows/agent-policies.yaml")
    )
    app = create_app(Settings(auth_secret=SECRET), legacy)
    instrument_app(app, provider)
    bearer = token()
    with TestClient(app, headers={"Authorization": "Bearer " + bearer}) as client:
        assert client.get("/v2/tenant?email=do-not-retain@example.invalid").status_code == 200
    spans = exporter.get_finished_spans()
    rendered = str([dict(span.attributes) for span in spans])
    assert "do-not-retain" not in rendered
    assert bearer not in rendered
    assert any(span.attributes.get("growth.tenant_id") == "tenant-demo" for span in spans)


def test_budget_recommendations_cannot_authorize_spend():
    from decimal import Decimal

    from growth.enterprise.budgets import recommend
    from growth.enterprise.contracts import BudgetDraft

    draft = BudgetDraft(
        currency="USD",
        totalBudget=100.01,
        observations=200,
        channels=[
            {"channel": "paid_search", "spend": 10, "conversions": 30, "contribution": 30},
            {"channel": "paid_social", "spend": 10, "conversions": 20, "contribution": 20},
        ],
    )
    result = recommend(draft)
    assert sum(Decimal(a["proposedBudget"]) for a in result["allocations"]) == Decimal("100.01")
    assert result["executionSupported"] is False and result["humanApprovalRequired"] is True
