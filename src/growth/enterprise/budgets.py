from decimal import ROUND_DOWN, Decimal
from typing import Any

from growth.enterprise.contracts import BudgetDraft


def recommend(draft: BudgetDraft) -> dict[str, Any]:
    # Descriptive contribution efficiency only; observed returns never imply causal lift.
    budget = Decimal(str(draft.totalBudget)).quantize(Decimal(".01"), rounding=ROUND_DOWN)
    scores = [max(0, c.contribution - c.spend) / max(1, c.spend) for c in draft.channels]
    mature = draft.observations >= 100 and sum(c.conversions for c in draft.channels) >= 20
    if not mature or not any(scores):
        scores = [1.0 for _ in draft.channels]
    total = sum(scores)
    allocations = []
    allocated = Decimal(0)
    for i, channel in enumerate(draft.channels):
        amount = (budget * Decimal(str(scores[i] / total))).quantize(
            Decimal(".01"), rounding=ROUND_DOWN
        )
        if i == len(draft.channels) - 1:
            amount = budget - allocated
        allocated += amount
        allocations.append({"channel": channel.channel, "proposedBudget": str(amount)})
    return {
        "currency": draft.currency,
        "totalBudget": str(budget),
        "allocations": allocations,
        "recommendationOnly": True,
        "executionSupported": False,
        "humanApprovalRequired": True,
        "reasonCodes": ["DESCRIPTIVE_EFFICIENCY" if mature else "INSUFFICIENT_EXPERIMENT_EVIDENCE"],
        "interpretation": "Descriptive draft only; no causal lift or spend authorization.",
    }
