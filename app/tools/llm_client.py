"""
Purpose: Unified LLM access for all agents with three interchangeable backends -
local Ollama (default), Anthropic Claude (optional cloud fallback), and a
deterministic offline mode so the app always runs even with nothing installed.

Agents call chat_structured()/plain_complete()/embed_texts() and do not need to
know which backend is active. chat_structured() returns None on failure (invalid
JSON after retry, backend unreachable) so callers can fall back to deterministic
logic - the app must never hard-crash because a local model isn't running.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from typing import TypeVar

from pydantic import BaseModel

from app import config

T = TypeVar("T", bound=BaseModel)

EMBED_DIM = 256


@lru_cache(maxsize=1)
def get_mode() -> str:
    """Resolve the active backend once per process: ollama | anthropic | offline."""
    if config.LLM_MODE in ("ollama", "anthropic", "offline"):
        return config.LLM_MODE

    if _probe_ollama():
        return "ollama"
    if config.ANTHROPIC_API_KEY:
        return "anthropic"
    return "offline"


def _probe_ollama() -> bool:
    try:
        import ollama

        client = ollama.Client(host=config.OLLAMA_HOST)
        client.list()
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Structured (schema-validated JSON) completion
# ---------------------------------------------------------------------------


def chat_structured(system: str, user: str, schema: type[T]) -> T | None:
    """Ask the active LLM backend for output matching `schema`. Returns None on
    any failure so the caller can fall back to deterministic logic."""
    mode = get_mode()
    if mode == "ollama":
        return _ollama_structured(system, user, schema)
    if mode == "anthropic":
        return _anthropic_structured(system, user, schema)
    return None


def _ollama_structured(system: str, user: str, schema: type[T]) -> T | None:
    try:
        import ollama

        client = ollama.Client(host=config.OLLAMA_HOST)
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        response = client.chat(model=config.OLLAMA_CHAT_MODEL, messages=messages,
                                format=schema.model_json_schema())
        return schema.model_validate_json(response["message"]["content"])
    except Exception:
        try:
            # one retry nudging the model to correct its own JSON
            import ollama

            client = ollama.Client(host=config.OLLAMA_HOST)
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
                {"role": "user", "content": "Your previous response was not valid JSON for the required schema. Reply with valid JSON only."},
            ]
            response = client.chat(model=config.OLLAMA_CHAT_MODEL, messages=messages,
                                    format=schema.model_json_schema())
            return schema.model_validate_json(response["message"]["content"])
        except Exception:
            return None


def _anthropic_structured(system: str, user: str, schema: type[T]) -> T | None:
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        tool_name = "emit_result"
        response = client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": user}],
            tools=[{
                "name": tool_name,
                "description": f"Emit the result matching the {schema.__name__} schema.",
                "input_schema": schema.model_json_schema(),
            }],
            tool_choice={"type": "tool", "name": tool_name},
        )
        for block in response.content:
            if block.type == "tool_use" and block.name == tool_name:
                return schema.model_validate(block.input)
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Free-text completion (executive narrative, ask-mode answers)
# ---------------------------------------------------------------------------


def plain_complete(system: str, user: str) -> str | None:
    mode = get_mode()
    if mode == "ollama":
        try:
            import ollama

            client = ollama.Client(host=config.OLLAMA_HOST)
            messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
            response = client.chat(model=config.OLLAMA_CHAT_MODEL, messages=messages)
            return response["message"]["content"]
        except Exception:
            return None
    if mode == "anthropic":
        try:
            import anthropic

            client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
            response = client.messages.create(
                model=config.ANTHROPIC_MODEL, max_tokens=1024, system=system,
                messages=[{"role": "user", "content": user}],
            )
            return "".join(b.text for b in response.content if b.type == "text")
        except Exception:
            return None
    return None


# ---------------------------------------------------------------------------
# Embeddings (real via Ollama; deterministic hashed fallback offline)
# ---------------------------------------------------------------------------


def embed_texts(texts: list[str]) -> list[list[float]]:
    if get_mode() == "ollama":
        try:
            import ollama

            client = ollama.Client(host=config.OLLAMA_HOST)
            response = client.embed(model=config.OLLAMA_EMBED_MODEL, input=texts)
            return [list(vec) for vec in response["embeddings"]]
        except Exception:
            pass
    return [_hashed_embedding(t) for t in texts]


def _hashed_embedding(text: str, dim: int = EMBED_DIM) -> list[float]:
    """Deterministic bag-of-words hashed embedding used when no real embedding
    model is available. Not semantically rich, but stable and dependency-free,
    so vector search still works end-to-end in offline mode."""
    vector = [0.0] * dim
    tokens = [t for t in text.lower().replace("\n", " ").split(" ") if t]
    for token in tokens:
        digest = hashlib.md5(token.encode("utf-8")).hexdigest()
        index = int(digest[:8], 16) % dim
        sign = 1.0 if int(digest[8], 16) % 2 == 0 else -1.0
        vector[index] += sign

    norm = sum(v * v for v in vector) ** 0.5
    if norm > 0:
        vector = [v / norm for v in vector]
    return vector
