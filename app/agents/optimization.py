"""
Purpose: Turn findings into keep/cancel/renegotiate recommendations. Cost
projections (keep/cancel/renegotiate spend, break-even) are always computed
deterministically from contract terms - the LLM is never asked to produce a
dollar figure, only judgment: which action, how confident, why, and what to
say in a renegotiation conversation. That split is what keeps this agent
grounded rather than a plausible-sounding hallucination machine (the critic
agent double-checks it anyway).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app import config
from app.agents.schemas import Finding, RevisionRequest, ScenarioResult
from app.tools import dataset_tools
from app.tools.llm_client import chat_structured, get_mode

HORIZON_MONTHS = 36
TOP_N_FOR_LLM_JUDGMENT = 15


class OptimizationJudgment(BaseModel):
    recommended_action: str  # Keep but monitor | Right-size | Cancel | Renegotiate | Review with owner
    confidence: float
    risk_level: str  # Low | Medium | High
    business_rationale: str
    negotiation_talking_points: list[str] = Field(default_factory=list)


JUDGMENT_SYSTEM_PROMPT = (
    "You are a sourcing/procurement strategist advising on an infrastructure or SaaS spend "
    "finding. You are given the finding, the current monthly cost, and pre-computed 36-month "
    "cost projections for keeping, cancelling, and renegotiating - do not recompute or restate "
    "different numbers than the ones given. Choose recommended_action from: 'Keep but monitor', "
    "'Right-size', 'Cancel', 'Renegotiate', 'Review with owner'. confidence is 0.1-0.95. "
    "business_rationale is one sentence. negotiation_talking_points is 2-4 short, concrete "
    "phrases a procurement lead could use in a renegotiation call."
)


def run(findings: list[Finding]) -> list[ScenarioResult]:
    contracts_by_id = {c["contract_id"]: c for c in dataset_tools.fetch_contracts()}

    scored = [(_deterministic_action(f), f) for f in findings]
    scored.sort(key=lambda pair: pair[1].estimated_annual_savings, reverse=True)

    results: list[ScenarioResult] = []
    llm_budget = TOP_N_FOR_LLM_JUDGMENT

    for action, finding in scored:
        contract = contracts_by_id.get(finding.contract_id, {})
        keep_cost, cancel_cost, renegotiate_cost, projected_savings, break_even = _cost_scenarios(finding, contract)

        judgment = None
        is_high_value = finding.estimated_annual_savings >= config.HIGH_VALUE_THRESHOLD or action["risk_level"] == "High"
        if is_high_value and llm_budget > 0 and get_mode() != "offline":
            judgment = _llm_judgment(finding, keep_cost, cancel_cost, renegotiate_cost,
                                     projected_savings)
            llm_budget -= 1

        recommended_action = judgment.recommended_action if judgment else action["recommended_action"]
        confidence = judgment.confidence if judgment else action["confidence"]
        risk_level = judgment.risk_level if judgment else action["risk_level"]
        rationale = judgment.business_rationale if judgment else action["business_rationale"]
        talking_points = judgment.negotiation_talking_points if judgment else action["talking_points"]

        results.append(ScenarioResult(
            finding_id=finding.finding_id,
            asset_id=finding.asset_id,
            contract_id=finding.contract_id,
            category=finding.category,
            issue=finding.issue,
            recommended_action=recommended_action,
            risk_level=risk_level,
            confidence=round(confidence, 2),
            business_rationale=rationale,
            negotiation_talking_points=talking_points,
            keep_cost_36mo=round(keep_cost, 2),
            cancel_cost_36mo=round(cancel_cost, 2),
            renegotiate_cost_36mo=round(renegotiate_cost, 2),
            projected_savings_36mo=round(projected_savings, 2),
            break_even_months=break_even,
            estimated_annual_savings=finding.estimated_annual_savings,
            source="ollama" if judgment and get_mode() == "ollama" else
                   ("anthropic" if judgment and get_mode() == "anthropic" else "offline"),
        ))

    return results


REVISION_SYSTEM_PROMPT = (
    JUDGMENT_SYSTEM_PROMPT
    + " A reviewer has rejected your previous recommendation. Address their objection "
    "directly and produce a more specific, better-grounded judgement. The cost figures "
    "you are given are fixed and authoritative - do not dispute or restate them."
)

# Only these fields may change in a revision. Every cost projection is computed
# deterministically upstream, so a regeneration pass must never touch them -
# that separation is what keeps this agent grounded rather than a plausible-
# sounding hallucination machine.
REVISABLE_FIELDS = (
    "recommended_action", "risk_level", "confidence",
    "business_rationale", "negotiation_talking_points",
)


def revise(scenarios: list[ScenarioResult], requests: list[RevisionRequest]) -> list[ScenarioResult]:
    """Regenerate the judgement on critic-flagged scenarios only. Cost numbers
    pass through untouched; unflagged scenarios are returned by identity."""
    if not requests or get_mode() == "offline":
        return scenarios

    critiques = {request.finding_id: request.critique for request in requests}
    revised: list[ScenarioResult] = []
    for scenario in scenarios:
        critique = critiques.get(scenario.finding_id)
        if critique is None:
            revised.append(scenario)
            continue

        judgment = _revised_judgment(scenario, critique)
        if judgment is None:
            revised.append(scenario)
            continue

        revised.append(scenario.model_copy(update={
            "recommended_action": judgment.recommended_action,
            "risk_level": judgment.risk_level,
            "confidence": round(max(0.0, min(judgment.confidence, 1.0)), 2),
            "business_rationale": judgment.business_rationale,
            "negotiation_talking_points": judgment.negotiation_talking_points,
            "source": f"{get_mode()}-revised",
        }))
    return revised


def _revised_judgment(scenario: ScenarioResult, critique: str) -> OptimizationJudgment | None:
    user = (
        f"Finding: {scenario.issue}\n"
        f"Category: {scenario.category}\n"
        f"Asset: {scenario.asset_id} (contract {scenario.contract_id})\n"
        f"Estimated annual savings if addressed: ${scenario.estimated_annual_savings:,.2f}\n"
        f"36-month projection - keep: ${scenario.keep_cost_36mo:,.0f}, "
        f"cancel: ${scenario.cancel_cost_36mo:,.0f}, "
        f"renegotiate: ${scenario.renegotiate_cost_36mo:,.0f}, "
        f"projected savings: ${scenario.projected_savings_36mo:,.0f}\n\n"
        f"Your previous recommendation was '{scenario.recommended_action}' with this "
        f"rationale: \"{scenario.business_rationale}\"\n"
        f"Reviewer objection: {critique}"
    )
    return chat_structured(system=REVISION_SYSTEM_PROMPT, user=user,
                           schema=OptimizationJudgment, agent="optimization-revise")


def _deterministic_action(finding: Finding) -> dict:
    category = finding.category.lower()
    annual = finding.estimated_annual_savings
    issue = finding.issue.lower()

    if "owner_gap" in category:
        action = "Review with owner"
    elif "underutilization" in category and annual >= 40_000:
        action = "Cancel"
    elif "underutilization" in category:
        action = "Right-size"
    elif "benchmark_variance" in category or "rate" in issue:
        action = "Renegotiate"
    elif "inactive" in category and annual >= 12_000:
        action = "Cancel"
    elif annual <= 5_000:
        action = "Keep but monitor"
    else:
        action = "Review with owner"

    risk_level = "High" if annual >= 100_000 or "termination" in issue else (
        "Medium" if action in ("Renegotiate", "Cancel") and annual >= 30_000 else "Low")

    confidence = 0.55
    if annual >= 50_000:
        confidence += 0.2
    if "underutilization" in category or "inactive" in category:
        confidence += 0.15
    if "owner_gap" in category:
        confidence -= 0.2
    if action == "Keep but monitor":
        confidence -= 0.1
    confidence = round(max(0.1, min(confidence, 0.95)), 2)

    rationale = (
        f"{finding.asset_id} has issue '{finding.issue}'. Action '{action}' is expected to recover "
        f"approximately ${annual:,.0f} annually."
    )
    talking_points = _default_talking_points(action, finding)

    return {
        "recommended_action": action, "risk_level": risk_level, "confidence": confidence,
        "business_rationale": rationale, "talking_points": talking_points,
    }


def _default_talking_points(action: str, finding: Finding) -> list[str]:
    if action == "Renegotiate":
        return [
            "Cite current usage/utilization data as leverage for a rate reduction.",
            "Ask for benchmark-aligned pricing at renewal or threaten competitive RFP.",
        ]
    if action == "Cancel":
        return ["Confirm no dependent workloads/users before cancellation.", "Request pro-rated final invoice."]
    if action == "Right-size":
        return ["Propose a reduced commitment tier matching actual usage."]
    return ["Confirm ownership and business justification before next renewal."]


def _cost_scenarios(finding: Finding, contract: dict) -> tuple[float, float, float, float, float]:
    monthly_cost = finding.current_monthly_cost
    if monthly_cost <= 0:
        monthly_cost = finding.estimated_annual_savings / 12 if finding.estimated_annual_savings > 0 else 1000

    keep_cost = monthly_cost * HORIZON_MONTHS
    penalty_pct = float(contract.get("termination_fee_pct", 10) or 10) / 100.0
    cancel_cost = monthly_cost * 12 * penalty_pct
    renegotiate_cost = max(keep_cost * 0.72, keep_cost - (finding.estimated_annual_savings * 1.5))

    projected_savings = max(keep_cost - min(cancel_cost, renegotiate_cost), 0)
    monthly_delta = projected_savings / HORIZON_MONTHS
    break_even = 0.0 if monthly_delta <= 0 else round(cancel_cost / monthly_delta, 1)

    return keep_cost, cancel_cost, renegotiate_cost, projected_savings, break_even


def _llm_judgment(finding: Finding, keep_cost: float, cancel_cost: float, renegotiate_cost: float,
                   projected_savings: float) -> OptimizationJudgment | None:
    user = (
        f"Finding: {finding.issue}\n"
        f"Category: {finding.category}\n"
        f"Asset: {finding.asset_id} (contract {finding.contract_id})\n"
        f"Current monthly cost: ${finding.current_monthly_cost:,.2f}\n"
        f"Estimated annual savings if addressed: ${finding.estimated_annual_savings:,.2f}\n"
        f"36-month projection - keep: ${keep_cost:,.0f}, cancel: ${cancel_cost:,.0f}, "
        f"renegotiate: ${renegotiate_cost:,.0f}, projected savings: ${projected_savings:,.0f}"
    )
    return chat_structured(system=JUDGMENT_SYSTEM_PROMPT, user=user, schema=OptimizationJudgment)
