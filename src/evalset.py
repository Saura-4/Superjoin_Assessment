"""Deterministic eval-set selection (TASK3 Phase 1): N facts per document.

Round-robin over predicates per document (rowid order within predicate) so the
set spreads across metrics instead of one dense section. Pure function of DB
contents — same DB always yields the same set.
"""
from __future__ import annotations

import sqlite3
from typing import Any


def select_eval_set(conn: sqlite3.Connection, document_ids: list[str],
                    per_doc: int = 100) -> list[dict[str, Any]]:
    """Return up to per_doc facts per document id."""
    out: list[dict[str, Any]] = []
    for did in document_ids:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM facts WHERE document_id = ? ORDER BY rowid", (did,)).fetchall()]
        groups: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            groups.setdefault(r.get("predicate", ""), []).append(r)
        ordered = [groups[p] for p in sorted(groups)]
        picked: list[dict[str, Any]] = []
        i = 0
        while len(picked) < per_doc:
            added = False
            for g in ordered:
                if i < len(g):
                    picked.append(g[i])
                    added = True
                    if len(picked) >= per_doc:
                        break
            if not added:
                break
            i += 1
        out.extend(picked)
    return out
