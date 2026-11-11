import hashlib
import json
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field

from growth.contracts import DTO, Proposal, Snapshot


class Policy(DTO):
    version: str
    purpose: Literal["cart_recovery"]
    region: Literal["us-east-1"]
    dryRun: bool = True
    requireApproval: bool = False
    approvedJourney: str
    experiment: str
    holdoutFraction: float = Field(ge=0, le=1)
    frequencyHours: int = Field(gt=0)
    maxAttempts: int = Field(ge=1, le=10)
    observationHours: int = Field(gt=0)
    allowedTools: dict[str, list[str]]

    @classmethod
    def load(cls, path: str) -> "Policy":
        return cls.model_validate(yaml.safe_load(Path(path).read_text()))


def assignment(tenant: str, customer: str, policy: Policy) -> str:
    key = json.dumps([tenant, customer, policy.experiment], separators=(",", ":"))
    fraction = int(hashlib.sha256(key.encode()).hexdigest()[:16], 16) / 2**64
    return "control" if fraction < policy.holdoutFraction else "treatment"


def reasons(snapshot: Snapshot, *, killed: bool, frequency: bool) -> list[str]:
    gates = [
        (not snapshot.sourceAvailable, "SOURCE_UNAVAILABLE"),
        (not snapshot.identityKnown, "IDENTITY_UNKNOWN"),
        (not snapshot.purposeAllowed, "PURPOSE_DENIED"),
        (not snapshot.consent, "CONSENT_DENIED"),
        (snapshot.severeCase, "OPEN_CRITICAL_CASE"),
        (snapshot.ordered, "ORDER_COMPLETED"),
        (not snapshot.inStock, "OUT_OF_STOCK"),
        (not snapshot.priceCurrent, "STALE_PRICE"),
        (frequency, "FREQUENCY_CAP"),
        (killed, "KILL_SWITCH"),
    ]
    return [reason for denied, reason in gates if denied]


def authorize(proposal: Proposal, policy: Policy) -> bool:
    return (
        proposal.domain == "Marketing"
        and proposal.tool == "trigger_approved_journey"
        and proposal.tool in policy.allowedTools.get(proposal.domain, [])
        and proposal.journeyId == policy.approvedJourney
        and proposal.policyVersion == policy.version
    )
