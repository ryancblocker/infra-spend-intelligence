"""
Purpose: Extract structured clause data (renewal terms, fees, SLA, liability cap,
MFN/price-protection presence) from unstructured contract prose.

This agent runs a bounded investigation loop rather than a single prompt. It
retrieves clause chunks, extracts what it can, assesses which required fields
are still missing, and issues its own targeted follow-up queries for just those
gaps - up to MAX_EXTRACTION_ITERS.

The loop's control flow is deterministic and its termination is computed in
Python; only the reasoning inside each step is the model's. That split is what
makes genuine autonomy safe on a small local model: qwen3:8b answers "what does
this clause say?" reliably but "am I finished?" badly, so it is only ever asked
the former.

The offline fallback (regex tuned to the generator's phrasing) is retained both
as the degraded path and as the eval harness's baseline.
"""

from __future__ import annotations

import hashlib
import json
import re

from pydantic import BaseModel, create_model

from app import config
from app.agents.schemas import ClauseCitation, ContractTerms, ExtractedContract
from app.tools import vector_store
from app.tools.llm_client import (
    UNTRUSTED_PREAMBLE,
    chat_structured,
    get_mode,
    scan_for_injection,
    wrap_untrusted,
)

EXTRACTION_SYSTEM_PROMPT = (
    "You are a contract analyst. Extract structured terms from the commercial contract text "
    "provided. Only use information present in the text - do not invent values. If a field is "
    "not present, leave it empty/false/null as appropriate. Set risk_level to High if the "
    "contract auto-renews AND has a notice period of 90+ days AND a termination fee of 15%+; "
    "Medium if two of those three conditions hold; otherwise Low. risk_rationale should be one "
    "sentence citing the specific terms that drove the risk level."
    "\n\n" + UNTRUSTED_PREAMBLE
)

# Each required field carries the retrieval query the agent uses to go looking
# for it. Iteration 1 runs all of them; later iterations run only the gaps.
FIELD_QUERIES = {
    "renewal_date": "term expiration end date renewal",
    "auto_renew": "automatically renew successive terms",
    "notice_period_days": "written notice of non-renewal days prior",
    "termination_fee_pct": "early termination fee penalty for convenience",
    "annual_escalator_pct": "annual escalator price increase uplift anniversary",
    "minimum_commitment": "minimum commitment volume covered services",
    "sla_summary": "service level credits availability uptime",
    "liability_cap_summary": "limitation of liability aggregate cap",
    "has_mfn_clause": "most favored pricing customer",
    "has_price_protection_clause": "price protection unit pricing shall not increase",
}

# A False boolean is indistinguishable from "I didn't find it" on a small model,
# so these get one more look before being reported as genuinely absent.
BOOLEAN_FIELDS = {"auto_renew", "has_mfn_clause", "has_price_protection_clause"}


def run() -> list[ExtractedContract]:
    results = []
    for path in sorted(config.CONTRACT_DOCS_DIR.glob("*.txt")):
        results.append(extract_one(path.stem, path.read_text(encoding="utf-8")))
    return results


# ---------------------------------------------------------------------------
# Gap assessment - deterministic, no LLM call, so it cannot itself fail
# ---------------------------------------------------------------------------


def _is_resolved(field: str, value) -> bool:
    if field in BOOLEAN_FIELDS:
        return value is True
    return value is not None and value != ""


def unresolved(terms: BaseModel) -> list[str]:
    """Which required fields still have no value. This is the loop's termination
    condition, and it is pure Python by design."""
    data = terms.model_dump()
    return [f for f in FIELD_QUERIES if not _is_resolved(f, data.get(f))]


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------


def _retrieve(contract_id: str, queries: list[str]) -> list[dict]:
    """Run each query and return the union of hits, deduplicated by chunk and
    keeping the best distance for each."""
    best: dict[int, dict] = {}
    for query in queries:
        for hit in vector_store.search(query, config.RETRIEVAL_K, contract_id=contract_id):
            index = hit.get("chunk_index", 0)
            if index not in best or hit["distance"] < best[index]["distance"]:
                best[index] = hit
    return sorted(best.values(), key=lambda h: h["distance"])


def _partial_schema(fields: list[str]) -> type[BaseModel]:
    """Narrow ContractTerms to just the unresolved fields. A smaller schema means
    a smaller output, which a small model gets right more often and faster."""
    definitions = {}
    for name in fields:
        info = ContractTerms.model_fields[name]
        definitions[name] = (info.annotation, info.default)
    return create_model("PartialContractTerms", **definitions)


def _cite(field: str, value, chunks: list[dict]) -> ClauseCitation | None:
    """Attach the chunk an extracted value actually came from. Prefers the chunk
    whose text literally contains the value; falls back to the best-ranked chunk
    for booleans and paraphrased summaries."""
    if not chunks:
        return None
    candidates = []
    if value is not None and not isinstance(value, bool):
        text = str(value)
        candidates.append(text)
        if isinstance(value, float) and value.is_integer():
            candidates.append(str(int(value)))
    for chunk in chunks:
        if any(candidate and candidate in chunk["text"] for candidate in candidates):
            return _citation_from(chunk)
    return _citation_from(chunks[0])


def _citation_from(chunk: dict) -> ClauseCitation:
    return ClauseCitation(
        contract_id=chunk.get("contract_id", ""),
        chunk_index=chunk.get("chunk_index", 0),
        heading=chunk.get("heading", ""),
        excerpt=chunk["text"][:240].strip(),
    )


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------


def extract_one(contract_id: str, text: str) -> ExtractedContract:
    cached = _cache_get(contract_id, text)
    if cached is not None:
        return cached

    if get_mode() == "offline":
        record = _with_offline_citations(contract_id, text)
    else:
        record = _extract_agentic(contract_id, text)

    _cache_put(contract_id, text, record)
    return record


def _extract_agentic(contract_id: str, text: str) -> ExtractedContract:
    accumulated: dict = {}
    sources: dict[str, ClauseCitation] = {}
    injection_flags: list[str] = []
    queries_issued: list[str] = []
    iterations = 0
    gaps = list(FIELD_QUERIES)

    for iteration in range(1, config.MAX_EXTRACTION_ITERS + 1):
        iterations = iteration
        queries = ([FIELD_QUERIES[f] for f in FIELD_QUERIES] if iteration == 1
                   else [FIELD_QUERIES[f] for f in gaps])
        queries_issued.extend(queries)

        chunks = _retrieve(contract_id, queries)
        if not chunks:
            break

        for chunk in chunks:
            injection_flags.extend(scan_for_injection(chunk["text"]))

        context = wrap_untrusted(
            "\n\n".join(f"[{c['heading']}]\n{c['text']}" for c in chunks)
        )
        schema = ContractTerms if iteration == 1 else _partial_schema(gaps)
        reply = chat_structured(system=EXTRACTION_SYSTEM_PROMPT, user=context,
                                schema=schema, agent="extraction")

        if reply is not None:
            for field, value in reply.model_dump().items():
                already = _is_resolved(field, accumulated.get(field))
                if already or not _is_resolved(field, value):
                    continue
                accumulated[field] = value
                if field in FIELD_QUERIES:
                    citation = _cite(field, value, chunks)
                    if citation is not None:
                        sources[field] = citation
            # non-required fields (vendor, category, risk_*) carry through too
            for field, value in reply.model_dump().items():
                if field not in accumulated and _is_resolved(field, value):
                    accumulated[field] = value

        gaps = [f for f in FIELD_QUERIES if not _is_resolved(f, accumulated.get(f))]
        if not gaps:
            break

    if not accumulated:
        # the model never produced anything usable - degrade, don't guess
        record = _with_offline_citations(contract_id, text)
        record.extraction_iterations = iterations or 1
        record.injection_flags = sorted(set(injection_flags))
        record.retrieval_queries = queries_issued
        return record

    terms = ContractTerms(**{k: v for k, v in accumulated.items()
                             if k in ContractTerms.model_fields})
    return ExtractedContract(
        contract_id=contract_id,
        **terms.model_dump(),
        extraction_source=get_mode(),
        field_sources=sources,
        extraction_iterations=iterations,
        unresolved_fields=gaps,
        injection_flags=sorted(set(injection_flags)),
        retrieval_queries=queries_issued,
    )


def _with_offline_citations(contract_id: str, text: str) -> ExtractedContract:
    """Regex extraction plus citations located directly in the document, so a
    trace exists in offline mode too."""
    record = _extract_offline(contract_id, text)
    chunks = [dict(c, contract_id=contract_id) for c in vector_store.chunk_document(text)]
    data = record.model_dump()
    for field in FIELD_QUERIES:
        value = data.get(field)
        if not _is_resolved(field, value):
            continue
        citation = _cite(field, value, chunks)
        if citation is not None:
            record.field_sources[field] = citation
    record.unresolved_fields = [f for f in FIELD_QUERIES if not _is_resolved(f, data.get(f))]
    record.injection_flags = sorted(set(scan_for_injection(text)))
    return record


# ---------------------------------------------------------------------------
# Cache - keyed so a changed document or model invalidates cleanly
# ---------------------------------------------------------------------------


def cache_key(contract_id: str, text: str) -> str:
    raw = f"{contract_id}|{text}|{config.OLLAMA_CHAT_MODEL}|{get_mode()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_cache() -> dict:
    try:
        return json.loads(config.EXTRACTION_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_cache(cache: dict) -> None:
    try:
        config.ensure_runtime_dirs()
        config.EXTRACTION_CACHE_PATH.write_text(json.dumps(cache), encoding="utf-8")
    except Exception:
        pass


def _cache_get(contract_id: str, text: str) -> ExtractedContract | None:
    if not config.EXTRACTION_CACHE_ENABLED:
        return None
    payload = load_cache().get(cache_key(contract_id, text))
    if payload is None:
        return None
    try:
        return ExtractedContract.model_validate(payload)
    except Exception:
        return None


def _cache_put(contract_id: str, text: str, record: ExtractedContract) -> None:
    if not config.EXTRACTION_CACHE_ENABLED:
        return
    cache = load_cache()
    cache[cache_key(contract_id, text)] = record.model_dump(mode="json")
    save_cache(cache)


def _extract_offline(contract_id: str, text: str) -> ExtractedContract:
    vendor = _search(text, r"VENDOR:\s*(.+)")
    category = _search(text, r"CATEGORY:\s*(.+)")
    end_date = _search(text, r"continues through (\d{4}-\d{2}-\d{2})")
    auto_renew = "automatically renew" in text.lower()
    notice_match = re.search(r"(?:non-renewal|expiration)[^.]*?at least (\d+) days", text, re.IGNORECASE)
    notice_days = int(notice_match.group(1)) if notice_match else None
    fee_match = re.search(r"termination fee equal to (\d+(?:\.\d+)?)%", text, re.IGNORECASE)
    termination_fee_pct = float(fee_match.group(1)) if fee_match else None
    esc_match = re.search(r"Annual Escalator of (\d+(?:\.\d+)?)%", text, re.IGNORECASE)
    escalator_pct = float(esc_match.group(1)) if esc_match else None
    minimum_commitment = _search(text, r"covering (.+?)\.\s")
    sla_summary = _search(text, r"Service Level Credits:\s*(.+)")
    liability_summary = _search(text, r"Limitation of Liability:\s*(.+)")
    has_mfn = "most favored pricing" in text.lower()
    has_price_protection = "price protection" in text.lower()

    risk_level, risk_rationale = _offline_risk(auto_renew, notice_days, termination_fee_pct, escalator_pct)

    return ExtractedContract(
        contract_id=contract_id,
        vendor=vendor,
        category=category,
        auto_renew=auto_renew,
        renewal_date=end_date,
        notice_period_days=notice_days,
        termination_fee_pct=termination_fee_pct,
        annual_escalator_pct=escalator_pct,
        minimum_commitment=minimum_commitment,
        sla_summary=sla_summary,
        liability_cap_summary=liability_summary,
        has_mfn_clause=has_mfn,
        has_price_protection_clause=has_price_protection,
        risk_level=risk_level,
        risk_rationale=risk_rationale,
        extraction_source="offline",
    )


def _search(text: str, pattern: str) -> str:
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _offline_risk(auto_renew: bool, notice_days: int | None, fee_pct: float | None,
                   esc_pct: float | None) -> tuple[str, str]:
    conditions = []
    if auto_renew:
        conditions.append("auto-renews")
    if notice_days and notice_days >= 90:
        conditions.append(f"{notice_days}-day notice period")
    if fee_pct and fee_pct >= 15:
        conditions.append(f"{fee_pct:.0f}% termination fee")

    if len(conditions) >= 3:
        level = "High"
    elif len(conditions) == 2:
        level = "Medium"
    else:
        level = "Low"

    rationale = f"Driven by: {', '.join(conditions)}." if conditions else "No high-risk terms detected."
    return level, rationale
