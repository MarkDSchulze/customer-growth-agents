import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from growth.contracts import Event
from tests.conftest import event, token


def test_auth_and_role_enforcement(client):
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 200
    assert client.get("/v1/workflows", headers={"Authorization": ""}).status_code == 401
    assert (
        client.get("/v1/workflows", headers={"Authorization": "Bearer forged"}).status_code == 401
    )
    viewer = {"Authorization": f"Bearer {token(role='viewer')}"}
    assert client.get("/v1/workflows", headers=viewer).status_code == 200
    assert (
        client.put("/v1/control/kill-switch", json={"enabled": True}, headers=viewer).status_code
        == 403
    )
    assert (
        client.post("/v1/events", json=event().model_dump(mode="json"), headers=viewer).status_code
        == 403
    )
    expired = token(exp=datetime.now(UTC) - timedelta(hours=1))
    assert (
        client.get("/v1/status", headers={"Authorization": f"Bearer {expired}"}).status_code == 401
    )


def test_api_journey(client, customer):
    client.post("/v1/simulation/enable").raise_for_status()
    client.put(
        "/v1/simulation/context", json={"customerRef": customer, "cartId": "cart-test"}
    ).raise_for_status()
    source = event(customer).model_dump(mode="json")
    response = client.post("/v1/events", json=source)
    assert response.status_code == 202
    wid = response.json()["workflowId"]
    assert client.get(f"/v1/workflows/{wid}").json()["state"] == "AWAITING_OUTCOME"
    assert client.post("/v1/events", json=source).json()["duplicate"]
    assert client.post("/v1/actions", json={"workflowId": wid}).status_code == 400
    assert (
        client.post(
            "/v1/actions", json={"workflowId": wid}, headers={"Idempotency-Key": wid}
        ).json()["state"]
        == "ACCEPTED"
    )
    audit = client.get("/v1/audit").json()
    assert any(a["operation"] == "action.state" for a in audit)
    other = {"Authorization": f"Bearer {token(tenant='tenant-other')}"}
    assert client.get(f"/v1/workflows/{wid}", headers=other).status_code == 404
    assert client.get("/v1/audit", headers=other).json() == []


def test_contract_rejection_does_not_echo_secrets(client):
    source = event().model_dump(mode="json")
    source["data"]["email"] = "do-not-return@example.invalid"
    response = client.post("/v1/events", json=source)
    assert response.status_code == 422
    assert "do-not-return" not in response.text
    assert "email" not in response.text
    assert (
        client.post("/v1/actions", json={"workflowId": "task", "tool": "change_price"}).status_code
        == 422
    )
    assert (
        client.post("/v1/actions", json={"workflowId": "task", "tenantId": "other"}).status_code
        == 422
    )


def test_event_schema_matches_runtime():
    schema = json.loads(Path("contracts/event.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    for kind in [
        "commerce.cart_abandoned.v1",
        "commerce.order_placed.v1",
        "service.case_escalated.v1",
    ]:
        validator.validate(event(kind=kind).model_dump(mode="json"))
    invalid = event().model_dump(mode="json")
    invalid["data"]["currency"] = "usd"
    assert list(validator.iter_errors(invalid))
    with pytest.raises(ValidationError):
        Event.model_validate(invalid)


def test_contracts_and_asyncapi_topics(client):
    expected = json.loads(Path("contracts/openapi.json").read_text())
    assert client.app.openapi() == expected
    asyncapi = yaml.safe_load(Path("contracts/asyncapi.yaml").read_text())
    assert asyncapi["asyncapi"] == "3.0.0"
    assert {c["address"] for c in asyncapi["channels"].values()} == set(
        Event.model_fields["eventType"].annotation.__args__
    )


def test_scope_region_and_purpose_rejected(client):
    for payload in [{"region": "eu-west-1"}, {"purposes": []}, {"tenant": "x@example.invalid"}]:
        response = client.get("/v1/status", headers={"Authorization": f"Bearer {token(**payload)}"})
        assert response.status_code in {401, 403}
    assert (
        client.get("/v1/status", headers={"X-Correlation-ID": "raw-untrusted"}).status_code == 400
    )


def test_openapi_schema_is_valid(client):
    from openapi_spec_validator import validate

    validate(client.app.openapi())
