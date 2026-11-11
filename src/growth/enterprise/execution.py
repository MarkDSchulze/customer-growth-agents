import re
from typing import Protocol

import httpx
from pydantic import SecretStr
from sqlalchemy.orm import Session

from growth.adapters import AmbiguousVendorError, PermanentVendorError, RetryableVendorError
from growth.db import VendorFault
from growth.enterprise.contracts import Scope, Tool
from growth.enterprise.model_gateway import approved_url, bounded_json
from growth.enterprise.models import VendorRecord
from growth.enterprise.storage import digest


def external_reference(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}", value):
        raise AmbiguousVendorError("PROVIDER_REFERENCE_INVALID")
    return value


class Executor(Protocol):
    def status(self, scope: Scope, key: str, tool: Tool, payload: dict[str, str]) -> str | None: ...
    def execute(self, scope: Scope, key: str, tool: Tool, payload: dict[str, str]) -> str: ...


def validate_parameters(tool: str, payload: dict[str, str]) -> None:
    valid = {
        "trigger_approved_journey": set(payload) == {"journeyId"}
        and payload.get("journeyId")
        in {"cart-recovery-v1", "lead-nurture-v1", "service-retention-v1"},
        "create_seller_task": payload == {"taskType": "qualified-follow-up"},
        "activate_approved_audience": payload == {"audienceRef": "approved-growth-audience-v1"},
        "publish_product_recommendation": set(payload) == {"productRef"},
        "create_service_recovery_task": payload == {"taskType": "service-recovery"},
    }
    if not valid.get(tool, False):
        raise PermanentVendorError("TOOL_PARAMETERS_DENIED")


class SyntheticExecutor:
    def __init__(self, db: object):
        from sqlalchemy.engine import Engine

        if not isinstance(db, Engine):
            raise TypeError("ENGINE_REQUIRED")
        self.db = db

    def status(self, scope: Scope, key: str, tool: Tool, payload: dict[str, str]) -> str | None:
        with Session(self.db) as session:
            fault = session.get(VendorFault, scope.tenantId)
            if fault and fault.mode == "unknown_status":
                raise AmbiguousVendorError("STATUS_UNAVAILABLE")
            row = session.get(VendorRecord, (scope.tenantId, key))
            if row and (
                row.region != scope.region
                or row.tool != tool
                or row.payload_hash != digest(payload)
            ):
                raise PermanentVendorError("IDEMPOTENCY_CONFLICT")
            return row.external_ref if row else None

    def execute(self, scope: Scope, key: str, tool: Tool, payload: dict[str, str]) -> str:
        validate_parameters(tool, payload)
        with Session(self.db) as session, session.begin():
            fault = session.get(VendorFault, scope.tenantId)
            mode = fault.mode if fault else "healthy"
            if mode == "unavailable":
                raise RetryableVendorError("VENDOR_UNAVAILABLE")
            if mode == "permanent":
                raise PermanentVendorError("VENDOR_REJECTED")
            row = session.get(VendorRecord, (scope.tenantId, key))
            if row and (
                row.region != scope.region
                or row.tool != tool
                or row.payload_hash != digest(payload)
            ):
                raise PermanentVendorError("IDEMPOTENCY_CONFLICT")
            if not row:
                row = VendorRecord(
                    tenant=scope.tenantId,
                    key=key,
                    region=scope.region,
                    tool=tool,
                    payload_hash=digest(payload),
                    external_ref=f"synthetic-{key}",
                )
                session.add(row)
            external = row.external_ref
        if mode == "timeout_after_accept":
            raise AmbiguousVendorError("ACK_TIMEOUT")
        return external


class HttpSandboxExecutor:
    """Fixed-origin, tenant-bound HTTP contract; ambiguous writes always reconcile first."""

    def __init__(
        self,
        tenant: str,
        region: str,
        url: str,
        token: SecretStr,
        hosts: list[str],
        allow_internal: bool = False,
        client: httpx.Client | None = None,
    ):
        self.tenant, self.region, self.token = tenant, region, token
        self.url = approved_url(url, hosts, allow_internal)
        from growth.observability import instrument_client

        self.client = client or instrument_client(
            httpx.Client(timeout=httpx.Timeout(5), follow_redirects=False)
        )

    def _call(
        self, scope: Scope, key: str, tool: Tool, payload: dict[str, str], operation: str
    ) -> object:
        if scope.tenantId != self.tenant or scope.region != self.region:
            raise PermanentVendorError("CONNECTOR_SCOPE_MISMATCH")
        validate_parameters(tool, payload)
        try:
            return bounded_json(
                self.client,
                "POST",
                f"{self.url}/v1/{operation}",
                headers={
                    "Authorization": f"Bearer {self.token.get_secret_value()}",
                    "Idempotency-Key": key,
                    "X-Correlation-ID": scope.correlationId,
                },
                json={"scope": scope.model_dump(), "key": key, "tool": tool, "parameters": payload},
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code >= 500 or exc.response.status_code == 429:
                if operation == "status":
                    raise AmbiguousVendorError("STATUS_UNAVAILABLE") from None
                raise RetryableVendorError("VENDOR_UNAVAILABLE") from None
            raise PermanentVendorError("VENDOR_REJECTED") from None
        except (httpx.TransportError, ValueError):
            raise AmbiguousVendorError(
                "STATUS_UNAVAILABLE" if operation == "status" else "ACK_TIMEOUT"
            ) from None

    def status(self, scope: Scope, key: str, tool: Tool, payload: dict[str, str]) -> str | None:
        value = self._call(scope, key, tool, payload, "status")
        if isinstance(value, dict) and value.get("state") == "not_found":
            return None
        if (
            isinstance(value, dict)
            and value.get("state") == "accepted"
            and isinstance(value.get("externalRef"), str)
        ):
            return external_reference(str(value["externalRef"]))
        raise AmbiguousVendorError("STATUS_UNCONFIRMED")

    def execute(self, scope: Scope, key: str, tool: Tool, payload: dict[str, str]) -> str:
        value = self._call(scope, key, tool, payload, "execute")
        if (
            isinstance(value, dict)
            and value.get("state") == "accepted"
            and isinstance(value.get("externalRef"), str)
        ):
            return external_reference(str(value["externalRef"]))
        raise AmbiguousVendorError("ACK_UNCONFIRMED")


class SandboxRouter:
    def __init__(
        self,
        bindings: dict[str, dict[str, str]],
        url: str,
        hosts: list[str],
        allow_internal: bool = False,
    ):
        self.adapters = {
            tenant: HttpSandboxExecutor(
                tenant, binding["region"], url, SecretStr(binding["token"]), hosts, allow_internal
            )
            for tenant, binding in bindings.items()
        }

    def _adapter(self, scope: Scope) -> HttpSandboxExecutor:
        adapter = self.adapters.get(scope.tenantId)
        if not adapter:
            raise PermanentVendorError("SANDBOX_TENANT_NOT_BOUND")
        return adapter

    def status(self, scope: Scope, key: str, tool: Tool, payload: dict[str, str]) -> str | None:
        return self._adapter(scope).status(scope, key, tool, payload)

    def execute(self, scope: Scope, key: str, tool: Tool, payload: dict[str, str]) -> str:
        return self._adapter(scope).execute(scope, key, tool, payload)
