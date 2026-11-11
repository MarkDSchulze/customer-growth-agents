from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

from growth.db import now
from growth.enterprise.contracts import (
    TOOLS,
    Advice,
    Candidate,
    CustomerContext,
    Domain,
    TenantConfig,
)
from growth.enterprise.storage import aware

DOMAINS: tuple[Domain, ...] = ("Service", "Commerce", "Sales", "Marketing", "Advertising")


ASSESSMENTS = ThreadPoolExecutor(max_workers=16, thread_name_prefix="growth-agent")


class ModelGateway(Protocol):
    def advise(self, domain: Domain, facts: dict[str, bool | int]) -> tuple[Advice, str]: ...


class DeterministicGateway:
    def advise(self, domain: Domain, facts: dict[str, bool | int]) -> tuple[Advice, str]:
        return Advice(
            domain=domain,
            priority=int(facts["leadFit"]),
            confidence=1,
            evidence=["consent", "service", "inventory", "lead_fit"],
        ), "deterministic-v2"


@dataclass(frozen=True)
class Plan:
    candidates: list[Candidate]
    agents: list[dict[str, object]]


def eligibility(context: CustomerContext, purpose: str) -> list[str]:
    denied = []
    if not context.sourceAvailable:
        denied.append("SOURCE_UNAVAILABLE")
    if not context.identityKnown:
        denied.append("IDENTITY_UNKNOWN")
    if purpose not in context.purposeAllowed:
        denied.append("PURPOSE_DENIED")
    stamp = aware(context.observedAt)
    if stamp < now() - timedelta(minutes=5) or stamp > now() + timedelta(minutes=1):
        denied.append("CONTEXT_STALE")
    return denied


def build(
    signal: str,
    purpose: str,
    context: CustomerContext,
    tenant: TenantConfig,
    gateway: ModelGateway,
    assess: bool = True,
) -> Plan:
    # Only minimized typed facts cross the model boundary. Models never supply tools or recipients.
    facts = {
        "emailConsent": context.emailConsent,
        "advertisingConsent": context.advertisingConsent,
        "severeCase": context.severeCase,
        "ordered": context.ordered,
        "availableProducts": sum(
            p.inStock and p.entitled and p.priceCurrent for p in context.products
        ),
        "leadFit": context.leadFit,
        "engagement": context.engagement,
        "serviceRecovered": context.serviceRecovered,
    }

    advisor = gateway if not eligibility(context, purpose) else DeterministicGateway()

    def reason(domain: Domain) -> dict[str, object]:
        advice, version = advisor.advise(domain, facts)
        return {
            "domain": domain,
            "advice": advice.model_dump(),
            "modelVersion": version,
            "state": "COMPLETED",
            "dependencies": [] if domain in ("Service", "Commerce") else ["Service", "Commerce"],
        }

    # Shared assessment stage precedes the three growth planners, with bounded parallelism.
    agents: list[dict[str, object]] = []
    if assess:
        assessments = list(ASSESSMENTS.map(reason, DOMAINS[:2]))
        proposals = list(ASSESSMENTS.map(reason, DOMAINS[2:]))
        agents = assessments + proposals
    candidates: list[Candidate] = []
    base_denials = eligibility(context, purpose)

    def add(domain: Domain, score: int, parameters: dict[str, str], extra: list[str]) -> None:
        denied = base_denials + extra
        if domain not in tenant.allowedDomains:
            denied.append("DOMAIN_DENIED")
        candidates.append(
            Candidate(
                domain=domain,
                tool=TOOLS[domain],
                score=score,
                parameters=parameters,
                reasonCodes=denied or ["ELIGIBLE"],
                disposition="suppressed" if denied else "eligible",
            )
        )

    promotional = ["OPEN_CRITICAL_CASE"] if context.severeCase else []
    email = [] if context.emailConsent else ["CONSENT_DENIED"]
    stock = next((p for p in context.products if p.inStock and p.entitled and p.priceCurrent), None)
    if signal in ("cart_abandoned", "lead_submitted", "case_resolved"):
        journey = {
            "cart_abandoned": "cart-recovery-v1",
            "lead_submitted": "lead-nurture-v1",
            "case_resolved": "service-retention-v1",
        }[signal]
        add(
            "Marketing",
            72,
            {"journeyId": journey},
            promotional
            + email
            + (["ORDER_COMPLETED"] if signal == "cart_abandoned" and context.ordered else [])
            + (
                ["RECOVERY_UNVERIFIED"]
                if signal == "case_resolved" and not context.serviceRecovered
                else []
            ),
        )
    if signal in ("lead_submitted", "product_interest"):
        score = (context.leadFit * 7 + context.engagement * 3) // 10
        add(
            "Sales",
            score,
            {"taskType": "qualified-follow-up"},
            promotional
            + (["LEAD_UNQUALIFIED"] if score < 60 else [])
            + (["SELLER_TASK_EXISTS"] if context.sellerTaskExists else []),
        )
    if signal in ("product_interest", "cart_abandoned"):
        add(
            "Commerce",
            70,
            {"productRef": stock.productRef if stock else "unavailable"},
            promotional
            + (["ORDER_COMPLETED"] if context.ordered else [])
            + ([] if stock else ["NO_ELIGIBLE_PRODUCT"]),
        )
    if signal == "audience_requested":
        add(
            "Advertising",
            65,
            {"audienceRef": context.audienceRef},
            promotional + ([] if context.advertisingConsent else ["ADVERTISING_CONSENT_DENIED"]),
        )
    if signal in ("service_risk", "case_resolved"):
        add(
            "Service",
            100 if context.severeCase else 80,
            {"taskType": "service-recovery"},
            []
            if context.severeCase or context.serviceRecovered
            else ["SERVICE_CONTEXT_UNVERIFIED"],
        )
    candidates.sort(key=lambda c: (-c.score, c.domain))
    return Plan(candidates, agents)
