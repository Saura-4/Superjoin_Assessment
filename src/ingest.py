"""PDF ingestion: hash → register → page text → quality → persistence.

Local parsing only (PyMuPDF). No LLM here. Page text is cached on disk so
large PDFs can be processed incrementally and retried per page.
"""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Any

import pymupdf  # PyMuPDF

from src.db import (
    create_document,
    get_document_by_hash,
    update_document_status,
    upsert_page_status,
)

EMPTY_THRESHOLD = 50
LOW_THRESHOLD = 300


def sha256_of_file(path: str | Path, chunk_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def quality_for_text(text: str) -> str:
    """good / low / empty based on extractable text length."""
    s = (text or "").strip()
    if len(s) < EMPTY_THRESHOLD:
        return "empty"
    if len(s) < LOW_THRESHOLD:
        return "low"
    alnum = sum(1 for ch in s if ch.isalnum())
    if alnum < 20:
        return "empty"
    if len(s) < LOW_THRESHOLD and alnum < 80:
        return "low"
    return "good"


def extract_pages(pdf_path: str | Path) -> list[dict[str, Any]]:
    """Return [{page (1-indexed), text}]. Raises on malformed PDF."""
    pages: list[dict[str, Any]] = []
    with pymupdf.open(str(pdf_path)) as doc:
        for i, pg in enumerate(doc):
            try:
                text = pg.get_text("text") or ""
            except Exception:
                text = ""
            pages.append({"page": i + 1, "text": text})
    if not pages:
        raise ValueError(f"no pages extracted: {pdf_path}")
    return pages


def ingest_pdf(
    conn: sqlite3.Connection,
    collection_id: str,
    pdf_path: str | Path,
    data_dir: str | Path = "data",
) -> dict[str, Any]:
    """Register + extract + persist page status. Duplicate-safe via content hash.

    Returns {"document": row, "duplicate": bool, "pages": [...], "quality_counts": {...}}.
    Page texts cached at <data_dir>/<collection_id>/<document_id>/page-XXXX.txt
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.is_file():
        raise FileNotFoundError(str(pdf_path))
    file_hash = sha256_of_file(pdf_path)

    existing = get_document_by_hash(conn, collection_id, file_hash)
    if existing is not None:
        return {"document": existing, "duplicate": True, "pages": [], "quality_counts": {}}

    doc_row = create_document(conn, collection_id, pdf_path.name, file_hash, status="processing")
    try:
        pages = extract_pages(pdf_path)
    except Exception as exc:  # malformed PDF
        update_document_status(conn, doc_row["id"], "failed", error=f"extract_failed: {exc}")
        raise

    doc_dir = Path(data_dir) / collection_id / doc_row["id"]
    doc_dir.mkdir(parents=True, exist_ok=True)

    counts = {"good": 0, "low": 0, "empty": 0}
    for p in pages:
        q = quality_for_text(p["text"])
        counts[q] += 1
        (doc_dir / f"page-{p['page']:04d}.txt").write_text(p["text"], encoding="utf-8")
        upsert_page_status(conn, doc_row["id"], p["page"], status="extracted" if q == "good" else "low_text",
                           attempts=1, text_len=len(p["text"]), quality=q)
        p["quality"] = q

    update_document_status(conn, doc_row["id"], "ready", num_pages=len(pages))
    doc_row = get_document_by_hash(conn, collection_id, file_hash) or doc_row
    return {"document": doc_row, "duplicate": False, "pages": pages, "quality_counts": counts}


def load_cached_page_text(data_dir: str | Path, collection_id: str, document_id: str, page: int) -> str:
    p = Path(data_dir) / collection_id / document_id / f"page-{page:04d}.txt"
    return p.read_text(encoding="utf-8") if p.is_file() else ""
