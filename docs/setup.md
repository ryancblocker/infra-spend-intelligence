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
ollama pull qwen3:1.7b
ollama pull nomic-embed-text
```

`qwen3:1.7b` (not a larger sibling) is the app's actual default
(`app/config.py`), sized deliberately for an 8 GB unified-memory Mac -
`qwen3:8b` leaves too little headroom for the OS and has hung machines
outright when the pipeline runs several LLM calls back to back. Only pull
`qwen3:8b` (and set `PACT_OLLAMA_MODEL=qwen3:8b`) if your machine has real
memory headroom beyond 8 GB.

**Expect it to be slow, and that's normal.** Against `qwen3:1.7b` on a
constrained machine, individual LLM calls run ~15-95s each, and a full
pipeline run (up to 15 optimization calls plus extraction/critic/narrator)
takes several minutes - `app/config.py`'s `PIPELINE_TIMEOUT_SECONDS` gives it
a 10-minute ceiling before it's actually treated as hung. A UI showing
progress for minutes at a time is the model thinking, not something broken.

To use a different local model, set:

```bash
export PACT_OLLAMA_MODEL=llama3.1:8b
```

### Cloud fallback instead of local

If you'd rather use Anthropic's API instead of a local model - notably
faster per call (seconds, not tens of seconds) since it runs on Anthropic's
servers instead of your machine, at the cost of a per-call API charge and no
longer being fully local/offline for that run:

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

## 5. Tests

```bash
pytest tests/
```
