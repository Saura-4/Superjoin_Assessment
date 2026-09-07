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
from src.retrieve import find_candidates, subject_compatible

REL_TYPES = {"CORROBORATES", "CONTRADICTS", "RECONCILED", "TEMPORAL_CHANGE", "UNRELATED", "UNCERTAIN"}

REL_TOL = 0.02  # 2% rounding tolerance for cross-document numeric agreement

JUDGE_SYSTEM = """You judge the relationship between two extracted facts.
Return JSON only: {"type": one of CORROBORATES/CONTRADICTS/RECONCILED/TEMPORAL_CHANGE/UNRELATED/UNCERTAIN, "confidence": 0-1, "reason": "1-2 sentences citing periods/scopes/units"}.
Rules: same metric+period+scope with equal values (after units) = CORROBORATES. Same metric+period+scope with different values = CONTRADICTS. Same metric but different period granularity/scope/definitions explaining the gap = RECONCILED (name the dimension). Same metric, different time points, changed value = TEMPORAL_CHANGE, not contradiction. Different subjects/entities with different values = UNRELATED, never a contradiction. Differing qualifiers/conditions = RECONCILED or UNRELATED, not CONTRADICTS. Different metrics = UNRELATED. Unclear = UNCERTAIN. Calibrate confidence: 0.9 only for exact agreement/disagreement on precise numbers; 0.6-0.7 for rounded or textually inferred pairs; never 1.0."""


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


def _quals(f: dict[str, Any]) -> dict[str, Any]:
    q = f.get("qualifiers", {})
    if isinstance(q, str):
        try:
            q = json.loads(q)
        except (json.JSONDecodeError, ValueError):
            return {}
    return q if isinstance(q, dict) else {}


def _zero_overlap(a: str, b: str) -> bool:
    import re as _re
    ta = set(t for t in _re.split(r"[^a-z0-9]+", (a or "").lower()) if t)
    tb = set(t for t in _re.split(r"[^a-z0-9]+", (b or "").lower()) if t)
    return bool(ta and tb) and not (ta & tb)


def deterministic_decide(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any] | None:
    """Return decision dict or None when genuinely ambiguous (needs LLM)."""
    if a.get("predicate") != b.get("predicate"):
        return None  # predicate semantics need judgment
    if _zero_overlap(a.get("subject", ""), b.get("subject", "")):
        va, vb = a.get("value_norm"), b.get("value_norm")
        if va is not None and vb is not None and values_equal(va, vb) is not True:
            # wholly distinct entities, different values: different facts, not a fight
            return {"type": "UNRELATED", "confidence": 0.85,
                    "reason": "Different subjects with no shared terms and different values; unrelated facts.",
                    "dimensions": {}}
        if va is None or vb is None:
            return {"type": "UNRELATED", "confidence": 0.7,
                    "reason": "Different subjects with no shared terms; unrelated facts.",
                    "dimensions": {}}
        # equal values despite different names: fall through (possible alias/corroboration)
    elif not subject_compatible(a.get("subject", ""), b.get("subject", "")):
        return None  # partially overlapping entities — needs judgment, never a blind contradiction
    if _quals(a) and _quals(b) and _quals(a) != _quals(b):
        return None  # differing conditions/qualifiers need judgment, not a numeric verdict
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
    out = llm_judge_batch(provider, [(a, ev_a, b, ev_b)])
    return out[0]


def llm_judge_batch(provider: LLMProvider,
                     pairs: list[tuple[dict[str, Any], str, dict[str, Any], str]],
                     chunk: int = 5) -> list[dict[str, Any]]:
    """Judge many ambiguous pairs in few LLM calls (quota-friendly).

    One call per `chunk` pairs; malformed chunk responses degrade to UNCERTAIN
    per pair (no quota-burning retries). Empty input → [].
    Small chunks: lite models drop entries from oversized batches.
    """
    decisions: list[dict[str, Any]] = []
    for i in range(0, len(pairs), chunk):
        decisions.extend(_judge_chunk(provider, pairs[i:i + chunk]))
    return decisions


def _judge_chunk(provider: LLMProvider, pairs: list[tuple[dict[str, Any], str, dict[str, Any], str]]) -> list[dict[str, Any]]:
    def uncertain(reason: str) -> dict[str, Any]:
        return {"type": "UNCERTAIN", "confidence": 0.3, "reason": reason, "dimensions": {}}

    body = []
    for n, (a, ev_a, b, ev_b) in enumerate(pairs):
        body.append(f"--- PAIR {n} ---\nFact A: {json.dumps(_slim(a))}\nEvidence A: {ev_a[:500]}"
                    f"\nFact B: {json.dumps(_slim(b))}\nEvidence B: {ev_b[:500]}")
    prompt = ("RELATION JUDGE. Decide each pair independently.\n" + "\n".join(body)
              + '\n\nReturn JSON: {"decisions": [{"type": ..., "confidence": 0-1, "reason": "..."}]}'
                " with exactly one entry per pair, same order.")
    try:
        out = provider.generate_json(prompt, system=JUDGE_SYSTEM,
                                     cache_key=f"judge-batch:{pairs[0][0]['id']}:{len(pairs)}",
                                     namespace="judge-v3-qualified")
    except LLMError:
        return [uncertain("LLM unavailable; marked uncertain.") for _ in pairs]
    decs = out.get("decisions", []) if isinstance(out, dict) else []
    result = []
    for n in range(len(pairs)):
        d = decs[n] if n < len(decs) and isinstance(decs[n], dict) else {}
        t = str(d.get("type", "UNCERTAIN")).upper()
        if t not in REL_TYPES:
            t = "UNCERTAIN"
        try:
            conf = max(0.0, min(1.0, float(d.get("confidence", 0.5))))
        except (TypeError, ValueError):
            conf = 0.5
        result.append({"type": t, "confidence": conf,
                       "reason": str(d.get("reason", ""))[:500], "dimensions": {}})
    return result


def _slim(f: dict[str, Any]) -> dict[str, Any]:
    slim = {k: f.get(k) for k in ("subject", "predicate", "value_raw", "unit_raw",
                                  "period_raw", "scope", "claim")}
    slim["qualifiers"] = _quals(f)
    return slim


def relate_pair(provider: LLMProvider, a: dict[str, Any], b: dict[str, Any],
                ev_a: str = "", ev_b: str = "") -> dict[str, Any]:
    dec = deterministic_decide(a, b)
    if dec is not None:
        return dec
    return llm_judge(provider, a, ev_a, b, ev_b)


def relate_new_fact(conn: sqlite3.Connection, provider: LLMProvider, fact: dict[str, Any],
                    collection_ids: Optional[list[str]] = None,
                    evidence_lookup: Optional[dict[str, str]] = None) -> list[dict[str, Any]]:
    """Single-fact wrapper (kept for tests/callers); prefer relate_new_facts for batches."""
    return relate_new_facts(conn, provider, [fact], collection_ids, evidence_lookup)


def relate_new_facts(conn: sqlite3.Connection, provider: LLMProvider, facts: list[dict[str, Any]],
                     collection_ids: Optional[list[str]] = None,
                     evidence_lookup: Optional[dict[str, str]] = None) -> list[dict[str, Any]]:
    """Deterministic decisions for all pairs first; ambiguous pairs judged in batches."""
    lookup = evidence_lookup or {}
    out = []
    ambiguous: list[tuple[dict[str, Any], str, dict[str, Any], str]] = []
    pool: Optional[list[dict[str, Any]]] = None
    if len(facts) > 3:
        # one prefetch instead of one SQL scan per fact (heal path is O(n) SQL now)
        scope = collection_ids or [facts[0]["collection_id"]]
        placeholders = ",".join("?" for _ in scope)
        pool = [dict(r) for r in conn.execute(
            f"SELECT * FROM facts WHERE collection_id IN ({placeholders})", tuple(scope)).fetchall()]
    for fact in facts:
        for cand in find_candidates(conn, fact, collection_ids, pool=pool):
            dec = deterministic_decide(fact, cand)
            if dec is None:
                # LLM judgment is reserved for cross-document ambiguity: within one
                # disclosure, distinct facts are noise to a knowledge layer, and
                # judging them burns quota for UNCERTAIN verdicts.
                if cand.get("document_id") == fact.get("document_id"):
                    dec = {"type": "UNCERTAIN", "confidence": 0.3,
                           "reason": "Same-document ambiguity without cross-doc evidence; left uncertain.",
                           "dimensions": {}}
                else:
                    ambiguous.append((fact, lookup.get(fact["id"], ""), cand, lookup.get(cand["id"], "")))
                    continue
            if dec["type"] != "UNRELATED":
                out.append(create_relationship(conn, fact["collection_id"], fact["id"], cand["id"],
                                               dec["type"], dec.get("confidence", 0.5),
                                               dec.get("reason", ""), dec.get("dimensions", {})))
    if ambiguous:
        judged = llm_judge_batch(provider, ambiguous)
        for (fact, _, cand, _), dec in zip(ambiguous, judged):
            if dec["type"] == "UNRELATED":
                continue
            out.append(create_relationship(conn, fact["collection_id"], fact["id"], cand["id"],
                                           dec["type"], dec.get("confidence", 0.5),
                                           dec.get("reason", ""), dec.get("dimensions", {})))
    _bump_corroborated(conn, out)
    return out


def _bump_corroborated(conn: sqlite3.Connection, rels: list[dict[str, Any]]) -> None:
    """Corroboration earns confidence: facts confirmed by an independent source
    get +0.05 capped at 0.95. Single-source facts never reach certainty alone."""
    seen: set[str] = set()
    for r in rels:
        if r.get("type") == "CORROBORATES":
            seen.add(r["fact_a_id"])
            seen.add(r["fact_b_id"])
    for fid in seen:
        conn.execute(
            "UPDATE facts SET confidence = min(0.95, round(confidence + 0.05, 3)) WHERE id = ?", (fid,))
    if seen:
        conn.commit()


def relate_unlinked_facts(conn: sqlite3.Connection, provider: LLMProvider,
                          collection_id: str, document_id: str,
                          collection_ids: Optional[list[str]] = None) -> list[dict[str, Any]]:
    """Heal interrupted runs: relate doc facts that have no relationships yet.

    Pages are marked processed before relating, so a kill leaves processed-but-
    unlinked facts; resume must link them instead of returning early.
    """
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM facts WHERE collection_id = ? AND document_id = ?",
        (collection_id, document_id)).fetchall()]
    if not rows:
        return []
    linked: set[str] = set()
    for r in conn.execute(
            "SELECT fact_a_id, fact_b_id FROM relationships WHERE collection_id = ?",
            (collection_id,)).fetchall():
        linked.add(r[0])
        linked.add(r[1])
    unlinked = [f for f in rows if f["id"] not in linked]
    if not unlinked:
        return []
    lookup = {e["fact_id"]: e["text"] for e in conn.execute(
        "SELECT fact_id, text FROM evidence WHERE document_id = ?", (document_id,)).fetchall()}
    return relate_new_facts(conn, provider, unlinked, collection_ids, lookup)
