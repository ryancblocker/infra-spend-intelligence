"""
Purpose: Aggregate the portfolio database into headline spend/asset figures.
Pure arithmetic over the SQLite tables - deterministic by design, no LLM needed,
since totals and counts have exactly one correct answer.
"""

from __future__ import annotations

from app.agents.schemas import DiscoverySummary
from app.tools import dataset_tools


def run() -> DiscoverySummary:
    totals = dataset_tools.portfolio_totals()
    return DiscoverySummary(
        total_annual_spend=totals["total_annual_spend"],
        total_monthly_spend=totals["total_monthly_spend"],
        spend_by_category=totals["spend_by_category"],
        asset_counts=totals["asset_counts"],
    )
