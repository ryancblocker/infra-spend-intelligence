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
4. Financial Optimization Agent combines discovery, waste, and contract intelligence outputs to create `outputs/financial_optimization_output.json`.
5. Dashboard pages consume these JSON files to show spend, waste opportunities, and top recommendations.

## Agent Flow
Discovery Agent -> Waste Detection Agent -> Contract Intelligence Agent -> Financial Optimization Agent -> Dashboard

## Suggested Commands
- python agents/discovery_agent.py
- python agents/waste_detection_agent.py
- python agents/contract_intelligence_agent.py
- python agents/financial_optimization_agent.py
- streamlit run ui/app.py

## TODO (SOFIA)
- Add workflow automation script
- Add error handling and rollback strategy for failed stages
- Add optional downstream agents (renewal and scenario) after vertical slice validation
