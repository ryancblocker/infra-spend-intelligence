"""
Purpose: Refresh a subset of the benchmark_rates table from real public
pricing pages, so pipeline runs reflect roughly current market pricing
instead of a number someone typed into app/data/seed/benchmark_rates.csv
once and never revisited (see docs/architecture.md#sources for the two
pages that seeded it originally).

Scope is deliberately narrow and was chosen by actually checking what each
candidate source contains, not by assuming a plausible-looking page would
work:

- Colocation ($/rack-unit, $/kW) keeps the original Brightlio source - it is
  itself sourced from CBRE's semi-annual data center trends report, about as
  real as free public colo pricing gets.
- Telecom circuit rates (DIA/MPLS/point-to-point, $/Mbps) are dropped
  entirely. The page docs/architecture.md previously cited for these
  (Socium IT) turned out to be aggregate per-employee spend content
  marketing, not per-Mbps circuit rates - scraping it would never produce a
  value for these fields. There is no good free public per-Mbps index;
  enterprise circuit pricing is quote-based. These categories stay static.
- Mobile line tiers and four license categories (Identity & Access,
  Productivity Suite, Security - Endpoint, Observability, AI/LLM Assistant)
  are new: real carrier/vendor pricing pages, verified to return actual
  dollar figures in their server-rendered HTML (no JS execution here - a
  page that only renders prices client-side, like Salesforce's or OpenAI's,
  was tried and dropped for exactly that reason).
- DevOps Platform, CRM/ERP, and HR/Finance license categories still have no
  verified working source and stay static rather than guess one.

Each source page maps to the ONE category it actually speaks to and gets its
own narrow LLM extraction call (see extraction.py's _partial_schema for the
same "narrow schema per call" reasoning) - a small local model handles one
targeted question far more reliably than one page's worth of noise plus
seven categories at once, and one page's fetch or extraction failure can
never affect any other category.

Runs once per BENCHMARK_REFRESH_TTL_HOURS (default 24h), on app startup
only. Any failure at any stage - fetch, parse, LLM extraction - leaves that
category's row exactly as it was; there is no path where a scrape failure
degrades a pipeline run. Offline mode skips outright: there is no LLM to
read prose with, so a stale-but-correct static rate beats a regex guess.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from html.parser import HTMLParser

from pydantic import BaseModel, create_model

from app import config
from app.orchestrator.events import emit, emit_done
from app.tools import dataset_tools
from app.tools.llm_client import (
    UNTRUSTED_PREAMBLE,
    chat_structured,
    get_mode,
    scan_for_injection,
    wrap_untrusted,
)

# One source page per category. Field names are the schema-safe (underscored)
# form; FIELD_TO_CATEGORY below maps back to the actual benchmark_rates.csv
# category, which may contain spaces/hyphens/slashes that aren't valid Python
# identifiers.
SOURCES: dict[str, str] = {
    "https://brightlio.com/colocation-pricing/": "colo_power_kw",
    "https://www.verizon.com/business/answers/monthly-costs-for-business-mobile-plans/": "mobile_tiers",
    "https://www.okta.com/pricing/": "license_identity_access",
    "https://workspace.google.com/pricing": "license_productivity_suite",
    "https://www.crowdstrike.com/en-us/pricing/": "license_security_endpoint",
    "https://www.datadoghq.com/pricing/": "license_observability",
    "https://www.anthropic.com/pricing": "license_ai_llm_assistant",
}

# Short, human-readable labels for progress events - falls back to the raw
# URL for any source added here without one.
SOURCE_LABELS: dict[str, str] = {
    "https://brightlio.com/colocation-pricing/": "Colocation (Brightlio)",
    "https://www.verizon.com/business/answers/monthly-costs-for-business-mobile-plans/": "Mobile plans (Verizon)",
    "https://www.okta.com/pricing/": "Identity & Access (Okta)",
    "https://workspace.google.com/pricing": "Productivity Suite (Google Workspace)",
    "https://www.crowdstrike.com/en-us/pricing/": "Security - Endpoint (CrowdStrike)",
    "https://www.datadoghq.com/pricing/": "Observability (Datadog)",
    "https://www.anthropic.com/pricing": "AI / LLM Assistant (Anthropic)",
}

# "mobile_tiers" fans out to three schema fields from one page; every other
# source key above names its schema field directly.
_FIELD_GROUPS: dict[str, tuple[str, ...]] = {
    "colo_power_kw": ("colo_rack_unit", "colo_power_kw"),
    "mobile_tiers": ("mobile_basic", "mobile_standard", "mobile_premium"),
    "license_identity_access": ("license_identity_access",),
    "license_productivity_suite": ("license_productivity_suite",),
    "license_security_endpoint": ("license_security_endpoint",),
    "license_observability": ("license_observability",),
    "license_ai_llm_assistant": ("license_ai_llm_assistant",),
}

FIELD_TO_CATEGORY = {
    "colo_rack_unit": "colo_rack_unit",
    "colo_power_kw": "colo_power_kw",
    "mobile_basic": "mobile_Basic",
    "mobile_standard": "mobile_Standard",
    "mobile_premium": "mobile_Premium",
    "license_identity_access": "license_Identity & Access",
    "license_productivity_suite": "license_Productivity Suite",
    "license_security_endpoint": "license_Security - Endpoint",
    "license_observability": "license_Observability",
    "license_ai_llm_assistant": "license_AI / LLM Assistant",
}

# What each field means, so the LLM extracts the right number rather than the
# first dollar figure on the page (a pricing page has many: per-GB overage,
# add-on fees, enterprise "contact us" placeholders).
_FIELD_DESCRIPTIONS = {
    "colo_rack_unit": "typical colocation price in USD per rack unit (U) per month",
    "colo_power_kw": "typical colocation price in USD per kW of power per month",
    "mobile_basic": "USD/month for the entry-level or basic business mobile line plan",
    "mobile_standard": "USD/month for the mid-tier/standard business mobile line plan",
    "mobile_premium": "USD/month for the top-tier/premium business mobile line plan",
    "license_identity_access": "USD per user per month for the identity & access management (SSO/MFA) product's mid-tier plan",
    "license_productivity_suite": "USD per user per month for the productivity/office suite's mid-tier plan",
    "license_security_endpoint": "USD per endpoint/device per month for the endpoint security (EDR) product's mid-tier plan",
    "license_observability": "USD per host (or per user, whichever the page prices by) per month for the observability/monitoring platform's mid-tier plan",
    "license_ai_llm_assistant": "USD per user per month for the AI/LLM assistant subscription's mid-tier paid plan",
}

FETCH_TIMEOUT_SECONDS = 15
# A pricing page's plan cards are typically well within the first screenfuls
# of content; bounding this keeps each LLM prompt small; per extraction.py's
# _partial_schema rationale, that is what a small local model reads reliably.
MAX_PAGE_CHARS = 8000

ALL_FIELDS: tuple[str, ...] = tuple(FIELD_TO_CATEGORY)

EXTRACTION_SYSTEM_PROMPT_TEMPLATE = (
    "You are a market-pricing analyst. Read the pricing page text provided and extract ONLY "
    "the specific rate(s) described below, in the units given. If the page does not clearly "
    "state a value for a field, leave it null - never estimate, infer, or use an unrelated "
    "figure (overage fees, enterprise 'contact us' placeholders, and one-time setup costs are "
    "not this rate).\n\n{field_lines}"
    "\n\n" + UNTRUSTED_PREAMBLE
)


def _schema_for(fields: tuple[str, ...]) -> type[BaseModel]:
    return create_model(
        "ScrapedRates",
        **{field: (float | None, None) for field in fields},
    )


class _TextExtractor(HTMLParser):
    """Strips tags down to visible text. Good enough for a pricing page's
    plan cards - this isn't a general-purpose renderer, and it never executes
    JavaScript, so a page whose prices only render client-side yields no
    numbers here (verified case by case before a URL was added to SOURCES,
    see module docstring)."""

    _SKIP_TAGS = ("script", "style", "nav", "footer", "header")

    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data.strip():
            self._chunks.append(data.strip())

    def text(self) -> str:
        return "\n".join(self._chunks)


def _fetch_text(url: str) -> str | None:
    try:
        import httpx

        response = httpx.get(
            url, timeout=FETCH_TIMEOUT_SECONDS, follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; PACTBenchmarkBot/1.0)"},
        )
        response.raise_for_status()
        parser = _TextExtractor()
        parser.feed(response.text)
        text = parser.text()
        return text[:MAX_PAGE_CHARS] if text else None
    except Exception:
        return None


def _load_cache() -> dict | None:
    try:
        return json.loads(config.BENCHMARK_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def last_refresh() -> dict | None:
    """What the most recent successful scrape found, for display - the page
    route reads this rather than reaching into the cache file directly."""
    return _load_cache()


def _save_cache(result: dict) -> None:
    try:
        config.ensure_runtime_dirs()
        config.BENCHMARK_CACHE_PATH.write_text(json.dumps(result), encoding="utf-8")
    except Exception:
        pass


def _is_fresh(cache: dict) -> bool:
    try:
        fetched_at = datetime.fromisoformat(cache["fetched_at"])
    except Exception:
        return False
    age_hours = (datetime.now(timezone.utc) - fetched_at).total_seconds() / 3600
    return age_hours < config.BENCHMARK_REFRESH_TTL_HOURS


def _extract_from_page(url: str, group: str, text: str) -> tuple[dict[str, float], list[str]]:
    """One narrowly-scoped LLM call per source page. Returns the rates it
    could confidently read (possibly empty) and any injection markers found
    in the page text."""
    fields = _FIELD_GROUPS[group]
    flags = scan_for_injection(text)

    field_lines = "\n".join(f"- {f}: {_FIELD_DESCRIPTIONS[f]}" for f in fields)
    system = EXTRACTION_SYSTEM_PROMPT_TEMPLATE.format(field_lines=field_lines)
    reply = chat_structured(
        system=system, user=wrap_untrusted(f"[source: {url}]\n{text}"),
        schema=_schema_for(fields), agent="pricing_scraper",
    )
    if reply is None:
        return {}, flags

    rates = {
        FIELD_TO_CATEGORY[field]: value
        for field, value in reply.model_dump().items()
        if value is not None and value > 0
    }
    return rates, flags


def apply_cached_only() -> dict:
    """Re-apply whatever the cache already holds to the benchmark_rates
    table, without any network or LLM call. This is what app startup calls:
    a DB rebuild (runtime/pact.db deleted) resets every category back to the
    static CSV, and this is what lets a restart re-assert already-scraped
    numbers immediately, with none of the latency or load a real scrape
    carries. Use refresh_benchmarks() to actually go fetch new numbers."""
    cache = _load_cache()
    if not cache:
        return {"status": "skipped", "reason": "no cached scrape yet"}
    dataset_tools.update_benchmark_rates(cache.get("rates", {}))
    return {"status": "cached", **cache}


def refresh_benchmarks(force: bool = False, event_queue=None) -> dict:
    """Re-scrape and re-extract if the cache is stale (or force=True), then
    apply whatever rates each page's LLM call could confidently read to the
    benchmark_rates table - one source at a time, applying and emitting
    progress for each as it finishes rather than batching everything to the
    end. Always returns a status dict; never raises - any failure just
    leaves the affected category's row as it was.

    A fresh cache still gets re-applied to the table (not just skipped): see
    apply_cached_only()'s docstring for why.

    event_queue, if given, receives one AgentEvent per source (started, then
    completed/error) plus a DONE_SENTINEL at the end - the same
    app.orchestrator.events contract app.orchestrator.graph.run_pipeline
    uses, so /api/refresh-benchmarks can stream it with the exact SSE
    plumbing /api/run already has."""
    try:
        cache = _load_cache()
        if not force and cache and _is_fresh(cache):
            result = apply_cached_only()
            detail = ", ".join(f"{cat}=${v:g}" for cat, v in cache.get("rates", {}).items())
            emit(event_queue, "Cached rates", "completed", detail or "nothing cached yet")
            return result

        if get_mode() == "offline":
            return {"status": "skipped", "reason": "offline mode - no LLM available to read prose with"}

        rates: dict[str, float] = {}
        injection_flags: list[str] = []
        sources_used: list[str] = []

        for url, group in SOURCES.items():
            label = SOURCE_LABELS.get(url, url)
            emit(event_queue, label, "started")

            text = _fetch_text(url)
            if not text:
                emit(event_queue, label, "error", "page unreachable")
                continue

            page_rates, page_flags = _extract_from_page(url, group, text)
            injection_flags.extend(page_flags)
            if page_rates:
                # Applied immediately, not batched to the end - the whole
                # point of one-at-a-time is that a rate is live the moment
                # its own source finishes, not after the slowest one does.
                dataset_tools.update_benchmark_rates(page_rates)
                rates.update(page_rates)
                sources_used.append(url)
                detail = ", ".join(f"{cat}=${v:g}" for cat, v in page_rates.items())
                emit(event_queue, label, "completed", detail)
            else:
                emit(event_queue, label, "completed", "no rate stated on this page")

        if not rates:
            return {"status": "skipped", "reason": "no rate was confidently read from any source page"}

        result = {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "rates": rates,
            "sources_used": sources_used,
            "injection_flags": sorted(set(injection_flags)),
        }
        _save_cache(result)
        return {"status": "updated", **result}
    finally:
        emit_done(event_queue)
