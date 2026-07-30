<!--
Purpose: Describe the operating workflow from data ingestion through executive dashboard reporting.
Inputs: Agent definitions, output contracts, and execution dependencies.
Outputs: Repeatable runbook for development, testing, and demos.
Assigned Team Member: SOFIA
Dependencies: Project README, agent scripts, and output schemas.
-->

# Infra Spend Intelligence Workflow

## Sequential Steps
1. Discovery Agent reads source CSV files and creates `outputs/discovery_output.json`.
2. Waste Detection Agent reads discovery + source data and creates `outputs/waste_findings.json`.
3. Contract Intelligence Agent reads `contract_texts/` and creates `outputs/contract_intelligence_output.json`.
4. Renewal Intelligence Agent reads contracts plus prior outputs to create `outputs/renewal_intelligence_output.json` when available.
5. Scenario Comparison Agent evaluates keep/cancel/renegotiate outcomes in `outputs/scenario_comparison_output.json` when available.
6. Financial Optimization Agent combines discovery, waste, and contract intelligence outputs to create `outputs/financial_optimization_output.json`.
7. Executive Summary Agent creates `outputs/executive_summary.json` when available.
8. Dashboard pages consume these JSON files to show spend, waste opportunities, and top recommendations.

## Agent Flow
Discovery Agent -> Waste Detection Agent -> Contract Intelligence Agent -> Renewal Intelligence Agent -> Scenario Comparison Agent -> Financial Optimization Agent -> Executive Summary Agent -> Dashboard

## Run From Terminal
- streamlit run ui/app.py

## Run Pipeline From Dashboard
1. Open the dashboard with `streamlit run ui/app.py`.
2. Click `Run Pipeline`.
3. Wait for pipeline completion and refreshed output JSON files.
4. Review executive metrics, findings, scenarios, and recommendations.

Run Pipeline button note:
The `Run Pipeline` button executes the full agent workflow and refreshes JSON outputs used by the dashboard.

## TODO (SOFIA)
- Add workflow automation script
- Add error handling and rollback strategy for failed stages
- Add optional downstream agents (renewal and scenario) after vertical slice validation
