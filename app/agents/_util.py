"""Shared helpers for the deterministic finding-producing agents (waste, benchmark)."""

from __future__ import annotations

from app.agents.schemas import Finding


def priority_for(annual_savings: float, category: str) -> str:
    if annual_savings > 50_000 or "contract" in category:
        return "High"
    if annual_savings > 15_000:
        return "Medium"
    return "Low"


class FindingIdSequence:
    def __init__(self, prefix: str) -> None:
        self._prefix = prefix
        self._n = 0

    def next(self) -> str:
        self._n += 1
        return f"{self._prefix}-{self._n:04d}"


def build_finding(finding_id: str, category: str, asset_id: str, contract_id: str, issue: str,
                   current_monthly_cost: float, estimated_monthly_savings: float,
                   recommended_action: str) -> Finding:
    annual_savings = round(estimated_monthly_savings * 12, 2)
    return Finding(
        finding_id=finding_id,
        category=category,
        asset_id=asset_id,
        contract_id=contract_id,
        issue=issue,
        current_monthly_cost=round(current_monthly_cost, 2),
        estimated_monthly_savings=round(estimated_monthly_savings, 2),
        estimated_annual_savings=annual_savings,
        recommended_action=recommended_action,
        priority=priority_for(annual_savings, category),
    )
