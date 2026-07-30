"""
Purpose: Reflection/guardrail pass over the optimization agent's output. Runs a
deterministic numeric sanity check on every scenario (always on, regardless of
LLM mode - this is the check that actually matters for a spend tool: never let
a savings claim exceed what's mathematically possible from the underlying
contract), plus an optional LLM pass that reviews the highest-value scenarios
for narrative plausibility. Downgrades confidence on anything flagged.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.agents.schemas import CriticFlag, ScenarioResult
from app.tools.llm_client import chat_structured, get_mode

REVIEW_SYSTEM_PROMPT = (
    "You are a skeptical reviewer checking spend-optimization recommendations before they reach "
    "an executive. For each item, flag anything where the business rationale is vague, generic, "
    "or doesn't logically follow from the stated issue and numbers. Only flag genuine problems - "
    "most well-formed recommendations should not be flagged. severity is 'info' or 'warning'."
)


class LLMReview(BaseModel):
    flags: list[CriticFlag] = Field(default_factory=list)


def run(scenarios: list[ScenarioResult]) -> tuple[list[ScenarioResult], list[CriticFlag]]:
    flags: list[CriticFlag] = []
    reviewed: list[ScenarioResult] = []

    for scenario in scenarios:
        scenario, item_flags = _numeric_sanity_check(scenario)
        flags.extend(item_flags)
        reviewed.append(scenario)

    if get_mode() != "offline" and reviewed:
        flags.extend(_llm_review(reviewed[:10]))

    return reviewed, flags


def _numeric_sanity_check(scenario: ScenarioResult) -> tuple[ScenarioResult, list[CriticFlag]]:
    flags: list[CriticFlag] = []
    annualized_keep_cost = (scenario.keep_cost_36mo / 36) * 12 if scenario.keep_cost_36mo else 0

    if annualized_keep_cost > 0 and scenario.estimated_annual_savings > annualized_keep_cost * 1.05:
        flags.append(CriticFlag(
            target_id=scenario.finding_id, target_type="scenario", severity="warning",
            message=(f"Estimated annual savings (${scenario.estimated_annual_savings:,.0f}) exceeds the "
                     f"asset's annualized current cost (${annualized_keep_cost:,.0f}) - recommendation "
                     f"confidence reduced pending manual review."),
        ))
        scenario = scenario.model_copy(update={"confidence": round(min(scenario.confidence, 0.35), 2)})

    if scenario.projected_savings_36mo < 0:
        flags.append(CriticFlag(
            target_id=scenario.finding_id, target_type="scenario", severity="error",
            message="Projected 36-month savings is negative; scenario math should be re-run.",
        ))

    if not (0.0 <= scenario.confidence <= 1.0):
        flags.append(CriticFlag(
            target_id=scenario.finding_id, target_type="scenario", severity="error",
            message="Confidence score out of [0,1] range.",
        ))
        scenario = scenario.model_copy(update={"confidence": max(0.0, min(scenario.confidence, 1.0))})

    if scenario.recommended_action == "Renegotiate" and not scenario.negotiation_talking_points:
        flags.append(CriticFlag(
            target_id=scenario.finding_id, target_type="scenario", severity="info",
            message="Renegotiate recommendation has no negotiation talking points attached.",
        ))

    return scenario, flags


def _llm_review(top_scenarios: list[ScenarioResult]) -> list[CriticFlag]:
    lines = "\n".join(
        f"- [{s.finding_id}] action={s.recommended_action}, confidence={s.confidence}, "
        f"savings=${s.estimated_annual_savings:,.0f}, rationale=\"{s.business_rationale}\""
        for s in top_scenarios
    )
    result = chat_structured(system=REVIEW_SYSTEM_PROMPT, user=f"Recommendations to review:\n{lines}", schema=LLMReview)
    return result.flags if result else []
