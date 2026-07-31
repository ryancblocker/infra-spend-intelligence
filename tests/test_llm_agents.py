"""
Tests for the LLM-backed agents and their supporting tools.

Everything here runs against a fake LLM backend injected at the llm_client
boundary, so the suite is fast, deterministic, and never requires Ollama.
"""

from __future__ import annotations

from app.tools import llm_client


# ---------------------------------------------------------------------------
# Think-tag stripping (qwen3 emits <think> reasoning blocks)
# ---------------------------------------------------------------------------


def test_strip_think_removes_closed_block():
    raw = "<think>internal reasoning here</think>The answer is 42."
    assert llm_client.strip_think(raw) == "The answer is 42."


def test_strip_think_removes_multiline_block():
    raw = "<think>\nline one\nline two\n</think>\nFinal answer."
    assert llm_client.strip_think(raw) == "Final answer."


def test_strip_think_handles_unclosed_block():
    raw = "Partial answer.<think>truncated reasoning that never closes"
    assert llm_client.strip_think(raw) == "Partial answer."


def test_strip_think_passes_through_clean_text():
    assert llm_client.strip_think("  Just text.  ") == "Just text."
