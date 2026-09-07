"""Basic persistence CRUD tests — Task 1."""
import tempfile
from pathlib import Path

from src.db import (
    create_collection,
    create_document,
    create_evidence,
    create_fact,
    create_job,
    create_relationship,
    get_collection_by_name,
    get_document_by_hash,
    init_db,
    list_collections,
    list_documents,
    list_evidence_for_fact,
    list_facts,
    list_page_status,
    list_relationships,
    list_relationships_for_fact,
    update_document_status,
    update_job,
    upsert_page_status,
)


def _tmpdb():
    d = tempfile.mkdtemp()
    return init_db(Path(d) / "t.db")


def test_collections():
    conn = _tmpdb()
    c = create_collection(conn, "delhivery", "test")
    assert get_collection_by_name(conn, "delhivery")["id"] == c["id"]
    assert len(list_collections(conn)) == 1
    conn.close()


def test_documents_hash_dedup_scope():
    conn = _tmpdb()
    c1 = create_collection(conn, "c1")
    c2 = create_collection(conn, "c2")
    d1 = create_document(conn, c1["id"], "a.pdf", "hash1", num_pages=3)
    assert get_document_by_hash(conn, c1["id"], "hash1")["id"] == d1["id"]
    # same hash allowed in different collection
    d2 = create_document(conn, c2["id"], "a.pdf", "hash1")
    assert d2["id"] != d1["id"]
    assert len(list_documents(conn, c1["id"])) == 1
    update_document_status(conn, d1["id"], "ready", num_pages=3)
    assert get_document_by_hash(conn, c1["id"], "hash1")["status"] == "ready"
    conn.close()


def test_facts_evidence_relationships():
    conn = _tmpdb()
    c = create_collection(conn, "delhivery")
    d1 = create_document(conn, c["id"], "annual.pdf", "h1")
    d2 = create_document(conn, c["id"], "ppt.pdf", "h2")
    f1 = create_fact(conn, c["id"], d1["id"], subject="Delhivery", predicate="express_parcels",
                     claim="740 Mn parcels in FY24", value_raw="740 Mn", value_norm=740_000_000.0,
                     period_raw="FY24", period_norm="FY24")
    f2 = create_fact(conn, c["id"], d2["id"], subject="Delhivery", predicate="express_parcels",
                     claim="740M shipments FY24", value_raw="740M", value_norm=740_000_000.0,
                     period_raw="FY24", period_norm="FY24")
    e1 = create_evidence(conn, f1["id"], d1["id"], page=10, text="Express parcel shipment volume 740 ...")
    assert list_evidence_for_fact(conn, f1["id"])[0]["id"] == e1["id"]
    assert len(list_facts(conn, c["id"], predicate="express_parcels")) == 2
    r = create_relationship(conn, c["id"], f1["id"], f2["id"], "CORROBORATES",
                            confidence=0.9, reason="same value normalized")
    assert r["type"] == "CORROBORATES"
    # canonical ordering: reversed insert updates same row
    r2 = create_relationship(conn, c["id"], f2["id"], f1["id"], "CORROBORATES", reason="x")
    assert r2["id"] == r["id"] or len(list_relationships(conn, c["id"])) == 1
    assert len(list_relationships_for_fact(conn, f1["id"])) == 1
    try:
        create_relationship(conn, c["id"], f1["id"], f1["id"], "CORROBORATES")
        raise AssertionError("self-link should fail")
    except ValueError:
        pass
    conn.close()


def test_jobs_pages():
    conn = _tmpdb()
    c = create_collection(conn, "c")
    d = create_document(conn, c["id"], "x.pdf", "hx")
    j = create_job(conn, "ingest", c["id"], d["id"])
    update_job(conn, j["id"], "done")
    upsert_page_status(conn, d["id"], 1, "ok", attempts=1, text_len=500, quality="good")
    upsert_page_status(conn, d["id"], 1, "ok", attempts=2, text_len=500, quality="good")
    assert len(list_page_status(conn, d["id"])) == 1
    conn.close()
