import json
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from growth.connectors.vendors import (
    AdobeConfig,
    AdobeProfileConnector,
    FederatedContext,
    SalesforceConfig,
    SalesforceConnector,
    ShopifyConfig,
    ShopifyConnector,
    verify_shopify_webhook,
)
from growth.contracts import DTO, Ref
from growth.db import now
from growth.enterprise.contracts import CustomerContext, IdentityBinding, Region, Scope, Tool
from growth.enterprise.execution import Executor, SyntheticExecutor
from growth.enterprise.models import IdentityRecord
from growth.enterprise.storage import digest


class ConnectorTemplate(DTO):
    tenantId: Ref
    region: Region
    salesforce: SalesforceConfig
    adobe: AdobeConfig
    shopify: ShopifyConfig
    allowSandboxTaskWrites: bool = False


class ConnectorProfile(ConnectorTemplate):
    customerRef: Ref


class ConnectorRegistry:
    """Tenant credentials and customer identity bindings have separate lifecycles and storage."""

    def __init__(
        self,
        profiles_json: str,
        vendor_db: Engine,
        fallback: Executor | None = None,
        operational_db: Engine | None = None,
        region: str = "us-east-1",
    ):
        entries = json.loads(profiles_json)
        if not isinstance(entries, dict):
            raise ValueError("CONNECTOR_PROFILES_INVALID")
        self.db = operational_db
        self.profiles: dict[tuple[str, str], ConnectorProfile] = {}
        self.templates: dict[str, ConnectorTemplate] = {}
        self.client = httpx.Client(timeout=5, follow_redirects=False)
        self.synthetic: Executor = fallback or SyntheticExecutor(vendor_db)
        for raw in entries.values():
            config = (
                ConnectorProfile.model_validate(raw)
                if "customerRef" in raw
                else ConnectorTemplate.model_validate(raw)
            )
            if config.region != region:
                raise ValueError("CONNECTOR_REGION_MISMATCH")
            sf_config = (
                config.salesforce
                if isinstance(config, ConnectorProfile)
                else config.salesforce.model_copy(update={"contactId": "003000000000001AAA"})
            )
            adobe_config = (
                config.adobe
                if isinstance(config, ConnectorProfile)
                else config.adobe.model_copy(update={"profileId": "configuration-validation"})
            )
            shopify_config = (
                config.shopify
                if isinstance(config, ConnectorProfile)
                else config.shopify.model_copy(update={"customerId": "gid://shopify/Customer/1"})
            )
            SalesforceConnector(config.tenantId, config.region, sf_config, self.client)
            AdobeProfileConnector(adobe_config, self.client)
            ShopifyConnector(shopify_config, self.client)

            if isinstance(config, ConnectorProfile):
                key = (config.tenantId, config.customerRef)
                if key in self.profiles:
                    raise ValueError("CONNECTOR_PROFILE_COLLISION")
                self.profiles[key] = config
            else:
                if config.tenantId in self.templates or self.db is None:
                    raise ValueError("CONNECTOR_TEMPLATE_COLLISION_OR_DATABASE_MISSING")
                self.templates[config.tenantId] = config

    def _binding(
        self, tenant: str, customer: str = "", shopify_customer: str = ""
    ) -> IdentityBinding | None:
        if self.db is None:
            return None
        # The outer customer guard serializes identity changes; avoid reacquiring that guard.
        with Session(self.db) as session, session.begin():
            if self.db.dialect.name == "postgresql":
                session.execute(
                    text("SELECT set_config('app.tenant_id',:tenant,true)"), {"tenant": tenant}
                )
            query = select(IdentityRecord).where(IdentityRecord.tenant == tenant)
            query = (
                query.where(IdentityRecord.customer == customer)
                if customer
                else query.where(IdentityRecord.shopify_customer == shopify_customer)
            )
            records = list(session.scalars(query.limit(2)))
            if len(records) != 1:
                return None
            return IdentityBinding.model_validate(records[0].binding)

    def _profile(self, scope: Scope) -> ConnectorProfile | None:
        static = self.profiles.get((scope.tenantId, scope.customerRef))
        if static:
            return static if static.region == scope.region else None
        template = self.templates.get(scope.tenantId)
        binding = self._binding(scope.tenantId, scope.customerRef) if template else None
        if (
            not template
            or not binding
            or binding.region != scope.region
            or template.region != scope.region
        ):
            return None
        return ConnectorProfile(
            tenantId=scope.tenantId,
            region=scope.region,
            customerRef=scope.customerRef,
            salesforce=template.salesforce.model_copy(
                update={"contactId": binding.salesforceContact}
            ),
            adobe=template.adobe.model_copy(update={"profileId": binding.adobeProfile}),
            shopify=template.shopify.model_copy(
                update={
                    "customerId": binding.shopifyCustomer,
                    "variantIds": binding.shopifyVariants,
                }
            ),
            allowSandboxTaskWrites=template.allowSandboxTaskWrites,
        )

    def read(self, scope: Scope) -> CustomerContext:
        profile = self._profile(scope)
        if not profile:
            return CustomerContext(
                customerRef=scope.customerRef,
                region=scope.region,
                observedAt=now(),
                identityKnown=False,
                sourceAvailable=False,
            )
        source = FederatedContext(
            SalesforceConnector(profile.tenantId, profile.region, profile.salesforce, self.client),
            AdobeProfileConnector(profile.adobe, self.client),
            ShopifyConnector(profile.shopify, self.client),
        )
        context = source.read(scope)
        context.identityVersion = digest(
            [
                profile.tenantId,
                profile.region,
                profile.salesforce.baseUrl,
                profile.salesforce.contactId,
                profile.adobe.sandbox,
                profile.adobe.profileId,
                profile.shopify.shop,
                profile.shopify.customerId,
                profile.shopify.variantIds,
            ]
        )
        return context

    def _executor(self, scope: Scope, tool: Tool) -> Executor:
        profile = self._profile(scope)
        if (
            profile
            and profile.allowSandboxTaskWrites
            and tool in ("create_seller_task", "create_service_recovery_task")
        ):
            return SalesforceConnector(
                profile.tenantId, profile.region, profile.salesforce, self.client
            )
        return self.synthetic

    def status(self, scope: Scope, key: str, tool: Tool, payload: dict[str, str]) -> str | None:
        return self._executor(scope, tool).status(scope, key, tool, payload)

    def execute(self, scope: Scope, key: str, tool: Tool, payload: dict[str, str]) -> str:
        return self._executor(scope, tool).execute(scope, key, tool, payload)

    def capabilities(self, tenant: str) -> list[dict[str, Any]]:
        configured = [p for p in self.profiles.values() if p.tenantId == tenant]
        template = self.templates.get(tenant)
        count = len(configured) + (1 if template else 0)
        writes = any(p.allowSandboxTaskWrites for p in configured) or bool(
            template and template.allowSandboxTaskWrites
        )
        return [
            {
                "provider": "Salesforce",
                "context": True,
                "sandboxTasks": writes,
                "productionWrites": False,
                "configuredProfiles": count,
            },
            {
                "provider": "Adobe Experience Platform",
                "context": True,
                "nativeActivation": False,
                "activationRequirement": "Approved idempotent bridge with delivery confirmation",
                "productionWrites": False,
                "configuredProfiles": count,
            },
            {
                "provider": "Shopify",
                "context": True,
                "priceMutation": False,
                "productionWrites": False,
                "configuredProfiles": count,
            },
        ]

    def authenticate_order(
        self, shop: str, signature: str, body: bytes
    ) -> tuple[ConnectorProfile, str, datetime]:
        from growth.adapters import PermanentVendorError

        configurations = list(self.profiles.values()) + list(self.templates.values())
        matches = [
            p
            for p in configurations
            if p.shopify.shop + ".myshopify.com" == shop
            and p.shopify.webhookSecret.get_secret_value()
            and verify_shopify_webhook(body, signature, p.shopify.webhookSecret)
        ]
        if not matches:
            raise PermanentVendorError("SOURCE_SIGNATURE_DENIED")
        value = json.loads(body)
        if type(value.get("id")) is not int or type(value.get("customer", {}).get("id")) is not int:
            raise ValueError("ORDER_REFERENCE_INVALID")
        native = "gid://shopify/Customer/" + str(value["customer"]["id"])
        profiles = []
        for config in matches:
            if isinstance(config, ConnectorProfile) and config.shopify.customerId == native:
                profiles.append(config)
            elif not isinstance(config, ConnectorProfile):
                binding = self._binding(config.tenantId, shopify_customer=native)
                if binding:
                    profile = self._profile(
                        Scope(
                            tenantId=config.tenantId,
                            region=config.region,
                            customerRef=binding.customerRef,
                            purpose="cart_recovery",
                            correlationId="source",
                            workflowId="source",
                            policyVersion="source",
                            actor="shopify-webhook",
                        )
                    )
                    if profile:
                        profiles.append(profile)
        if len(profiles) != 1:
            raise ValueError("SOURCE_IDENTITY_AMBIGUOUS")
        occurred = datetime.fromisoformat(value["created_at"])
        if occurred.tzinfo is None:
            raise ValueError("ORDER_TIME_REQUIRED")
        return profiles[0], "shopify-order-" + digest([shop, value["id"]])[:48], occurred
