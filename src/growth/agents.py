from dataclasses import dataclass
from typing import Literal

from growth.contracts import Proposal, Snapshot
from growth.policy import Policy

Domain = Literal["Marketing", "Advertising", "Sales", "Commerce", "Service"]


@dataclass(frozen=True)
class AgentTask:
    task_id: str
    tenant: str
    customer: str
    purpose: Literal["cart_recovery"]
    snapshot_hash: str
    allowed_tools: tuple[str, ...]


@dataclass(frozen=True)
class DomainAgent:
    domain: Domain

    def propose(self, task: AgentTask, context: Snapshot, policy: Policy) -> Proposal:
        """Deterministic baseline. Structured model outputs must pass the same DTO/gateway."""
        marketing = self.domain == "Marketing"
        tool = "trigger_approved_journey" if marketing else "recommend_only"
        if tool not in task.allowed_tools:
            raise ValueError("TOOL_NOT_ALLOWED")
        rationale = {
            "Marketing": ["APPROVED_RECOVERY_CANDIDATE"],
            "Advertising": ["PAID_MEDIA_READ_ONLY"],
            "Sales": ["SELLER_ACTION_POST_MVP"],
            "Commerce": ["ORDER_COMPLETED" if context.ordered else "CART_CONTEXT_CHECKED"],
            "Service": ["OPEN_CRITICAL_CASE" if context.severeCase else "SERVICE_CONTEXT_CHECKED"],
        }
        return Proposal(
            domain=self.domain,
            taskId=task.task_id,
            tool=tool,
            journeyId=policy.approvedJourney if marketing else None,
            policyVersion=policy.version,
            rationale=rationale[self.domain],
        )


AGENTS = tuple(DomainAgent(d) for d in ("Marketing", "Advertising", "Sales", "Commerce", "Service"))
