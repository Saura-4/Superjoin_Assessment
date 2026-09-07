"""Incremental processing + collection scope (Tasks 9-10).

upload → hash → reuse if processed, else process → extract new facts →
compare ONLY new facts vs relevant existing → add relationships.
No full rebuild. Page-level statuses make failures retryable.
Comparison scope (current / selected / all collections) is explicit data —
never collection-name special-casing.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Optional

from src.db import (
    create_collection,
    create_job,
    get_collection_by_name,
    list_documents,
    list_facts,
    list_page_status,
    list_relationships,
    page_has_facts,
    rename_document,
    update_document_status,
    update_job,
    upsert_page_status,
)
from src.extract import extract_facts_from_text, persist_facts_with_evidence
from src.ingest import ingest_pdf, load_cached_page_text
from src.llm import LLMProvider
from src.relate import relate_new_facts, relate_unlinked_facts

RESUMABLE_STATUSES = {"extracted", "low_text", "pending", "failed"}


def get_or_create_collection(conn: sqlite3.Connection, name: str, description: str = "") -> dict[str, Any]:
    existing = get_collection_by_name(conn, name.strip())
    if existing:
        return existing
    return create_collection(conn, name.strip(), description)


def collection_stats(conn: sqlite3.Connection, collection_id: str) -> dict[str, Any]:
    docs = list_documents(conn, collection_id)
    facts = list_facts(conn, collection_id, limit=100_000)
    rels = list_relationships(conn, collection_id, limit=100_000)
    return {"documents": len(docs), "facts": len(facts), "relationships": len(rels)}


def resolve_scope(conn: sqlite3.Connection, current_collection_id: str,
                  scope: str = "current",
                  selected: Optional[list[str]] = None) -> list[str]:
    """scope: 'current' | 'selected' | 'all'. Returns collection id list."""
    if scope == "all":
        return [r["collection_id"] for r in
                conn.execute("SELECT DISTINCT collection_id FROM facts").fetchall()] or [current_collection_id]
    if scope == "selected":
        ids = [i for i in (selected or []) if i]
        return ids or [current_collection_id]
    return [current_collection_id]


def process_document(
    conn: sqlite3.Connection,
    provider: LLMProvider,
    collection_id: str,
    pdf_path: str | Path,
    data_dir: str | Path = "data",
    max_pages: Optional[int] = None,
    scope: str = "current",
    filename: Optional[str] = None,
) -> dict[str, Any]:
    """Full incremental ingest for one PDF. Duplicate hash → reuse, no rework.

    `filename` is the user-facing name (uploads arrive as temp paths).
    """
    job = create_job(conn, "ingest", collection_id)
    try:
        ing = ingest_pdf(conn, collection_id, pdf_path, data_dir=data_dir)
    except Exception as exc:
        update_job(conn, job["id"], "failed", error=str(exc)[:500])
        raise
    if ing["duplicate"]:
        # Resume interrupted runs: reprocess pages never finished, else reuse.
        statuses = {p["page"]: p for p in list_page_status(conn, ing["document"]["id"])}
        todo = sorted(p for p, s in statuses.items() if s["status"] in RESUMABLE_STATUSES)
        if not todo:
            # fully processed: heal any facts left unlinked by an interrupted
            # relate phase, then reuse without rebuild.
            scope_ids = resolve_scope(conn, collection_id, scope)
            healed = relate_unlinked_facts(conn, provider, collection_id,
                                           ing["document"]["id"], scope_ids)
            update_document_status(conn, ing["document"]["id"], "ready")
            update_job(conn, job["id"], "done", error="duplicate_reused")
            return {"document": get_doc(conn, ing["document"]["id"]), "duplicate": True,
                    "facts_added": 0, "relationships_added": len(healed), "failures": []}
        doc = ing["document"]
        pages = [{"page": p,
                  "text": load_cached_page_text(data_dir, collection_id, doc["id"], p),
                  "quality": statuses[p]["quality"]} for p in todo]
        update_job(conn, job["id"], "done", error=None)
    else:
        doc = ing["document"]
        if filename and not ing["duplicate"]:
            rename_document(conn, doc["id"], Path(filename).name)
            doc = get_doc(conn, doc["id"])
        pages = ing["pages"][:max_pages] if max_pages else ing["pages"]
    if max_pages:
        pages = pages[:max_pages]
    scope_ids = resolve_scope(conn, collection_id, scope)
    facts_added, rels_added, failures = 0, 0, []
    evidence_lookup: dict[str, str] = {}
    new_rows: list[dict[str, Any]] = []

    for p in pages:
        page_no, text, quality = p["page"], p["text"], p.get("quality", "unknown")
        if page_has_facts(conn, doc["id"], page_no):
            # interrupted run already persisted this page's facts: skip, don't duplicate
            upsert_page_status(conn, doc["id"], page_no, status="processed",
                               attempts=1, text_len=len(text), quality=quality)
            continue
        if quality == "empty":
            upsert_page_status(conn, doc["id"], page_no, status="empty_no_text",
                               attempts=1, text_len=len(text), quality=quality)
            failures.append({"page": page_no, "kind": "extraction_failure",
                             "detail": "no extractable text layer (chart/scan?); no facts fabricated"})
            continue
        try:
            found = extract_facts_from_text(provider, text, page=page_no)
        except Exception as exc:
            upsert_page_status(conn, doc["id"], page_no, status="failed",
                               attempts=1, error=str(exc)[:300], text_len=len(text), quality=quality)
            failures.append({"page": page_no, "kind": "fact_extraction_failure", "detail": str(exc)[:300]})
            continue
        if not found:
            upsert_page_status(conn, doc["id"], page_no, status="processed_no_facts",
                               attempts=1, text_len=len(text), quality=quality)
            continue
        rows = persist_facts_with_evidence(conn, collection_id, doc["id"], page_no, found)
        for r, f in zip(rows, found):
            evidence_lookup[r["id"]] = f.get("evidence_quote", "")
        upsert_page_status(conn, doc["id"], page_no, status="processed",
                           attempts=1, text_len=len(text), quality=quality)
        facts_added += len(rows)
        new_rows.extend(rows)

    # relate once per document: deterministic first, ambiguous judged in batches
    if new_rows:
        rels = relate_new_facts(conn, provider, new_rows, collection_ids=scope_ids,
                                evidence_lookup=evidence_lookup)
        rels_added = len(rels)

    update_document_status(conn, doc["id"], "ready")
    update_job(conn, job["id"], "done")
    return {"document": get_doc(conn, doc["id"]), "duplicate": False,
            "facts_added": facts_added, "relationships_added": rels_added, "failures": failures}


def get_doc(conn: sqlite3.Connection, document_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
    return dict(row)
