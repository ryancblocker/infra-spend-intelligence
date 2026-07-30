# PACT - Portfolio Agentic Contract Tracker

PACT is a local-first, agentic infrastructure and SaaS spend intelligence
platform. It analyzes a portfolio of contracts (telecom circuits, colocation,
software licenses, mobile lines) with an eight-agent LangGraph pipeline -
extracting contract terms from unstructured text, detecting waste, comparing
rates to market benchmarks, flagging renewal risk, and generating keep /
cancel / renegotiate recommendations with a critic pass for grounding - all
running against a local model via [Ollama](https://ollama.com), with an
Anthropic cloud fallback and a fully offline deterministic mode.

## What it does

- **Discovers** total spend and asset counts across the portfolio
- **Extracts** renewal terms, SLAs, liability caps, and MFN/price-protection
  clauses from real contract prose (LLM, RAG-grounded)
- **Detects waste**: underutilized circuits/colocation/licenses, unassigned or
  inactive mobile lines, missing ownership
- **Benchmarks** rates against 2026 market research (telecom, colocation,
  SaaS, mobility)
- **Flags renewal risk** with notice-deadline-aware urgency
- **Recommends** keep/cancel/renegotiate per finding with 36-month cost
  projections and negotiation talking points
- **Checks its own work**: a critic agent flags any recommendation whose
  numbers don't hold up before it reaches the UI
- **Answers questions** about the portfolio via a RAG chat interface (`/ask`)

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8420
```

Open http://localhost:8420 and click **Run Analysis**. That's it - the
database auto-seeds on first run, and the app works fully offline. See
[`docs/setup.md`](docs/setup.md) to add a local LLM (Ollama) for the full
agentic experience, and [`docs/architecture.md`](docs/architecture.md) for
how the pipeline is built.

## Project layout

```
app/
  main.py            FastAPI app - pages, SSE pipeline run, /api/ask
  agents/             the eight pipeline agents
  orchestrator/        LangGraph wiring, state, progress events
  tools/                dataset access, vector search, LLM client
  data/                  seed CSVs, contract docs, DB/index builders
  templates/, static/     Jinja2 pages + vanilla CSS/JS design system
docs/                architecture.md, setup.md
tests/               unit tests for the deterministic agents
```

## Team ownership

Four owned areas, split along the architecture's natural seams (data/rules vs.
LLM reasoning, backend vs. frontend). Cross-area PRs are normal - these are
primary owners, not walls.

| Owner | Area | Owns | Files | First thing to check |
|---|---|---|---|---|
| **Seth** | Data & Rules Agents | Synthetic dataset realism, benchmark accuracy, and the four deterministic/rules-based agents | `app/data/` (`generate_seed_data.py`, `seed_db.py`, `seed/*.csv`, `contract_docs/*.txt`), `app/agents/discovery.py`, `waste.py`, `benchmark.py`, `renewal.py` | Run `python app/data/generate_seed_data.py` and sanity-check the printed totals/category mix still look like a believable portfolio |
| **Sofia** | LLM & Reasoning Agents | Prompt quality, structured-output reliability, RAG grounding, and the four LLM-backed agents | `app/agents/extraction.py`, `optimization.py`, `critic.py`, `narrator.py`, `app/tools/llm_client.py`, `vector_store.py` | Install Ollama (`docs/setup.md`), pull `qwen3:8b` + `nomic-embed-text`, and compare a pipeline run in `ollama` mode vs. the offline fallback |
| **Jessie** | Backend & Orchestration | Pipeline wiring, API routes, SSE streaming, persistence | `app/orchestrator/` (`graph.py`, `state.py`, `events.py`, `persistence.py`), `app/main.py`, `app/views.py`, `app/tools/dataset_tools.py`, `app/config.py` | Trigger `GET /api/run` and confirm every agent's SSE event lands in the right order and `runtime/last_run.json` round-trips correctly |
| **Ryan** | Frontend, Docs & QA | Visual design, UI/UX, documentation, test coverage | `app/templates/`, `app/static/`, `docs/`, `tests/`, `README.md` | Click through all 6 pages in both light and dark theme, then run `pytest tests/` |

## Tests

```bash
pytest tests/
```
