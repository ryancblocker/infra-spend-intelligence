"""
Purpose: Shared pydantic contracts passed between agents and rendered by the UI.
Keeping these in one place means every agent - deterministic or LLM-backed -
produces the same shape of finding/recommendation regardless of which backend
generated it.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DiscoverySummary(BaseModel):
    total_annual_spend: float
    total_monthly_spend: float
    spend_by_category: dict[str, float]
    asset_counts: dict[str, int]


class ClauseCitation(BaseModel):
    """Where an extracted value actually came from. Assembled in code from the
    retrieved chunk - never produced by the model."""
    contract_id: str
    chunk_index: int
    heading: str = ""
    excerpt: str = ""


class ContractTerms(BaseModel):
    """LLM-facing extraction schema. Deliberately narrow: clause facts only.

    Kept separate from ExtractedContract because a small local model produces
    clause facts reliably but citation bookkeeping badly - and all of that
    bookkeeping is derivable in code anyway."""
    vendor: str = ""
    category: str = ""
    auto_renew: bool = False
    renewal_date: str = ""
    notice_period_days: int | None = None
    termination_fee_pct: float | None = None
    annual_escalator_pct: float | None = None
    minimum_commitment: str = ""
    # The contract states its price; reading a written-down number is extraction,
    # not calculation. Every *derived* figure stays in Python - see
    # extraction.reconcile_costs.
    monthly_cost: float | None = None
    annual_cost: float | None = None
    sla_summary: str = ""
    liability_cap_summary: str = ""
    has_mfn_clause: bool = False
    has_price_protection_clause: bool = False
    risk_level: str = "Low"  # Low | Medium | High
    risk_rationale: str = ""


class RevisionRequest(BaseModel):
    """A critic-raised objection routed back to the optimization agent."""
    finding_id: str
    critique: str


class ExtractedContract(BaseModel):
    contract_id: str
    vendor: str = ""
    category: str = ""
    auto_renew: bool = False
    renewal_date: str = ""
    notice_period_days: int | None = None
    termination_fee_pct: float | None = None
    annual_escalator_pct: float | None = None
    minimum_commitment: str = ""
    monthly_cost: float | None = None
    annual_cost: float | None = None
    sla_summary: str = ""
    liability_cap_summary: str = ""
    has_mfn_clause: bool = False
    has_price_protection_clause: bool = False
    risk_level: str = "Low"  # Low | Medium | High
    risk_rationale: str = ""
    extraction_source: str = "offline"  # ollama | anthropic | offline

    # --- agent trace / provenance, assembled by the extraction loop ---
    field_sources: dict[str, ClauseCitation] = Field(default_factory=dict)
    extraction_iterations: int = 1
    unresolved_fields: list[str] = Field(default_factory=list)
    injection_flags: list[str] = Field(default_factory=list)
    retrieval_queries: list[str] = Field(default_factory=list)


class Finding(BaseModel):
    finding_id: str
    category: str  # e.g. telecom_underutilization, license_underutilization, benchmark_variance, owner_gap
    asset_id: str
    contract_id: str = ""
    issue: str
    current_monthly_cost: float = 0.0
    estimated_monthly_savings: float = 0.0
    estimated_annual_savings: float = 0.0
    recommended_action: str = "Review with owner"
    priority: str = "Low"  # Low | Medium | High


class ScenarioResult(BaseModel):
    finding_id: str
    asset_id: str
    contract_id: str = ""
    category: str = ""
    issue: str = ""
    recommended_action: str = "Review with owner"
    risk_level: str = "Low"
    confidence: float = 0.5
    business_rationale: str = ""
    negotiation_talking_points: list[str] = Field(default_factory=list)
    keep_cost_36mo: float = 0.0
    cancel_cost_36mo: float = 0.0
    renegotiate_cost_36mo: float = 0.0
    projected_savings_36mo: float = 0.0
    break_even_months: float = 0.0
    estimated_annual_savings: float = 0.0
    source: str = "offline"


class RenewalRisk(BaseModel):
    contract_id: str
    vendor: str
    contract_label: str
    renewal_date: str
    notice_deadline: str
    days_remaining: int
    days_to_notice_deadline: int
    auto_renew: bool
    notice_window_closing: bool
    risk: str  # LOW | MEDIUM | HIGH
    recommended_action: str
    annual_cost: float


class CriticFlag(BaseModel):
    target_id: str
    target_type: str  # scenario | narrative
    severity: str  # info | warning | error
    message: str


class PipelineRunSummary(BaseModel):
    llm_mode: str
    total_annual_spend: float
    total_potential_annual_savings: float
    number_of_findings: int
    high_priority_findings: int
    high_risk_contracts: int
    executive_summary: str
    top_risks: list[str] = Field(default_factory=list)
    immediate_actions: list[str] = Field(default_factory=list)
    critic_flags: list[CriticFlag] = Field(default_factory=list)
    # How the optimization step actually produced its recommendations: only
    # the highest-impact findings are reasoned about by the model (see
    # config.MAX_LLM_SCENARIOS); the rest use the deterministic rule engine.
    # Surfaced so the UI never implies every scenario was model-reasoned.
    scenarios_llm_reasoned: int = 0
    scenarios_deterministic: int = 0
