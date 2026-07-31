"""
Purpose: Synthesize every agent's output into one executive-facing summary.
LLM narrative when available; a clear templated equivalent offline so the
top-level page always has something coherent to show.
"""

from __future__ import annotations

from app.agents.schemas import (
    CriticFlag,
    DiscoverySummary,
    Finding,
    PipelineRunSummary,
    RenewalRisk,
    ScenarioResult,
)
from app.tools.llm_client import get_mode, plain_complete, strip_think

NARRATIVE_SYSTEM_PROMPT = (
    "You are writing the opening paragraph of an executive spend-intelligence report. Write 2-4 "
    "sentences, confident and specific, citing the actual dollar figures and counts given. No "
    "headers, no bullet points, no preamble like 'Here is a summary'."
)


def run(discovery: DiscoverySummary, findings: list[Finding], renewal_risks: list[RenewalRisk],
        scenarios: list[ScenarioResult], critic_flags: list[CriticFlag]) -> PipelineRunSummary:
    total_potential_savings = round(sum(f.estimated_annual_savings for f in findings), 2)
    high_priority = sum(1 for f in findings if f.priority == "High")
    high_risk_contracts = sum(1 for r in renewal_risks if r.risk == "HIGH")
    savings_pct = (total_potential_savings / discovery.total_annual_spend * 100) if discovery.total_annual_spend else 0

    top_scenarios = sorted(scenarios, key=lambda s: s.estimated_annual_savings, reverse=True)[:3]

    summary_text = _narrative(discovery, total_potential_savings, high_risk_contracts, savings_pct, top_scenarios)

    top_risks = []
    if high_risk_contracts:
        top_risks.append(f"{high_risk_contracts} contracts have HIGH renewal risk and need immediate action.")
    if total_potential_savings:
        top_risks.append("Underutilized or above-benchmark services are creating avoidable recurring spend.")
    if not top_risks:
        top_risks.append("No major risks detected; continue monitoring cadence.")

    immediate_actions = [
        f"Execute '{s.recommended_action}' for {s.asset_id} to target ~${s.estimated_annual_savings:,.0f} annual savings."
        for s in top_scenarios
    ] or ["Run the pipeline to generate prioritized actions."]

    return PipelineRunSummary(
        llm_mode=get_mode(),
        total_annual_spend=discovery.total_annual_spend,
        total_potential_annual_savings=total_potential_savings,
        number_of_findings=len(findings),
        high_priority_findings=high_priority,
        high_risk_contracts=high_risk_contracts,
        executive_summary=summary_text,
        top_risks=top_risks,
        immediate_actions=immediate_actions,
        critic_flags=critic_flags,
    )


def _narrative(discovery: DiscoverySummary, total_potential_savings: float, high_risk_contracts: int,
               savings_pct: float, top_scenarios: list[ScenarioResult]) -> str:
    if get_mode() != "offline":
        top_lines = "\n".join(
            f"- {s.asset_id}: {s.recommended_action}, ~${s.estimated_annual_savings:,.0f}/yr" for s in top_scenarios
        )
        result = plain_complete(
            system=NARRATIVE_SYSTEM_PROMPT,
            user=(f"Total annual spend: ${discovery.total_annual_spend:,.0f}\n"
                  f"Potential annual savings identified: ${total_potential_savings:,.0f} ({savings_pct:.1f}%)\n"
                  f"High renewal-risk contracts: {high_risk_contracts}\n"
                  f"Top opportunities:\n{top_lines}"),
            agent="narrator",
        )
        # A reasoning model can return nothing but a <think> block; once stripped
        # that is empty, and an empty summary is worse than the templated one.
        if result and strip_think(result).strip():
            return strip_think(result).strip()

    return (
        f"Portfolio intelligence identified ${total_potential_savings:,.0f} in annual savings opportunities "
        f"against a baseline annual spend of ${discovery.total_annual_spend:,.0f} ({savings_pct:.1f}% of spend). "
        f"{high_risk_contracts} contracts are currently high renewal risk. "
        "Acting on the top-ranked opportunities below is the fastest path to realized savings."
    )
