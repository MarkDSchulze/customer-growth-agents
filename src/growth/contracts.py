from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Ref = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")]
Currency = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]


class DTO(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, hide_input_in_errors=True)


class CartAbandoned(DTO):
    cartId: Ref
    customerRef: Ref
    currency: Currency
    cartValue: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    itemIds: list[Ref] = Field(min_length=1, max_length=100)


class OrderPlaced(DTO):
    cartId: Ref
    customerRef: Ref
    orderId: Ref
    currency: Currency
    amount: Decimal = Field(ge=0, max_digits=12, decimal_places=2)


class CaseEscalated(DTO):
    customerRef: Ref
    caseId: Ref
    severity: Literal["high", "critical"]


class ActionExecuted(DTO):
    actionId: Ref
    workflowId: Ref
    customerRef: Ref
    externalRef: Ref


class Event(DTO):
    eventId: UUID
    eventType: Literal[
        "commerce.cart_abandoned.v1",
        "commerce.order_placed.v1",
        "service.case_escalated.v1",
        "growth.action_executed.v1",
    ]
    schemaVersion: Literal["1.0.0"] = "1.0.0"
    tenantId: Ref
    aggregateId: Ref
    occurredAt: datetime
    correlationId: UUID
    source: Ref
    region: Literal["us-east-1"] = "us-east-1"
    data: dict[str, Any]

    @model_validator(mode="after")
    def validate_payload(self) -> "Event":
        if self.occurredAt.tzinfo is None:
            raise ValueError("occurredAt requires timezone")
        models: dict[str, type[DTO]] = {
            "commerce.cart_abandoned.v1": CartAbandoned,
            "commerce.order_placed.v1": OrderPlaced,
            "service.case_escalated.v1": CaseEscalated,
            "growth.action_executed.v1": ActionExecuted,
        }
        payload = models[self.eventType].model_validate(self.data)
        self.data = payload.model_dump(mode="json")
        if isinstance(payload, (CartAbandoned, OrderPlaced)) and self.aggregateId != payload.cartId:
            raise ValueError("aggregateId must match cartId")
        return self


class Snapshot(DTO):
    customerRef: Ref
    cartId: Ref
    identityKnown: bool = True
    consent: bool = True
    purposeAllowed: bool = True
    severeCase: bool = False
    ordered: bool = False
    inStock: bool = True
    priceCurrent: bool = True
    sourceAvailable: bool = True
    channel: Literal["email"] = "email"


class Proposal(DTO):
    domain: Literal["Marketing", "Advertising", "Sales", "Commerce", "Service"]
    taskId: Ref
    tool: Literal["trigger_approved_journey", "recommend_only"]
    journeyId: Ref | None = None
    channel: Literal["email"] = "email"
    policyVersion: Ref
    rationale: list[Ref]


class ActionIntent(DTO):
    workflowId: Ref
    tool: Literal["trigger_approved_journey"] = "trigger_approved_journey"
    journeyId: Ref = "cart-recovery-v1"
    purpose: Literal["cart_recovery"] = "cart_recovery"


class KillCommand(DTO):
    enabled: bool


class Principal(DTO):
    subject: Ref
    identityType: Literal["human", "workload"] = "workload"
    tenant: Ref
    region: Literal["us-east-1", "eu-west-1", "ap-southeast-2"]
    role: Literal["viewer", "operator", "admin", "producer", "platform_admin"]
    purposes: list[
        Literal[
            "cart_recovery",
            "lead_qualification",
            "audience_activation",
            "commerce_personalization",
            "service_recovery",
        ]
    ]


class DecisionRequest(DTO):
    workflowId: Ref
    purpose: Literal["cart_recovery"] = "cart_recovery"


class FaultCommand(DTO):
    mode: Literal["healthy", "timeout_after_accept", "unavailable", "permanent", "unknown_status"]


class ApprovalCommand(DTO):
    decision: Literal["approved", "rejected"]
