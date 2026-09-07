"""Selective candidate retrieval — never compare every fact with every fact.

Deterministic filters (subject/predicate/period/scope compatibility) narrow the
pool; semantic embeddings (if ever added) sit behind SemanticIndex and are used
for retrieval ONLY, never final classification. SQLite stays source of truth.
"""
from __future__ import annotations

import re
import sqlite3
from typing import Any, Optional


def _tokens(s: str) -> set[str]:
    return set(t for t in re.split(r"[^a-z0-9]+", (s or "").lower()) if t)


def subject_compatible(a: str, b: str) -> bool:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return False
    if ta == tb:
        return True
    # one subject contained in the other (Delhivery vs Delhivery Limited)
    return ta <= tb or tb <= ta or len(ta & tb) / max(len(ta), len(tb)) >= 0.5


def predicate_compatible(a: str, b: str) -> bool:
    if a == b:
        return True
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return False
    # shared stem (revenue_from_services vs revenue) counts as candidate
    return bool(ta & tb) and (ta <= tb or tb <= ta or len(ta & tb) >= 1 and _jaccard(ta, tb) >= 0.34)


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if (a | b) else 0.0


class SemanticIndex:
    """Abstraction for future embedding retrieval. Deterministic stub for now."""

    def candidates(self, fact: dict[str, Any], pool: list[dict[str, Any]], limit: int = 20) -> list[dict[str, Any]]:
        ft, fs = _tokens(fact.get("predicate", "")), _tokens(fact.get("subject", ""))
        scored = []
        for c in pool:
            s = _jaccard(ft, _tokens(c.get("predicate", ""))) * 2 + _jaccard(
                fs, _tokens(c.get("subject", "")))
            scored.append((s, c))
        scored.sort(key=lambda x: -x[0])
        return [c for _, c in scored[:limit]]


def find_candidates(
    conn: sqlite3.Connection,
    fact: dict[str, Any],
    collection_ids: Optional[list[str]] = None,
    limit: int = 20,
    semantic: Optional[SemanticIndex] = None,
    pool: Optional[list[dict[str, Any]]] = None,
) -> list[dict[str, Any]]:
    """Return at most `limit` related facts. Scope defaults to fact's collection.

    Cross-collection comparison only when collection_ids explicitly passed —
    enabling it never means all-vs-all. Pass `pool` (prefetched facts) to avoid
    one SQL scan per fact when relating many facts at once.
    """
    if pool is None:
        scope = collection_ids or [fact["collection_id"]]
        placeholders = ",".join("?" for _ in scope)
        rows = conn.execute(
            f"SELECT * FROM facts WHERE collection_id IN ({placeholders}) AND id != ?",
            (*scope, fact["id"]),
        ).fetchall()
        pool = [dict(r) for r in rows]
    else:
        scope = collection_ids or [fact["collection_id"]]
        pool = [c for c in pool if c["collection_id"] in scope and c["id"] != fact["id"]]

    filtered = [
        c for c in pool
        if predicate_compatible(fact.get("predicate", ""), c.get("predicate", ""))
        or (subject_compatible(fact.get("subject", ""), c.get("subject", ""))
            and fact.get("unit_norm") and fact.get("unit_norm") == c.get("unit_norm"))
    ]
    # rank: predicate match > subject match > same period > cross-doc
    def rank(c: dict[str, Any]) -> tuple:
        pred = 0 if c.get("predicate") == fact.get("predicate") else 1
        subj = 0 if _tokens(c.get("subject", "")) == _tokens(fact.get("subject", "")) else 1
        period = 0 if (c.get("period_norm") or "") == (fact.get("period_norm") or "") and fact.get("period_norm") else 1
        cross = 0 if c.get("document_id") != fact.get("document_id") else 1
        return (pred, subj, period, cross)

    filtered.sort(key=rank)
    if semantic is not None and len(filtered) > limit:
        return semantic.candidates(fact, filtered, limit)
    return filtered[:limit]
