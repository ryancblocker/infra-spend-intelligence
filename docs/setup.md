# Setup

## 1. Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 2. (Optional but recommended) Local LLM via Ollama

PACT runs fully functional without this step - it falls back to deterministic
logic automatically. Installing Ollama unlocks the LLM-powered agents
(contract clause extraction, negotiation strategy, executive narrative, and
the `/ask` chat endpoint).

```bash
# macOS
brew install ollama
ollama serve &                      # or open the Ollama app

# pull the default chat + embedding models
ollama pull qwen3:8b
ollama pull nomic-embed-text
```

To use a different model (e.g. a smaller one on constrained hardware, or
`llama3.1:8b`), set:

```bash
export PACT_OLLAMA_MODEL=llama3.1:8b
```

### Cloud fallback instead of local

If you'd rather use Anthropic's API instead of a local model:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export PACT_LLM_MODE=anthropic      # optional: skip Ollama auto-detection
```

## 3. Seed the database

The app auto-seeds `runtime/pact.db` and the vector index on first startup if
they don't exist. To do it explicitly (e.g. after editing the CSV fixtures
under `app/data/seed/`):

```bash
python -m app.data.seed_db --check
```

To regenerate the synthetic dataset itself from scratch:

```bash
python app/data/generate_seed_data.py
python -m app.data.seed_db --check
```

## 4. Run

```bash
uvicorn app.main:app --reload --port 8420
```

Open http://localhost:8420. Click **Run Analysis** on the Overview page to
execute the agent pipeline - progress streams live via Server-Sent Events.

## 5. Demo mode (recording a walkthrough)

Flip the **Demo mode** toggle above the Run Analysis button on the Overview
page before clicking it. This runs the real eight-agent pipeline against the
seeded portfolio through the app's existing offline deterministic path - no
Ollama, no Anthropic, no network calls at all, regardless of `PACT_LLM_MODE`
- and paces the progress events (~0.5-1.3s per node) so the pipeline
visualization is watchable instead of finishing before a recording can even
start. It's the fastest way to see (or capture) the full pipeline working,
and the only way that doesn't depend on a real run finishing first.

Demo runs are labeled "demo" in the executive summary badge and run history
so they're never mistaken for a real analysis.

## 6. Tests

```bash
pytest tests/
```
