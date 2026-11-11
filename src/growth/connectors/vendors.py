import hashlib
import re
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import Field, SecretStr

from growth.adapters import AmbiguousVendorError, PermanentVendorError, RetryableVendorError
from growth.contracts import DTO
from growth.db import now
from growth.enterprise.contracts import CustomerContext, Product, Purpose, Scope, Tool
from growth.enterprise.model_gateway import bounded_json


class SalesforceConfig(DTO):
    baseUrl: str
    accessToken: SecretStr
    apiVersion: str = "v65.0"
    contactId: str = ""


class AdobeConfig(DTO):
    baseUrl: str = "https://platform.adobe.io"
    accessToken: SecretStr
    apiKey: SecretStr
    organizationId: str
    sandbox: str
    profileId: str = ""
    advertisingConsentPath: list[str] = Field(default_factory=list, max_length=8)
    purposeEligibilityPaths: dict[Purpose, list[str]] = Field(default_factory=dict)


class ShopifyConfig(DTO):
    shop: str
    accessToken: SecretStr
    customerId: str = ""
    variantIds: list[str] = Field(default_factory=list, max_length=50)
    apiVersion: str = "2026-10"
    webhookSecret: SecretStr = SecretStr("")


def object_result(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("PROVIDER_SCHEMA_INVALID")
    return value


def records(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError("PROVIDER_SCHEMA_INVALID")
    return value


def headers(token: SecretStr) -> dict[str, str]:
    return {"Authorization": f"Bearer {token.get_secret_value()}"}


class SalesforceConnector:
    def __init__(
        self, tenant: str, region: str, config: SalesforceConfig, client: httpx.Client | None = None
    ):
        parsed = urlparse(config.baseUrl)
        # Only Salesforce sandbox domains are accepted for task mutations in this release.
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or not parsed.hostname.endswith(".sandbox.my.salesforce.com")
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
        ):
            raise ValueError("SALESFORCE_SANDBOX_REQUIRED")
        if not re.fullmatch(r"[A-Za-z0-9]{15}(?:[A-Za-z0-9]{3})?", config.contactId):
            raise ValueError("SALESFORCE_CONTACT_ID_INVALID")
        if not re.fullmatch(r"v[0-9]{2,3}\.0", config.apiVersion):
            raise ValueError("SALESFORCE_API_VERSION_INVALID")
        self.tenant, self.region, self.config = tenant, region, config
        self.url = f"{config.baseUrl.rstrip('/')}/services/data/{config.apiVersion}"
        from growth.observability import instrument_client

        self.client = client or instrument_client(httpx.Client(timeout=5, follow_redirects=False))

    def _scope(self, scope: Scope) -> None:
        if scope.tenantId != self.tenant or scope.region != self.region:
            raise PermanentVendorError("CONNECTOR_SCOPE_MISMATCH")

    def read(self, scope: Scope) -> dict[str, Any]:
        self._scope(scope)
        auth = headers(self.config.accessToken)
        # SOQL has no REST bind variables. Contact IDs are restricted to 15/18 alphanumerics.
        contact = object_result(
            bounded_json(
                self.client,
                "GET",
                f"{self.url}/sobjects/Contact/{self.config.contactId}",
                headers=auth,
                params={"fields": "Id,Growth_Fit_Score__c,Growth_Engagement_Score__c"},
            )
        )
        cases = object_result(
            bounded_json(
                self.client,
                "GET",
                f"{self.url}/query",
                headers=auth,
                params={
                    "q": "SELECT Id,Priority FROM Case WHERE ContactId = '"  # nosec B608
                    + self.config.contactId
                    + "' AND IsClosed = false LIMIT 100"
                },
            )
        )
        tasks = object_result(
            bounded_json(
                self.client,
                "GET",
                f"{self.url}/query",
                headers=auth,
                params={
                    "q": "SELECT Id FROM Task WHERE WhoId = '"  # nosec B608
                    + self.config.contactId
                    + "' AND IsClosed = false AND Subject = 'Growth: qualified follow-up' LIMIT 1"
                },
            )
        )
        if contact.get("Id") != self.config.contactId:
            raise ValueError("PROVIDER_IDENTITY_MISMATCH")
        case_records = records(cases["records"])
        task_records = records(tasks["records"])
        return {
            "leadFit": int(contact.get("Growth_Fit_Score__c", 0)),
            "engagement": int(contact.get("Growth_Engagement_Score__c", 0)),
            "severeCase": any(c.get("Priority") in ("High", "Critical") for c in case_records),
            "sellerTaskExists": bool(task_records),
            "serviceRecovered": not case_records,
        }

    def status(self, scope: Scope, key: str, tool: Tool, payload: dict[str, str]) -> str | None:
        self._scope(scope)
        if not re.fullmatch(r"[a-f0-9]{64}", key):
            raise PermanentVendorError("IDEMPOTENCY_KEY_INVALID")
        if tool not in ("create_seller_task", "create_service_recovery_task"):
            raise PermanentVendorError("SALESFORCE_TOOL_DENIED")
        try:
            result = object_result(
                bounded_json(
                    self.client,
                    "GET",
                    f"{self.url}/sobjects/Task/Growth_Action_Key__c/{key}",
                    headers=headers(self.config.accessToken),
                )
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise AmbiguousVendorError("SALESFORCE_STATUS_UNCONFIRMED") from None
        except (httpx.HTTPError, ValueError):
            raise AmbiguousVendorError("SALESFORCE_STATUS_UNCONFIRMED") from None
        if not isinstance(result.get("Id"), str) or not re.fullmatch(
            r"00T[A-Za-z0-9]{12}(?:[A-Za-z0-9]{3})?", result["Id"]
        ):
            raise AmbiguousVendorError("SALESFORCE_STATUS_UNCONFIRMED")
        return "salesforce-" + str(result["Id"])

    def execute(self, scope: Scope, key: str, tool: Tool, payload: dict[str, str]) -> str:
        from growth.enterprise.execution import validate_parameters

        self._scope(scope)
        validate_parameters(tool, payload)
        if tool not in ("create_seller_task", "create_service_recovery_task") or not re.fullmatch(
            r"[a-f0-9]{64}", key
        ):
            raise PermanentVendorError("SALESFORCE_TOOL_DENIED")
        try:
            description = object_result(
                bounded_json(
                    self.client,
                    "GET",
                    f"{self.url}/sobjects/Task/describe",
                    headers=headers(self.config.accessToken),
                )
            )
            field: dict[str, Any] = next(
                (
                    f
                    for f in records(description.get("fields", []))
                    if f.get("name") == "Growth_Action_Key__c"
                ),
                {},
            )
            if field.get("externalId") is not True or field.get("unique") is not True:
                raise PermanentVendorError("SALESFORCE_IDEMPOTENCY_NOT_VERIFIED")
        except (httpx.HTTPError, ValueError):
            raise RetryableVendorError("SALESFORCE_METADATA_UNAVAILABLE") from None
        body = {
            "WhoId": self.config.contactId,
            "Status": "Not Started",
            "Priority": "Normal",
            "Subject": "Growth: qualified follow-up"
            if tool == "create_seller_task"
            else "Growth: service recovery",
        }
        try:
            result = self.client.patch(
                f"{self.url}/sobjects/Task/Growth_Action_Key__c/{key}",
                headers=headers(self.config.accessToken),
                json=body,
            )
            result.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                raise RetryableVendorError("SALESFORCE_RATE_LIMIT") from None
            if exc.response.status_code >= 500:
                raise AmbiguousVendorError("SALESFORCE_ACK_UNKNOWN") from None
            raise PermanentVendorError("SALESFORCE_REJECTED") from None
        except httpx.TransportError:
            raise AmbiguousVendorError("SALESFORCE_ACK_UNKNOWN") from None
        external = self.status(scope, key, tool, payload)
        if not external:
            raise AmbiguousVendorError("SALESFORCE_ACK_UNKNOWN")
        return external


class AdobeProfileConnector:
    def __init__(self, config: AdobeConfig, client: httpx.Client | None = None):
        if config.baseUrl != "https://platform.adobe.io" or config.sandbox in (
            "prod",
            "production",
            "",
        ):
            raise ValueError("ADOBE_NAMED_SANDBOX_REQUIRED")
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,96}", config.profileId):
            raise ValueError("ADOBE_PROFILE_REFERENCE_INVALID")
        paths = [config.advertisingConsentPath, *config.purposeEligibilityPaths.values()]
        if any(len(path) > 8 for path in paths) or any(
            not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]{0,95}", part)
            for path in paths
            for part in path
        ):
            raise ValueError("ADOBE_CONSENT_MAPPING_INVALID")
        self.config = config
        from growth.observability import instrument_client

        self.client = client or instrument_client(httpx.Client(timeout=5, follow_redirects=False))

    def read(self) -> dict[str, Any]:
        cfg = self.config
        auth = {
            **headers(cfg.accessToken),
            "x-api-key": cfg.apiKey.get_secret_value(),
            "x-gw-ims-org-id": cfg.organizationId,
            "x-sandbox-name": cfg.sandbox,
        }
        result = object_result(
            bounded_json(
                self.client,
                "GET",
                cfg.baseUrl + "/data/core/ups/access/entities",
                headers=auth,
                params={"schema.name": "_xdm.context.profile", "entityId": cfg.profileId},
            )
        )
        profile = object_result(result.get(cfg.profileId, {})).get("entity", {})
        profile = object_result(profile)
        consents = object_result(profile.get("consents", {}))
        marketing = object_result(consents.get("marketing", {}))
        email = object_result(marketing.get("email", {})).get("val") == "y"
        any_consent = object_result(marketing.get("any", {})).get("val") == "y"
        explicit: object = profile
        for part in cfg.advertisingConsentPath:
            explicit = explicit.get(part) if isinstance(explicit, dict) else None
        # Advertising is denied unless a client-approved dedicated CMP field is configured.
        advertising = bool(cfg.advertisingConsentPath) and explicit is True
        purposes = []
        for purpose, path in cfg.purposeEligibilityPaths.items():
            value: object = profile
            for part in path:
                value = value.get(part) if isinstance(value, dict) else None
            if path and value is True:
                purposes.append(purpose)
        return {
            "purposeAllowed": purposes,
            "emailConsent": email and any_consent,
            "advertisingConsent": advertising,
            "identityKnown": bool(profile),
        }


class ShopifyConnector:
    def __init__(self, config: ShopifyConfig, client: httpx.Client | None = None):
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", config.shop):
            raise ValueError("SHOPIFY_SHOP_INVALID")
        if not re.fullmatch(r"20[0-9]{2}-(01|04|07|10)", config.apiVersion):
            raise ValueError("SHOPIFY_API_VERSION_INVALID")
        if not re.fullmatch(r"gid://shopify/Customer/[0-9]+", config.customerId) or any(
            not re.fullmatch(r"gid://shopify/ProductVariant/[0-9]+", p) for p in config.variantIds
        ):
            raise ValueError("SHOPIFY_REFERENCE_INVALID")
        self.config = config
        self.url = f"https://{config.shop}.myshopify.com/admin/api/{config.apiVersion}/graphql.json"
        from growth.observability import instrument_client

        self.client = client or instrument_client(httpx.Client(timeout=5, follow_redirects=False))

    def read(self) -> dict[str, Any]:
        cfg = self.config
        query = """query GrowthContext($customerId:ID!,$variantIds:[ID!]!,$since:String!){
          shop{currencyCode} customer(id:$customerId){id orders(first:1,query:$since){nodes{id}}}
          nodes(ids:$variantIds){... on ProductVariant{id inventoryQuantity price product{status}}}}
        """
        result = object_result(
            bounded_json(
                self.client,
                "POST",
                self.url,
                headers={"X-Shopify-Access-Token": cfg.accessToken.get_secret_value()},
                json={
                    "query": query,
                    "variables": {
                        "customerId": cfg.customerId,
                        "variantIds": cfg.variantIds,
                        "since": "processed_at:>=" + (now() - timedelta(hours=72)).isoformat(),
                    },
                },
            )
        )
        if result.get("errors"):
            raise ValueError("SHOPIFY_GRAPHQL_REJECTED")
        data = object_result(result["data"])
        products = []
        for p in data["nodes"]:
            if p is None:
                continue
            if not isinstance(p, dict) or p.get("id") not in cfg.variantIds:
                raise ValueError("PROVIDER_PRODUCT_MISMATCH")
            try:
                price_ok = Decimal(str(p.get("price", "-1"))) >= 0
            except InvalidOperation:
                price_ok = False
            products.append(
                Product(
                    productRef="sku-" + hashlib.sha256(p["id"].encode()).hexdigest()[:20],
                    inStock=isinstance(p.get("inventoryQuantity"), int)
                    and p["inventoryQuantity"] > 0,
                    entitled=p.get("product", {}).get("status") == "ACTIVE",
                    priceCurrent=price_ok,
                    currency=data["shop"]["currencyCode"],
                )
            )
        customer = data.get("customer")
        return {
            "ordered": bool(customer and customer.get("orders", {}).get("nodes")),
            "products": [p.model_dump() for p in products],
            "identityKnown": bool(
                isinstance(customer, dict) and customer.get("id") == cfg.customerId
            ),
        }


def verify_shopify_webhook(body: bytes, signature: str, secret: SecretStr) -> bool:
    import base64
    import hmac

    expected = base64.b64encode(
        hmac.new(secret.get_secret_value().encode(), body, "sha256").digest()
    ).decode()
    return hmac.compare_digest(expected, signature)


class FederatedContext:
    def __init__(
        self,
        salesforce: SalesforceConnector,
        adobe: AdobeProfileConnector,
        shopify: ShopifyConnector,
    ):
        self.salesforce, self.adobe, self.shopify = salesforce, adobe, shopify

    def read(self, scope: Scope) -> CustomerContext:
        try:
            consent = self.adobe.read()
            if scope.purpose not in consent["purposeAllowed"]:
                return CustomerContext(
                    customerRef=scope.customerRef,
                    region=scope.region,
                    observedAt=now(),
                    purposeAllowed=[],
                    identityKnown=consent["identityKnown"],
                    emailConsent=consent["emailConsent"],
                    advertisingConsent=consent["advertisingConsent"],
                )
            sf = self.salesforce.read(scope)
            commerce = self.shopify.read()
            known = consent.pop("identityKnown") and commerce.pop("identityKnown")
            return CustomerContext.model_validate(
                {
                    "customerRef": scope.customerRef,
                    "region": scope.region,
                    "observedAt": now(),
                    "identityKnown": known,
                    **sf,
                    **consent,
                    **commerce,
                }
            )
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return CustomerContext(
                customerRef=scope.customerRef,
                region=scope.region,
                observedAt=now(),
                sourceAvailable=False,
                identityKnown=False,
            )
