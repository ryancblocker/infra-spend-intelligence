"""Purpose: Shared state object threaded through every node in the LangGraph pipeline."""

from __future__ import annotations

from typing import TypedDict

from app.agents.schemas import (
    CriticFlag,
    DiscoverySummary,
    ExtractedContract,
    Finding,
    PipelineRunSummary,
    RenewalRisk,
    ScenarioResult,
)


class PipelineState(TypedDict, total=False):
    discovery: DiscoverySummary
    extracted_contracts: list[ExtractedContract]
    waste_findings: list[Finding]
    benchmark_findings: list[Finding]
    benchmark_narrative: str
    renewal_risks: list[RenewalRisk]
    renewal_narrative: str
    scenarios: list[ScenarioResult]
    critic_flags: list[CriticFlag]
    summary: PipelineRunSummary


def empty_state() -> PipelineState:
    return PipelineState()
