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

Four owned areas, split along the architecture's natural seams: data and
deterministic rules, LLM reasoning, backend/orchestration, and frontend. Each
person below owns their area end to end - designing it, building it, and
being the first call when something in it breaks. Cross-area PRs are normal
and encouraged; these are primary owners, not walls, and the areas hand off
to each other constantly (e.g. Seth's data feeds Sofia's prompts, Jessy's API
serves Ryan's pages).

| Owner | Area |
|---|---|
| **Seth** | Data & Rules Agents |
| **Sofia** | LLM & Reasoning Agents |
| **Jessy** | Backend & Orchestration |
| **Ryan** | Frontend, Docs & QA |

### Seth — Data & Rules Agents

**Scope:** everything that defines what the portfolio looks like, and the
four agents that reason over it with fixed, deterministic logic rather than a
model. If a number in the app is wrong, it's either bad source data or a bug
in one of these four agents - both are Seth's to fix.

**Responsibilities:**
- Keep the synthetic dataset (`app/data/generate_seed_data.py`) realistic and
  grounded in actual market pricing - vendor mix, contract volume, and the
  telecom/colocation/SaaS/mobile pricing bands should hold up to scrutiny.
  Regenerating the dataset should always produce a believable spend profile,
  not obviously fake or wildly inconsistent numbers.
- Write and maintain the sample contract documents in `app/data/contract_docs/`
  that Sofia's extraction agent parses - these need real clause language
  (SLA terms, termination fees, auto-renew, MFN/price-protection), not
  key:value stubs, or extraction has nothing meaningful to demonstrate.
- Own the four rules-based agents and their thresholds:
  - `discovery.py` - portfolio spend/asset aggregation (pure arithmetic, must
    reconcile exactly with the underlying data)
  - `waste.py` - underutilization thresholds (circuits, colocation, licenses)
    and unassigned/inactive mobile line detection
  - `benchmark.py` - rate-vs-market-benchmark comparison logic
  - `renewal.py` - renewal-risk date math and urgency classification
- Tune thresholds so findings feel like a real audit, not noise - e.g. if
  every contract gets flagged HIGH risk or savings claims exceed a
  believable percentage of total spend, that's a threshold bug here.

**Key files:** `app/data/` (`generate_seed_data.py`, `seed_db.py`,
`seed/*.csv`, `contract_docs/*.txt`), `app/agents/discovery.py`, `waste.py`,
`benchmark.py`, `renewal.py`.

**First thing to check:** run `python app/data/generate_seed_data.py` and
read the printed totals - does the category mix and dollar figure look like
a real mid-size company's infrastructure spend?

### Sofia — LLM & Reasoning Agents

**Scope:** the four agents that call a language model, and the plumbing that
makes those calls reliable - the model client, structured-output validation,
and retrieval (RAG). This is the "agentic AI" part of the product; Sofia owns
whether it's actually good at reasoning or just a slow way to reformat text.

**Responsibilities:**
- Design and iterate on prompts for the four LLM-backed agents:
  - `extraction.py` - pulling structured clause data out of unstructured
    contract prose
  - `optimization.py` - recommending keep/cancel/renegotiate with a
    business rationale and negotiation talking points (never numbers - those
    come from deterministic math, see Jessy/Seth)
  - `critic.py` - the reflection pass that checks the other agents' claims
    against the underlying data before they reach the UI
  - `narrator.py` - the executive summary synthesis
- Own `app/tools/llm_client.py`: the three-mode backend (Ollama / Anthropic /
  offline), structured-output schema validation with retry, and making sure
  a bad or slow local model degrades gracefully instead of breaking the app.
- Own `app/tools/vector_store.py`: chunking strategy, embeddings, and
  retrieval quality for both the extraction agent's grounding and the `/ask`
  endpoint.
- Responsible for catching prompt injection risk from contract text (an
  agent reading a "contract" should never follow instructions embedded in
  it), and for making sure the real LLM path is a genuine improvement over
  the offline fallback, not just slower.

**Key files:** `app/agents/extraction.py`, `optimization.py`, `critic.py`,
`narrator.py`, `app/tools/llm_client.py`, `vector_store.py`.

**First thing to check:** install Ollama (`docs/setup.md`), pull `qwen3:8b`
and `nomic-embed-text`, then run the pipeline once in `ollama` mode and once
offline and compare the extraction/optimization output quality side by side.

### Jessy — Backend & Orchestration

**Scope:** how the eight agents are wired together and exposed to the rest
of the app - the LangGraph pipeline definition, the FastAPI server, and
everything about making a multi-step agent run feel fast and reliable rather
than like a black box you wait on.

**Responsibilities:**
- Own the LangGraph state graph in `app/orchestrator/graph.py`: agent
  execution order, the fan-out/fan-in structure (Discovery → four parallel
  workers → Optimization → Critic → Narrator), and the shared state schema
  in `state.py`.
- Own the FastAPI app (`app/main.py`, `app/views.py`): every route's
  request/response contract, and the Server-Sent-Events stream that powers
  the live pipeline visualization on the frontend - this is the API Ryan's
  pages depend on, so changes here should be coordinated with him.
- Own run persistence (`app/orchestrator/persistence.py`) so a completed
  analysis survives an app restart instead of vanishing.
- Own `app/tools/dataset_tools.py`, the one place allowed to touch the
  SQLite database directly - if the database technology ever changes, this
  is the only file that should need to.
- Responsible for pipeline reliability (no dropped SSE events, no race
  conditions between concurrent runs) and for keeping API responses stable
  so frontend and backend can be worked on independently.

**Key files:** `app/orchestrator/` (`graph.py`, `state.py`, `events.py`,
`persistence.py`), `app/main.py`, `app/views.py`, `app/tools/dataset_tools.py`,
`app/config.py`.

**First thing to check:** trigger `GET /api/run`, confirm every agent's SSE
event arrives in the right order with no gaps, and confirm
`runtime/last_run.json` round-trips correctly after a server restart.

### Ryan — Frontend, Docs & QA

**Scope:** everything the user actually sees, and everything that proves the
rest of the team's work is correct - the UI, the documentation, and the test
suite. If it's not documented or not tested, it's not really done, and
that's Ryan's standard to hold the project to.

**Responsibilities:**
- Own the design system (`app/static/css/theme.css`) and every page template
  under `app/templates/` - visual consistency, accessibility, and parity
  between the light and dark themes.
- Own the frontend JavaScript (`app/static/js/app.js`): the SSE handling
  that drives the live pipeline visualization, chart rendering, and Alpine.js
  interactivity - all without a Node build step, by design.
- Own the docs (`README.md`, `docs/architecture.md`, `docs/setup.md`) - keep
  them accurate as the other three areas evolve; a doc that describes a
  removed feature or a stale setup step is worse than no doc.
- Own the test suite (`tests/`) and be the one pushing for coverage as new
  agent logic lands - especially for Seth's threshold changes and Jessy's
  API contracts, since those are the easiest things to silently break.
- Responsible for being the last check before something ships: click through
  the actual running app, not just the code, before calling a change done.

**Key files:** `app/templates/`, `app/static/`, `docs/`, `tests/`, `README.md`.

**First thing to check:** click through all 6 pages in both light and dark
theme, then run `pytest tests/` and make sure it's green.

## Tests

```bash
pytest tests/
```
