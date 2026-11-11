from datetime import datetime
from typing import Any, Literal, cast
from uuid import UUID

from pydantic import Field, model_validator

from growth.contracts import DTO, Currency, Ref

Region = Literal["us-east-1", "eu-west-1", "ap-southeast-2"]
Purpose = Literal[
    "cart_recovery",
    "lead_qualification",
    "audience_activation",
    "commerce_personalization",
    "service_recovery",
]
Domain = Literal["Marketing", "Advertising", "Sales", "Commerce", "Service"]
Tool = Literal[
    "trigger_approved_journey",
    "create_seller_task",
    "activate_approved_audience",
    "publish_product_recommendation",
    "create_service_recovery_task",
]
Signal = Literal[
    "cart_abandoned",
    "lead_submitted",
    "audience_requested",
    "product_interest",
    "service_risk",
    "case_resolved",
]
SIGNAL_PURPOSE: dict[str, Purpose] = {
    "cart_abandoned": "cart_recovery",
    "lead_submitted": "lead_qualification",
    "audience_requested": "audience_activation",
    "product_interest": "commerce_personalization",
    "service_risk": "service_recovery",
    "case_resolved": "service_recovery",
}
TOOLS: dict[str, Tool] = {
    "Marketing": "trigger_approved_journey",
    "Sales": "create_seller_task",
    "Advertising": "activate_approved_audience",
    "Commerce": "publish_product_recommendation",
    "Service": "create_service_recovery_task",
}


def approval_defaults() -> list[Domain]:
    return ["Advertising"]


class TenantConfig(DTO):
    tenantId: Ref
    region: Region
    brand: Ref = "demo-brand"
    enabled: bool = True
    policyVersion: Ref = "enterprise-policy-v1"
    allowedPurposes: list[Purpose] = Field(default_factory=lambda: list(SIGNAL_PURPOSE.values()))
    allowedDomains: list[Domain] = Field(default_factory=lambda: [cast(Domain, d) for d in TOOLS])
    holdoutFraction: float = Field(default=0.2, ge=0, le=1)
    maxPending: int = Field(default=1000, ge=1, le=100000)
    signalsPerMinute: int = Field(default=1000, ge=1, le=100000)
    actionsPerHour: int = Field(default=1000, ge=1, le=1000000)
    contactHours: int = Field(default=24, ge=1, le=720)
    requireApproval: list[Domain] = Field(default_factory=approval_defaults)
    simulationEnabled: bool = False


class Product(DTO):
    productRef: Ref
    inStock: bool
    entitled: bool = True
    priceCurrent: bool = True
    currency: Currency = "USD"


class CustomerContext(DTO):
    customerRef: Ref
    region: Region
    observedAt: datetime
    identityKnown: bool = True
    identityVersion: Ref = "synthetic-v1"
    purposeAllowed: list[Purpose] = Field(
        default_factory=lambda: list(set(SIGNAL_PURPOSE.values()))
    )
    emailConsent: bool = False
    advertisingConsent: bool = False
    severeCase: bool = False
    ordered: bool = False
    accountTier: Literal["strategic", "self_service"] = "self_service"
    leadFit: int = Field(default=0, ge=0, le=100)
    engagement: int = Field(default=0, ge=0, le=100)
    sellerTaskExists: bool = False
    products: list[Product] = Field(default_factory=list, max_length=50)
    serviceRecovered: bool = False
    sourceAvailable: bool = True
    audienceRef: Literal["approved-growth-audience-v1"] = "approved-growth-audience-v1"

    @model_validator(mode="after")
    def timezone(self) -> "CustomerContext":
        if self.observedAt.tzinfo is None:
            raise ValueError("observedAt requires timezone")
        return self


class SignalEvent(DTO):
    eventId: UUID
    eventType: Literal["growth.signal.v2"] = "growth.signal.v2"
    schemaVersion: Literal["2.0.0"] = "2.0.0"
    tenantId: Ref
    region: Region
    aggregateId: Ref
    customerRef: Ref
    signal: Signal
    occurredAt: datetime
    correlationId: UUID
    source: Ref

    @model_validator(mode="after")
    def timezone(self) -> "SignalEvent":
        if self.occurredAt.tzinfo is None:
            raise ValueError("occurredAt requires timezone")
        return self


class Scope(DTO):
    model_config = {"extra": "forbid", "frozen": True}
    tenantId: Ref
    region: Region
    customerRef: Ref
    purpose: Purpose
    correlationId: str
    workflowId: str
    policyVersion: Ref
    actor: Ref


class Advice(DTO):
    domain: Domain
    priority: int = Field(ge=0, le=100)
    evidence: list[
        Literal["consent", "service", "order", "inventory", "lead_fit", "engagement", "recovery"]
    ]
    confidence: float = Field(ge=0, le=1)


class Candidate(DTO):
    domain: Domain
    tool: Tool
    score: int = Field(ge=0, le=100)
    parameters: dict[str, str]
    reasonCodes: list[Ref]
    disposition: Literal["eligible", "suppressed", "recommendation"]


class Decision(DTO):
    requestedBy: Ref = "enterprise-worker"
    workflowId: str
    policyVersion: Ref
    arm: Literal["treatment", "control"]
    contextHash: str
    identityVersion: Ref = "synthetic-v1"
    candidates: list[Candidate]
    agents: list[dict[str, Any]]


class ApprovalDecision(DTO):
    decision: Literal["approved", "rejected"]
    planHash: str


class CursorPage(DTO):
    items: list[dict[str, Any]]
    nextCursor: str | None


class ChannelEvidence(DTO):
    channel: Literal["paid_search", "paid_social", "display"]
    spend: float = Field(ge=0, le=100000000, allow_inf_nan=False)
    conversions: int = Field(ge=0, le=10000000)
    contribution: float = Field(ge=0, le=100000000, allow_inf_nan=False)


class BudgetDraft(DTO):
    currency: Currency
    totalBudget: float = Field(ge=0, le=1000000, allow_inf_nan=False)
    observations: int = Field(ge=0, le=100000000)
    channels: list[ChannelEvidence] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def unique(self) -> "BudgetDraft":
        if len({c.channel for c in self.channels}) != len(self.channels):
            raise ValueError("duplicate channel")
        return self


class IdentityBinding(DTO):
    customerRef: Ref
    region: Region
    salesforceContact: str = Field(pattern=r"^[A-Za-z0-9]{15}(?:[A-Za-z0-9]{3})?$")
    adobeProfile: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,96}$")
    shopifyCustomer: str = Field(pattern=r"^gid://shopify/Customer/[0-9]+$")
    shopifyVariants: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def variant_references(self) -> "IdentityBinding":
        import re

        if any(
            not re.fullmatch(r"gid://shopify/ProductVariant/[0-9]+", v)
            for v in self.shopifyVariants
        ):
            raise ValueError("invalid product variant reference")
        return self
