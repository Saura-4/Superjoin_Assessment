"""Selective candidate retrieval — never compare every fact with every fact.

Two candidate sources (TASK3 hybrid):
- lexical: deterministic token filters (subject/predicate/unit);
- semantic: embedding cosine over `fact_embeddings` (auxiliary table only).
Merged + deduped, then structured reranking decides what reaches the
deterministic relationship layer. Embeddings NEVER classify relationships.
SQLite stays source of truth; no vector DB.
"""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Any, Optional

from src.embed import EMBEDDING_MODEL, cosine


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
    """In-process cosine index over `fact_embeddings` for one embedding model.

    Loads vectors once; `search` ranks by cosine similarity. Retrieval only.
    """

    def __init__(self, vectors: dict[str, list[float]] | None = None):
        self.vectors: dict[str, list[float]] = vectors or {}

    @classmethod
    def from_db(cls, conn: sqlite3.Connection, model: str = EMBEDDING_MODEL) -> "SemanticIndex":
        vecs: dict[str, list[float]] = {}
        for fid, v in conn.execute(
                "SELECT fact_id, vector FROM fact_embeddings WHERE model = ?", (model,)).fetchall():
            try:
                vecs[fid] = [float(x) for x in json.loads(v)]
            except (ValueError, TypeError):
                continue
        return cls(vecs)

    def __len__(self) -> int:
        return len(self.vectors)

    def candidates(self, fact: dict[str, Any], pool: list[dict[str, Any]], limit: int = 20) -> list[dict[str, Any]]:
        """Legacy token-rank hook (kept for compat); prefer search()."""
        ft, fs = _tokens(fact.get("predicate", "")), _tokens(fact.get("subject", ""))
        scored = []
        for c in pool:
            s = _jaccard(ft, _tokens(c.get("predicate", ""))) * 2 + _jaccard(
                fs, _tokens(c.get("subject", "")))
            scored.append((s, c))
        scored.sort(key=lambda x: -x[0])
        return [c for _, c in scored[:limit]]

    def search(self, vector: list[float], top_k: int = 20,
               exclude_ids: Optional[set[str]] = None) -> list[tuple[str, float]]:
        """Top-K (fact_id, cosine) excluding given ids. No DB access."""
        excl = exclude_ids or set()
        scored = [(fid, cosine(vector, v)) for fid, v in self.vectors.items() if fid not in excl]
        scored.sort(key=lambda x: -x[1])
        return scored[:top_k]


def hybrid_retrieve(
    conn: sqlite3.Connection,
    fact: dict[str, Any],
    index: SemanticIndex,
    query_vector: list[float],
    lex_k: int = 20,
    sem_k: int = 20,
    exclude_same_doc: bool = True,
    collection_ids: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    """Lexical ∪ semantic candidates, deduped, self/same-doc removed.

    Returns fact dicts (order: lexical hits first, then semantic-only hits).
    """
    lexical = find_candidates(conn, fact, collection_ids, limit=lex_k)
    lex_ids = {c["id"] for c in lexical}
    sem_hits = index.search(query_vector, top_k=sem_k, exclude_ids=lex_ids | {fact["id"]})
    sem_ids = [fid for fid, _ in sem_hits]
    extra = []
    if sem_ids:
        placeholders = ",".join("?" for _ in sem_ids)
        extra = [dict(r) for r in conn.execute(
            f"SELECT * FROM facts WHERE id IN ({placeholders})", tuple(sem_ids)).fetchall()]
    merged = {c["id"]: c for c in lexical}
    for c in extra:
        merged.setdefault(c["id"], c)
    out = [c for c in merged.values()
           if c["id"] != fact["id"]
           and not (exclude_same_doc and c.get("document_id") == fact.get("document_id"))]
    # drop cross-collection strays unless explicitly scoped in
    scope = set(collection_ids or [fact["collection_id"]])
    return [c for c in out if c.get("collection_id") in scope]


def rerank_score(a: dict[str, Any], b: dict[str, Any],
                 sem_score: float = 0.0, lex_score: float = 0.0) -> float:
    """Deterministic, explainable compatibility 0..1 (TASK3 Phase 6).

    Embeddings/lexical scores are advisory inputs; structured fields dominate.
    """
    ta, tb = _tokens(a.get("subject", "")), _tokens(b.get("subject", ""))
    pa, pb = _tokens(a.get("predicate", "")), _tokens(b.get("predicate", ""))
    if ta == tb and ta:
        s_sub, s_pred = 1.0, 0.0
    else:
        s_sub = 0.6 if (ta and tb and (ta <= tb or tb <= ta or len(ta & tb) / max(len(ta), len(tb)) >= 0.5)) else 0.0
        s_pred = 0.0
    if pa == pb and pa:
        s_pred = 1.0
    elif pa and pb and (pa <= pb or pb <= pa):
        s_pred = 0.6
    elif pa and pb and (pa & pb):
        s_pred = 0.4
    ea, eb = (a.get("period_norm") or ""), (b.get("period_norm") or "")
    s_per = 1.0 if (ea and ea == eb) else (0.5 if not (ea and eb) else 0.0)
    sa, sb = (a.get("scope") or "").strip().lower(), (b.get("scope") or "").strip().lower()
    s_scope = 1.0 if (sa and sa == sb) else (0.5 if not (sa and sb) else 0.2)
    ua, ub = a.get("unit_norm") or "", b.get("unit_norm") or ""
    s_unit = 1.0 if (ua and ua == ub) else 0.3
    va, vb = a.get("value_norm"), b.get("value_norm")
    if va is None or vb is None:
        s_val = 0.5
    else:
        denom = max(abs(va), abs(vb), 1e-9)
        s_val = 1.0 if abs(va - vb) / denom <= 0.02 else 0.4
    base = 0.25 * s_sub + 0.25 * s_pred + 0.15 * s_per + 0.10 * s_scope + 0.10 * s_unit + 0.15 * s_val
    # retrieval signals nudge, never override structure
    nudge = 0.05 * max(0.0, min(1.0, sem_score)) + 0.05 * max(0.0, min(1.0, lex_score))
    total = min(1.0, base + nudge)
    if s_sub == 0.0 and sem_score < 0.5:
        # different entities with no semantic rescue: not worth judging
        total = min(total, 0.39)
    return round(total, 3)


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
