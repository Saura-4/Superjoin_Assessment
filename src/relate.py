"""Relationship engine: deterministic checks first, LLM judge only when ambiguous.

Pipeline per pair: context compatibility → normalization/value comparison →
contextual (period granularity/scope) comparison → LLM fallback.
Vocabulary is extensible data (CORROBORATES/CONTRADICTS/RECONCILED/
TEMPORAL_CHANGE/UNRELATED/UNCERTAIN), never hard-coded demo rules.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Optional

from src.db import create_relationship
from src.llm import LLMError, LLMProvider
from src.retrieve import find_candidates

REL_TYPES = {"CORROBORATES", "CONTRADICTS", "RECONCILED", "TEMPORAL_CHANGE", "UNRELATED", "UNCERTAIN"}

REL_TOL = 0.02  # 2% rounding tolerance for cross-document numeric agreement

JUDGE_SYSTEM = """You judge the relationship between two extracted facts.
Return JSON only: {"type": one of CORROBORATES/CONTRADICTS/RECONCILED/TEMPORAL_CHANGE/UNRELATED/UNCERTAIN, "confidence": 0-1, "reason": "1-2 sentences citing periods/scopes/units"}.
Rules: same metric+period+scope with equal values (after units) = CORROBORATES. Same metric+period+scope with different values = CONTRADICTS. Same metric but different period granularity/scope/definitions explaining the gap = RECONCILED (name the dimension). Same metric, different time points, changed value = TEMPORAL_CHANGE, not contradiction. Different metrics = UNRELATED. Unclear = UNCERTAIN."""


def values_equal(v1: Optional[float], v2: Optional[float], tol: float = REL_TOL) -> Optional[bool]:
    if v1 is None or v2 is None:
        return None
    if v1 == 0 and v2 == 0:
        return True
    denom = max(abs(v1), abs(v2), 1e-9)
    return abs(v1 - v2) / denom <= tol


def _quarter_of(period_norm: str) -> Optional[str]:
    p = (period_norm or "")
    return p if p.startswith("Q") and "-FY" in p else None


def _fy_of(period_norm: str) -> Optional[str]:
    p = (period_norm or "")
    if p.startswith("Q") and "-FY" in p:
        return "FY" + p.split("-FY", 1)[1]
    if p.startswith("FY"):
        return p
    return None


def deterministic_decide(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any] | None:
    """Return decision dict or None when genuinely ambiguous (needs LLM)."""
    if a.get("predicate") != b.get("predicate"):
        return None  # predicate semantics need judgment
    pa, pb = a.get("period_norm") or "", b.get("period_norm") or ""
    sa, sb = (a.get("scope") or "").strip().lower(), (b.get("scope") or "").strip().lower()
    ua, ub = a.get("unit_norm") or "", b.get("unit_norm") or ""
    va, vb = a.get("value_norm"), b.get("value_norm")

    # granularity: quarter vs full-year of same FY cannot be directly compared
    qa, qb = _quarter_of(pa), _quarter_of(pb)
    fa, fb = _fy_of(pa), _fy_of(pb)
    if fa and fb and fa == fb and ((qa and not qb) or (qb and not qa)):
        return {"type": "RECONCILED", "confidence": 0.8,
                "reason": f"Different granularity in same {fa}: {pa or '?'} (quarterly) vs {pb or '?'} (full-year); values describe different slices.",
                "dimensions": {"period_granularity": [pa, pb]}}

    if pa and pb and pa != pb:
        # different time points
        if va is not None and vb is not None and ua == ub and ua:
            eq = values_equal(va, vb)
            if eq is True:
                return None  # same value, different periods — ambiguous, ask LLM
            return {"type": "TEMPORAL_CHANGE", "confidence": 0.75,
                    "reason": f"Same metric at different times ({pa} vs {pb}) with different values; change over time, not a contradiction.",
                    "dimensions": {"period": [pa, pb]}}
        return None  # semantic change over time → LLM

    # same (or unknown) period from here
    if va is not None and vb is not None:
        if ua != ub or not ua:
            return None  # incomparable units → LLM
        eq = values_equal(va, vb)
        if eq is True:
            exact = "exactly" if va == vb else "within rounding"
            return {"type": "CORROBORATES", "confidence": 0.9,
                    "reason": f"Same {a.get('predicate')} for {pa or 'same period'} agrees {exact} after unit normalization ({va:,.0f} vs {vb:,.0f} {ua}).",
                    "dimensions": {}}
        # same period, different values
        if sa and sb and sa != sb:
            return {"type": "RECONCILED", "confidence": 0.75,
                    "reason": f"Same period {pa or ''} but different scopes ('{a.get('scope')}' vs '{b.get('scope')}'); scope explains the gap.",
                    "dimensions": {"scope": [a.get("scope"), b.get("scope")]}}
        return {"type": "CONTRADICTS", "confidence": 0.7,
                "reason": f"Same {a.get('predicate')} for {pa or 'same period'} and scope differs numerically beyond rounding ({va:,.2f} vs {vb:,.2f} {ua}).",
                "dimensions": {"value": [va, vb]}}
    return None  # non-numeric → LLM


def llm_judge(provider: LLMProvider, a: dict[str, Any], ev_a: str,
              b: dict[str, Any], ev_b: str) -> dict[str, Any]:
    prompt = ("RELATION JUDGE. Fact A:\n" + json.dumps(_slim(a), indent=1)
              + f"\nEvidence A: {ev_a[:600]}\n\nFact B:\n" + json.dumps(_slim(b), indent=1)
              + f"\nEvidence B: {ev_b[:600]}\n\nReturn JSON.")
    try:
        out = provider.generate_json(prompt, system=JUDGE_SYSTEM,
                                     cache_key=f"judge:{a['id']}:{b['id']}")
    except LLMError:
        return {"type": "UNCERTAIN", "confidence": 0.3, "reason": "LLM unavailable; marked uncertain.", "dimensions": {}}
    if not isinstance(out, dict):
        return {"type": "UNCERTAIN", "confidence": 0.3, "reason": "Bad judge output; marked uncertain.", "dimensions": {}}
    t = str(out.get("type", "UNCERTAIN")).upper()
    if t not in REL_TYPES:
        t = "UNCERTAIN"
    try:
        conf = max(0.0, min(1.0, float(out.get("confidence", 0.5))))
    except (TypeError, ValueError):
        conf = 0.5
    return {"type": t, "confidence": conf, "reason": str(out.get("reason", ""))[:500], "dimensions": {}}


def _slim(f: dict[str, Any]) -> dict[str, Any]:
    return {k: f.get(k) for k in ("subject", "predicate", "value_raw", "unit_raw",
                                  "period_raw", "scope", "claim")}


def relate_pair(provider: LLMProvider, a: dict[str, Any], b: dict[str, Any],
                ev_a: str = "", ev_b: str = "") -> dict[str, Any]:
    dec = deterministic_decide(a, b)
    if dec is not None:
        return dec
    return llm_judge(provider, a, ev_a, b, ev_b)


def relate_new_fact(conn: sqlite3.Connection, provider: LLMProvider, fact: dict[str, Any],
                    collection_ids: Optional[list[str]] = None,
                    evidence_lookup: Optional[dict[str, str]] = None) -> list[dict[str, Any]]:
    """Find candidates for one new fact, decide + persist non-UNRELATED links."""
    out = []
    for cand in find_candidates(conn, fact, collection_ids):
        dec = relate_pair(provider, fact, cand,
                          (evidence_lookup or {}).get(fact["id"], ""),
                          (evidence_lookup or {}).get(cand["id"], ""))
        if dec["type"] == "UNRELATED":
            continue
        out.append(create_relationship(conn, fact["collection_id"], fact["id"], cand["id"],
                                       dec["type"], dec.get("confidence", 0.5),
                                       dec.get("reason", ""), dec.get("dimensions", {})))
    return out
