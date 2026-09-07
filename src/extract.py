"""Generic, grounded fact extraction (text-first). No document-specific rules.

One LLM call per page/section — never whole-PDF prompts. Every returned fact
carries its evidence quote; persistence (Task 5) stores fact + evidence rows
so fact → evidence → document/page is always traceable.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
from typing import Any

from src.db import create_evidence, create_fact
from src.llm import LLMError, LLMProvider
from src.normalize import normalize_fact_dict

EXTRACT_SYSTEM = """You extract structured facts from a single document page.
Rules:
- Output JSON only: {"facts": [ ... ]}. No prose.
- Each fact: subject (who/what), predicate (snake_case attribute), value_raw (exact number/text as written, "" if non-numeric), unit_raw, period_raw (e.g. FY24, Q4 FY24, a date, or ""), scope (e.g. consolidated, standalone, services-only, or ""), qualifiers (object, may be {}), claim (one human sentence), confidence (0-1), evidence_quote (verbatim substring from SOURCE, max 400 chars).
- Only facts stated in SOURCE. Never invent values, periods, or quotes.
- Prefer meaningful numerical facts (amounts, counts, %, ratios) and key semantic facts (appointments, resignations, addresses, statuses). Skip headers/footers/toc boilerplate.
- At most 12 facts. If the page has no meaningful facts, return {"facts": []}."""

MAX_SOURCE_CHARS = 6000


def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


def quote_grounded(quote: str, source: str, min_overlap_words: int = 4) -> bool:
    """Fuzzy grounding: quote's start or any long word-run appears in source."""
    q, s = _norm_ws(quote), _norm_ws(source)
    if not q or not s:
        return False
    if q[:60] in s or q[-60:] in s:
        return True
    qw = q.split()
    for i in range(len(qw) - min_overlap_words + 1):
        run = " ".join(qw[i:i + min_overlap_words])
        if len(run) > 15 and run in s:
            return True
    return False


def _coerce_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        facts = payload.get("facts", [])
        return [x for x in facts if isinstance(x, dict)] if isinstance(facts, list) else []
    return []


def validate_fact_dict(raw: dict[str, Any], source_text: str) -> dict[str, Any] | None:
    subject = str(raw.get("subject", "") or "").strip()[:200]
    predicate = str(raw.get("predicate", "") or "").strip()[:200]
    claim = str(raw.get("claim", "") or "").strip()[:500]
    quote = str(raw.get("evidence_quote", "") or "").strip()[:1000]
    if not subject or not predicate or not claim or not quote:
        return None
    try:
        conf = float(raw.get("confidence", 0.5))
    except (TypeError, ValueError):
        conf = 0.5
    conf = max(0.0, min(1.0, conf))
    if not quote_grounded(quote, source_text):
        conf *= 0.6  # ungrounded quote → uncertain, never fabricated certainty
    qual = raw.get("qualifiers", {})
    if not isinstance(qual, dict):
        qual = {}
    return {
        "subject": subject,
        "predicate": predicate,
        "value_raw": str(raw.get("value_raw", "") or "")[:200],
        "unit_raw": str(raw.get("unit_raw", "") or "")[:100],
        "period_raw": str(raw.get("period_raw", "") or "")[:100],
        "scope": str(raw.get("scope", "") or "")[:200],
        "qualifiers": qual,
        "claim": claim,
        "confidence": round(conf, 3),
        "evidence_quote": quote,
    }


def extract_facts_from_text(
    provider: LLMProvider, source_text: str, page: int = 0, max_facts: int = 12
) -> list[dict[str, Any]]:
    """Call LLM once for a page slice; malformed responses → [] (caller marks page)."""
    text = (source_text or "").strip()
    if len(text) < 50:
        return []
    prompt = (
        f"SOURCE (page {page}, truncated to {MAX_SOURCE_CHARS} chars):\n{text[:MAX_SOURCE_CHARS]}"
        f"\n\nReturn at most {max_facts} facts as JSON."
    )
    # NOTE: sha256 (stable) — never builtin hash() (randomized per process).
    text_key = hashlib.sha256(text.encode()).hexdigest()[:16]
    try:
        payload = provider.generate_json(prompt, system=EXTRACT_SYSTEM,
                                         cache_key=f"extract:p{page}:{text_key}")
    except LLMError:
        return []
    out: list[dict[str, Any]] = []
    for raw in _coerce_list(payload)[:max_facts]:
        v = validate_fact_dict(raw, text)
        if v is not None:
            out.append(normalize_fact_dict(v))
    return out


def persist_facts_with_evidence(
    conn: sqlite3.Connection, collection_id: str, document_id: str, page: int,
    fact_dicts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Store facts + one evidence row each. Returns fact rows."""
    rows = []
    for f in fact_dicts:
        row = create_fact(
            conn, collection_id, document_id,
            subject=f["subject"], predicate=f["predicate"], claim=f["claim"],
            value_raw=f.get("value_raw", ""), value_norm=f.get("value_norm"),
            unit_raw=f.get("unit_raw", ""), unit_norm=f.get("unit_norm", ""),
            period_raw=f.get("period_raw", ""), period_norm=f.get("period_norm", ""),
            scope=f.get("scope", ""), qualifiers=f.get("qualifiers", {}),
            confidence=f.get("confidence", 0.5),
        )
        create_evidence(conn, row["id"], document_id, page, f.get("evidence_quote", ""))
        rows.append(row)
    return rows
