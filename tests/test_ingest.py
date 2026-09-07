"""Task 2 tests: page numbering, quality, duplicates, malformed handling."""
import tempfile
from pathlib import Path

import pytest

from src.db import create_collection, get_document_by_hash, init_db, list_page_status
from src.ingest import extract_pages, ingest_pdf, quality_for_text

DELHIVERY = Path("unzipped_starter/starter-datasets/delhivery")
PPT = DELHIVERY / "03-delhivery-q4-fy24-earnings-presentation.pdf"
PROSPECTUS = DELHIVERY / "01-delhivery-prospectus-2022-excerpt.pdf"


def _tmpdb(tmp_path):
    return init_db(tmp_path / "t.db")


def test_page_numbering_and_quality_counts():
    pages = extract_pages(PROSPECTUS)
    assert len(pages) == 100
    assert pages[0]["page"] == 1 and pages[-1]["page"] == 100
    assert quality_for_text(pages[0]["text"]) in ("good", "low")


def test_low_text_detection_chart_pdf():
    pages = extract_pages(PPT)
    assert len(pages) == 27
    quals = [quality_for_text(p["text"]) for p in pages]
    # earnings deck is visual-heavy: at least one low/empty page expected
    assert "low" in quals or "empty" in quals


def test_quality_thresholds():
    assert quality_for_text("") == "empty"
    assert quality_for_text("   ") == "empty"
    assert quality_for_text("hello") == "empty"
    assert quality_for_text("x " * 200) == "good"


def test_ingest_duplicate_and_pages(tmp_path):
    conn = _tmpdb(tmp_path)
    c = create_collection(conn, "delhivery")
    r1 = ingest_pdf(conn, c["id"], PPT, data_dir=tmp_path / "data")
    assert r1["duplicate"] is False
    assert r1["document"]["num_pages"] == 27
    assert len(list_page_status(conn, r1["document"]["id"])) == 27
    r2 = ingest_pdf(conn, c["id"], PPT, data_dir=tmp_path / "data")
    assert r2["duplicate"] is True
    assert r2["document"]["id"] == r1["document"]["id"]
    conn.close()


def test_malformed_pdf(tmp_path):
    conn = _tmpdb(tmp_path)
    c = create_collection(conn, "c")
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.4 not a real pdf %%%%")
    with pytest.raises(Exception):
        ingest_pdf(conn, c["id"], bad, data_dir=tmp_path / "data")
    row = get_document_by_hash(conn, c["id"], __import__("src.ingest", fromlist=["sha256_of_file"]).sha256_of_file(bad))
    assert row is None or row["status"] in ("failed", "processing")
    conn.close()
