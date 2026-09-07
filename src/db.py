"""SQLite persistence for the Fact Knowledge Layer.

One database, many collections. Predicates and relationship types are data,
not columns — the schema stays stable while fact kinds evolve.

Tables: collections, documents, facts, evidence, relationships,
processing_jobs, page_processing.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS collections (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    file_hash TEXT NOT NULL,
    num_pages INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'registered',
    error TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(collection_id, file_hash)
);
CREATE INDEX IF NOT EXISTS idx_documents_collection ON documents(collection_id);

CREATE TABLE IF NOT EXISTS facts (
    id TEXT PRIMARY KEY,
    collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    subject TEXT NOT NULL,
    predicate TEXT NOT NULL,
    value_raw TEXT NOT NULL DEFAULT '',
    value_norm REAL,
    unit_raw TEXT NOT NULL DEFAULT '',
    unit_norm TEXT NOT NULL DEFAULT '',
    period_raw TEXT NOT NULL DEFAULT '',
    period_norm TEXT NOT NULL DEFAULT '',
    scope TEXT NOT NULL DEFAULT '',
    qualifiers TEXT NOT NULL DEFAULT '{}',
    claim TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.5,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_facts_collection ON facts(collection_id);
CREATE INDEX IF NOT EXISTS idx_facts_predicate ON facts(collection_id, predicate);
CREATE INDEX IF NOT EXISTS idx_facts_subject ON facts(collection_id, subject);
CREATE INDEX IF NOT EXISTS idx_facts_document ON facts(document_id);

CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY,
    fact_id TEXT NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page INTEGER NOT NULL,
    text TEXT NOT NULL,
    bbox TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evidence_fact ON evidence(fact_id);

CREATE TABLE IF NOT EXISTS relationships (
    id TEXT PRIMARY KEY,
    collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    fact_a_id TEXT NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
    fact_b_id TEXT NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.5,
    reason TEXT NOT NULL DEFAULT '',
    dimensions TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(fact_a_id, fact_b_id)
);
CREATE INDEX IF NOT EXISTS idx_rel_collection ON relationships(collection_id);
CREATE INDEX IF NOT EXISTS idx_rel_facts ON relationships(fact_a_id, fact_b_id);

CREATE TABLE IF NOT EXISTS processing_jobs (
    id TEXT PRIMARY KEY,
    collection_id TEXT REFERENCES collections(id) ON DELETE CASCADE,
    document_id TEXT REFERENCES documents(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS page_processing (
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    text_len INTEGER NOT NULL DEFAULT 0,
    quality TEXT NOT NULL DEFAULT 'unknown',
    PRIMARY KEY (document_id, page)
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: str | Path) -> sqlite3.Connection:
    conn = get_connection(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


# ---- collections ----

def create_collection(conn: sqlite3.Connection, name: str, description: str = "") -> dict[str, Any]:
    cid = _new_id()
    conn.execute(
        "INSERT INTO collections (id, name, description, created_at) VALUES (?, ?, ?, ?)",
        (cid, name.strip(), description, _now()),
    )
    conn.commit()
    return get_collection(conn, cid)  # type: ignore[return-value]


def get_collection(conn: sqlite3.Connection, collection_id: str) -> dict[str, Any] | None:
    return _row_to_dict(conn.execute("SELECT * FROM collections WHERE id = ?", (collection_id,)).fetchone())


def get_collection_by_name(conn: sqlite3.Connection, name: str) -> dict[str, Any] | None:
    return _row_to_dict(conn.execute("SELECT * FROM collections WHERE name = ?", (name,)).fetchone())


def list_collections(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute("SELECT * FROM collections ORDER BY created_at").fetchall()]


# ---- documents ----

def create_document(
    conn: sqlite3.Connection,
    collection_id: str,
    filename: str,
    file_hash: str,
    num_pages: int = 0,
    status: str = "registered",
) -> dict[str, Any]:
    did = _new_id()
    conn.execute(
        """INSERT INTO documents (id, collection_id, filename, file_hash, num_pages, status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (did, collection_id, filename, file_hash, num_pages, status, _now()),
    )
    conn.commit()
    return get_document(conn, did)  # type: ignore[return-value]


def get_document(conn: sqlite3.Connection, document_id: str) -> dict[str, Any] | None:
    return _row_to_dict(conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone())


def get_document_by_hash(conn: sqlite3.Connection, collection_id: str, file_hash: str) -> dict[str, Any] | None:
    return _row_to_dict(
        conn.execute(
            "SELECT * FROM documents WHERE collection_id = ? AND file_hash = ?",
            (collection_id, file_hash),
        ).fetchone()
    )


def list_documents(conn: sqlite3.Connection, collection_id: str) -> list[dict[str, Any]]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM documents WHERE collection_id = ? ORDER BY created_at", (collection_id,)
        ).fetchall()
    ]


def update_document_status(
    conn: sqlite3.Connection, document_id: str, status: str, error: Optional[str] = None,
    num_pages: Optional[int] = None,
) -> None:
    if num_pages is not None:
        conn.execute(
            "UPDATE documents SET status = ?, error = ?, num_pages = ? WHERE id = ?",
            (status, error, num_pages, document_id),
        )
    else:
        conn.execute(
            "UPDATE documents SET status = ?, error = ? WHERE id = ?", (status, error, document_id)
        )
    conn.commit()


# ---- facts ----

def create_fact(
    conn: sqlite3.Connection,
    collection_id: str,
    document_id: str,
    subject: str,
    predicate: str,
    claim: str,
    value_raw: str = "",
    value_norm: Optional[float] = None,
    unit_raw: str = "",
    unit_norm: str = "",
    period_raw: str = "",
    period_norm: str = "",
    scope: str = "",
    qualifiers: Optional[dict[str, Any]] = None,
    confidence: float = 0.5,
) -> dict[str, Any]:
    fid = _new_id()
    conn.execute(
        """INSERT INTO facts (id, collection_id, document_id, subject, predicate, value_raw, value_norm,
                              unit_raw, unit_norm, period_raw, period_norm, scope, qualifiers, claim,
                              confidence, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            fid, collection_id, document_id, subject.strip(), predicate.strip(),
            value_raw, value_norm, unit_raw, unit_norm, period_raw, period_norm,
            scope, json.dumps(qualifiers or {}), claim, confidence, _now(),
        ),
    )
    conn.commit()
    return get_fact(conn, fid)  # type: ignore[return-value]


def get_fact(conn: sqlite3.Connection, fact_id: str) -> dict[str, Any] | None:
    return _row_to_dict(conn.execute("SELECT * FROM facts WHERE id = ?", (fact_id,)).fetchone())


def list_facts(
    conn: sqlite3.Connection,
    collection_id: str,
    predicate: Optional[str] = None,
    subject_like: Optional[str] = None,
    document_id: Optional[str] = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    q = "SELECT * FROM facts WHERE collection_id = ?"
    args: list[Any] = [collection_id]
    if predicate:
        q += " AND predicate = ?"
        args.append(predicate)
    if document_id:
        q += " AND document_id = ?"
        args.append(document_id)
    if subject_like:
        q += " AND subject LIKE ?"
        args.append(f"%{subject_like}%")
    q += " ORDER BY created_at LIMIT ?"
    args.append(limit)
    return [dict(r) for r in conn.execute(q, tuple(args)).fetchall()]


# ---- evidence ----

def create_evidence(
    conn: sqlite3.Connection,
    fact_id: str,
    document_id: str,
    page: int,
    text: str,
    bbox: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    eid = _new_id()
    conn.execute(
        "INSERT INTO evidence (id, fact_id, document_id, page, text, bbox, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (eid, fact_id, document_id, page, text, json.dumps(bbox) if bbox else None, _now()),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM evidence WHERE id = ?", (eid,)).fetchone()
    return dict(row)


def list_evidence_for_fact(conn: sqlite3.Connection, fact_id: str) -> list[dict[str, Any]]:
    return [
        dict(r)
        for r in conn.execute("SELECT * FROM evidence WHERE fact_id = ? ORDER BY page", (fact_id,)).fetchall()
    ]


# ---- relationships (fact-to-fact, canonical ordering) ----

def _canonical(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


def create_relationship(
    conn: sqlite3.Connection,
    collection_id: str,
    fact_a_id: str,
    fact_b_id: str,
    rel_type: str,
    confidence: float = 0.5,
    reason: str = "",
    dimensions: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    if fact_a_id == fact_b_id:
        raise ValueError("fact_a_id and fact_b_id must differ")
    fa, fb = _canonical(fact_a_id, fact_b_id)
    rid = _new_id()
    conn.execute(
        """INSERT INTO relationships (id, collection_id, fact_a_id, fact_b_id, type, confidence, reason, dimensions, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(fact_a_id, fact_b_id) DO UPDATE SET type=excluded.type, confidence=excluded.confidence,
             reason=excluded.reason, dimensions=excluded.dimensions""",
        (rid, collection_id, fa, fb, rel_type, confidence, reason, json.dumps(dimensions or {}), _now()),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM relationships WHERE fact_a_id = ? AND fact_b_id = ?", (fa, fb)
    ).fetchone()
    return dict(row)


def list_relationships(
    conn: sqlite3.Connection, collection_id: str, rel_type: Optional[str] = None, limit: int = 1000
) -> list[dict[str, Any]]:
    q = "SELECT * FROM relationships WHERE collection_id = ?"
    args: list[Any] = [collection_id]
    if rel_type:
        q += " AND type = ?"
        args.append(rel_type)
    q += " ORDER BY created_at LIMIT ?"
    args.append(limit)
    return [dict(r) for r in conn.execute(q, tuple(args)).fetchall()]


def list_relationships_for_fact(conn: sqlite3.Connection, fact_id: str) -> list[dict[str, Any]]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM relationships WHERE fact_a_id = ? OR fact_b_id = ?", (fact_id, fact_id)
        ).fetchall()
    ]


# ---- jobs / pages ----

def create_job(
    conn: sqlite3.Connection, kind: str, collection_id: str | None = None,
    document_id: str | None = None, status: str = "pending",
) -> dict[str, Any]:
    jid = _new_id()
    now = _now()
    conn.execute(
        """INSERT INTO processing_jobs (id, collection_id, document_id, kind, status, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (jid, collection_id, document_id, kind, status, now, now),
    )
    conn.commit()
    return dict(conn.execute("SELECT * FROM processing_jobs WHERE id = ?", (jid,)).fetchone())


def update_job(conn: sqlite3.Connection, job_id: str, status: str, error: Optional[str] = None) -> None:
    conn.execute(
        "UPDATE processing_jobs SET status = ?, error = ?, updated_at = ? WHERE id = ?",
        (status, error, _now(), job_id),
    )
    conn.commit()


def upsert_page_status(
    conn: sqlite3.Connection, document_id: str, page: int, status: str,
    attempts: int = 0, error: Optional[str] = None, text_len: int = 0, quality: str = "unknown",
) -> None:
    conn.execute(
        """INSERT INTO page_processing (document_id, page, status, attempts, error, text_len, quality)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(document_id, page) DO UPDATE SET status=excluded.status, attempts=excluded.attempts,
             error=excluded.error, text_len=excluded.text_len, quality=excluded.quality""",
        (document_id, page, status, attempts, error, text_len, quality),
    )
    conn.commit()


def list_page_status(conn: sqlite3.Connection, document_id: str) -> list[dict[str, Any]]:
    return [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM page_processing WHERE document_id = ? ORDER BY page", (document_id,)
        ).fetchall()
    ]
