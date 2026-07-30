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

## 5. Tests

```bash
pytest tests/
```
