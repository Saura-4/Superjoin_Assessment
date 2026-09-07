"""Tasks 9-10 tests: incremental reuse + scope resolution."""
from pathlib import Path

import pytest

from src.db import init_db, list_facts, list_relationships
from src.llm import MockProvider
from src.pipeline import collection_stats, get_or_create_collection, process_document, resolve_scope

PPT = "unzipped_starter/starter-datasets/delhivery/03-delhivery-q4-fy24-earnings-presentation.pdf"

needs_starter = pytest.mark.skipif(
    not Path(PPT).is_file(),
    reason="starter PDFs are local-only test data (git-ignored), not present in a fresh clone",
)


@needs_starter
def test_incremental_duplicate_reuse(tmp_path):
    conn = init_db(tmp_path / "t.db")
    c = get_or_create_collection(conn, "delhivery")
    assert get_or_create_collection(conn, "delhivery")["id"] == c["id"]
    canned = {"facts": [{
        "subject": "Delhivery", "predicate": "express_parcels", "value_raw": "740 Mn",
        "unit_raw": "parcels", "period_raw": "FY24", "scope": "", "qualifiers": {},
        "claim": "Shipped 740 Mn parcels in FY24.", "confidence": 0.9,
        "evidence_quote": "shipped 740 Mn parcels in FY24"}]}
    # Mock returns facts only when source contains the quote; patch via provider
    from src import extract as ex
    from src import pipeline as pl
    real = ex.extract_facts_from_text
    calls = {"n": 0}

    def fake(provider, text, page=0, max_facts=12):
        calls["n"] += 1
        if "shipped 740" in text:
            return real(MockProvider(canned=canned), text, page=page)
        return []

    ex.extract_facts_from_text = fake
    pl.extract_facts_from_text = fake
    try:
        # use a tiny fake PDF path? use real PPT but cap pages for speed
        r1 = process_document(conn, MockProvider(), c["id"], PPT, data_dir=tmp_path / "data",
                                max_pages=3, filename="q4-fy24-earnings.pdf")
        assert r1["document"]["filename"] == "q4-fy24-earnings.pdf"
        n_facts = len(list_facts(conn, c["id"], limit=100000))
        # capped run leaves pages unfinished → next call RESUMES them, not reuse
        r2 = process_document(conn, MockProvider(), c["id"], PPT, data_dir=tmp_path / "data", max_pages=3)
        assert r2["duplicate"] is False
        assert len(list_facts(conn, c["id"], limit=100000)) == n_facts  # mock adds nothing new
        # uncapped call resumes all remaining pages, then reuse is true
        r3 = process_document(conn, MockProvider(), c["id"], PPT, data_dir=tmp_path / "data")
        assert r3["duplicate"] is False  # resumes the rest
        r4 = process_document(conn, MockProvider(), c["id"], PPT, data_dir=tmp_path / "data")
        assert r4["duplicate"] is True
        assert len(list_facts(conn, c["id"], limit=100000)) == n_facts  # no rebuild
        assert resolve_scope(conn, c["id"], "current") == [c["id"]]
        assert resolve_scope(conn, c["id"], "selected", [c["id"]]) == [c["id"]]
        s = collection_stats(conn, c["id"])
        assert s["documents"] == 1
    finally:
        ex.extract_facts_from_text = real
        pl.extract_facts_from_text = real
    conn.close()


@needs_starter
def test_crash_mid_page_does_not_duplicate_facts(tmp_path):
    """Page with persisted facts but unfinished status (killed mid-relate) is skipped on resume."""
    from src.db import list_page_status, upsert_page_status
    from src import extract as ex
    from src import pipeline as pl

    conn = init_db(tmp_path / "t.db")
    c = get_or_create_collection(conn, "delhivery")
    canned = {"facts": [{
        "subject": "S", "predicate": "p", "value_raw": "1",
        "unit_raw": "", "period_raw": "", "scope": "", "qualifiers": {},
        "claim": "C.", "confidence": 0.9, "evidence_quote": "Earnings Presentation"}]}
    real = ex.extract_facts_from_text

    def fake2(provider, text, page=0, max_facts=12):
        return real(MockProvider(canned=canned), "Earnings Presentation " + text, page=page)

    ex.extract_facts_from_text = fake2
    pl.extract_facts_from_text = fake2
    try:
        r1 = process_document(conn, MockProvider(), c["id"], PPT, data_dir=tmp_path / "data", max_pages=1)
        assert r1["facts_added"] >= 1
        n = len(list_facts(conn, c["id"], limit=100000))
        doc_id = r1["document"]["id"]
        # simulate crash: facts persisted, status never flipped to processed
        upsert_page_status(conn, doc_id, 1, status="extracted", attempts=1, text_len=10, quality="good")
        r2 = process_document(conn, MockProvider(), c["id"], PPT, data_dir=tmp_path / "data", max_pages=1)
        assert len(list_facts(conn, c["id"], limit=100000)) == n
        assert [p for p in list_page_status(conn, doc_id) if p["page"] == 1][0]["status"] == "processed"
    finally:
        ex.extract_facts_from_text = real
        pl.extract_facts_from_text = real
    conn.close()
