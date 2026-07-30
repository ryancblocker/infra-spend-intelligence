"""
Unit tests for the deterministic math in the agent pipeline - the parts that
must be correct regardless of which LLM backend (or none) is active.
"""

from __future__ import annotations

from app.agents import critic, discovery, optimization, waste
from app.agents.renewal import _recommended_action, _risk
from app.agents.schemas import Finding, ScenarioResult
from app.tools import dataset_tools

# --- Discovery: portfolio totals must reconcile exactly ---


def test_discovery_totals_match_category_sum():
    summary = discovery.run()
    assert summary.total_annual_spend > 0
    assert round(sum(summary.spend_by_category.values()), 2) == summary.total_annual_spend


def test_discovery_asset_counts_match_dataset():
    summary = discovery.run()
    assert summary.asset_counts["contracts"] == len(dataset_tools.fetch_contracts())
    assert summary.asset_counts["circuits"] == len(dataset_tools.fetch_circuits())
    assert summary.asset_counts["licenses"] == len(dataset_tools.fetch_licenses())


def test_discovery_monthly_is_annual_over_twelve():
    summary = discovery.run()
    assert round(summary.total_annual_spend / 12, 2) == summary.total_monthly_spend


# --- Renewal risk classification ---


def test_renewal_risk_imminent_is_always_high():
    assert _risk(days_remaining=10, notice_closing=False, auto_renew=False, annual_value=0) == "HIGH"


def test_renewal_risk_large_contract_far_out_is_not_high():
    # A big contract renewing in ~2 years should not be flagged HIGH just for size.
    assert _risk(days_remaining=700, notice_closing=False, auto_renew=True, annual_value=5_000_000) == "MEDIUM"


def test_renewal_risk_large_auto_renew_inside_window_is_high():
    assert _risk(days_remaining=45, notice_closing=False, auto_renew=True, annual_value=300_000) == "HIGH"


def test_renewal_risk_small_auto_renew_inside_window_is_medium():
    assert _risk(days_remaining=45, notice_closing=False, auto_renew=True, annual_value=50_000) == "MEDIUM"


def test_renewal_risk_notice_window_closing_forces_high():
    assert _risk(days_remaining=200, notice_closing=True, auto_renew=True, annual_value=1_000) == "HIGH"


def test_renewal_action_escalates_when_notice_closing():
    action = _recommended_action("HIGH", auto_renew=True, notice_closing=True)
    assert "Escalate" in action


# --- Waste detection thresholds ---


def test_waste_underutilization_threshold_is_exclusive():
    assert waste.UNDERUTILIZATION_THRESHOLD_PCT == 25


def test_waste_run_only_flags_below_threshold():
    findings = waste.run()
    circuit_findings = [f for f in findings if f.category == "telecom_underutilization"]
    circuits_by_id = {c["circuit_id"]: c for c in dataset_tools.fetch_circuits()}
    for f in circuit_findings:
        util = float(circuits_by_id[f.asset_id]["utilization_pct"])
        assert util < 25


# --- Optimization: cost scenario math ---


def _sample_finding(annual_savings=60_000, monthly_cost=5_000, category="benchmark_variance") -> Finding:
    return Finding(
        finding_id="TEST-0001", category=category, asset_id="CIRC-TEST", contract_id="C-TEST",
        issue="test issue", current_monthly_cost=monthly_cost,
        estimated_monthly_savings=annual_savings / 12, estimated_annual_savings=annual_savings,
        recommended_action="Renegotiate", priority="High",
    )


def test_cost_scenarios_keep_cost_is_36_months_of_current_spend():
    finding = _sample_finding(monthly_cost=5_000)
    keep, cancel, renegotiate, savings, break_even = optimization._cost_scenarios(finding, {"termination_fee_pct": 10})
    assert keep == 5_000 * 36


def test_cost_scenarios_cancel_cost_uses_contract_termination_fee():
    finding = _sample_finding(monthly_cost=5_000)
    keep, cancel, renegotiate, savings, break_even = optimization._cost_scenarios(finding, {"termination_fee_pct": 20})
    assert cancel == 5_000 * 12 * 0.20


def test_cost_scenarios_projected_savings_never_negative():
    finding = _sample_finding(annual_savings=1, monthly_cost=100)
    _, _, _, savings, _ = optimization._cost_scenarios(finding, {"termination_fee_pct": 10})
    assert savings >= 0


def test_deterministic_action_cancels_high_value_underutilization():
    finding = _sample_finding(annual_savings=50_000, category="license_underutilization")
    action = optimization._deterministic_action(finding)
    assert action["recommended_action"] == "Cancel"


def test_deterministic_action_confidence_bounded():
    for annual in (1_000, 500_000):
        finding = _sample_finding(annual_savings=annual)
        action = optimization._deterministic_action(finding)
        assert 0.1 <= action["confidence"] <= 0.95


# --- Critic: numeric grounding guardrail ---


def test_critic_flags_savings_exceeding_annualized_cost():
    # 36mo keep cost of $36,000 implies ~$12,000/yr - claiming $500k/yr savings
    # from that asset is not mathematically possible and must be caught.
    bad_scenario = ScenarioResult(
        finding_id="F-1", asset_id="A-1", recommended_action="Cancel", confidence=0.9,
        business_rationale="test", keep_cost_36mo=36_000, cancel_cost_36mo=5_000,
        renegotiate_cost_36mo=20_000, projected_savings_36mo=31_000, break_even_months=2,
        estimated_annual_savings=500_000,
    )
    reviewed, flags = critic.run([bad_scenario])
    assert any(f.severity in ("warning", "error") for f in flags)
    assert reviewed[0].confidence <= 0.35


def test_critic_does_not_flag_well_formed_scenario():
    good_scenario = ScenarioResult(
        finding_id="F-2", asset_id="A-2", recommended_action="Renegotiate", confidence=0.7,
        business_rationale="test", negotiation_talking_points=["ask for a discount"],
        keep_cost_36mo=360_000, cancel_cost_36mo=50_000, renegotiate_cost_36mo=280_000,
        projected_savings_36mo=80_000, break_even_months=2, estimated_annual_savings=25_000,
    )
    reviewed, flags = critic.run([good_scenario])
    assert flags == []
    assert reviewed[0].confidence == 0.7
