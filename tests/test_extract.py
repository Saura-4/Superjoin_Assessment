"""Tasks 4+5 tests: validation, grounding, provenance traceability."""
from src.db import (
    create_collection,
    create_document,
    init_db,
    list_evidence_for_fact,
    list_facts,
)
from src.extract import (
    extract_facts_from_text,
    persist_facts_with_evidence,
    quote_grounded,
    validate_fact_dict,
)
from src.llm import MockProvider


def test_quote_grounded():
    src = "Express parcel shipment volume was 740 million in FY24."
    assert quote_grounded("shipment volume was 740 million", src)
    assert not quote_grounded("net profit doubled magically", src)
    assert not quote_grounded("", src)


def test_validate_drops_incomplete_and_penalizes_ungrounded():
    src = "Revenue from services was Rs 8,142 crore in FY24."
    good = validate_fact_dict({
        "subject": "Delhivery", "predicate": "revenue_from_services", "value_raw": "Rs 8,142 crore",
        "claim": "Revenue was Rs 8,142 crore in FY24.", "confidence": 0.9,
        "evidence_quote": "Revenue from services was Rs 8,142 crore"}, src)
    assert good is not None and good["confidence"] == 0.9
    bad = validate_fact_dict({
        "subject": "Delhivery", "predicate": "revenue_from_services",
        "claim": "Revenue doubled.", "confidence": 0.9,
        "evidence_quote": "totally invented quote xyz"}, src)
    assert bad is not None and bad["confidence"] < 0.6
    assert validate_fact_dict({"subject": "", "predicate": "x", "claim": "y",
                               "evidence_quote": "z"}, src) is None


def test_extract_with_mock_and_provenance(tmp_path):
    canned = {"facts": [{
        "subject": "Delhivery", "predicate": "express_parcels", "value_raw": "740 Mn",
        "unit_raw": "parcels", "period_raw": "FY24", "scope": "annual",
        "qualifiers": {}, "claim": "Delhivery shipped 740 Mn parcels in FY24.",
        "confidence": 0.9, "evidence_quote": "shipped 740 Mn parcels in FY24"}]}
    src_text = "In FY24 Delhivery shipped 740 Mn parcels in FY24 with growth."
    facts = extract_facts_from_text(MockProvider(canned=canned), src_text, page=10)
    assert len(facts) == 1
    assert facts[0]["predicate"] == "express_parcels"
    assert facts[0]["value_norm"] == 740_000_000.0  # normalized
    assert facts[0]["period_norm"] == "FY24"

    conn = init_db(tmp_path / "t.db")
    c = create_collection(conn, "delhivery")
    d = create_document(conn, c["id"], "annual.pdf", "h1")
    rows = persist_facts_with_evidence(conn, c["id"], d["id"], 10, facts)
    assert len(rows) == 1
    # provenance: fact → evidence → document/page
    ev = list_evidence_for_fact(conn, rows[0]["id"])
    assert len(ev) == 1 and ev[0]["document_id"] == d["id"] and ev[0]["page"] == 10
    assert "740 Mn" in ev[0]["text"]
    assert len(list_facts(conn, c["id"])) == 1
    conn.close()


def test_malformed_llm_response_yields_empty():
    class Bad(MockProvider):
        def generate_json(self, prompt, system="", cache_key=""):
            return {"unexpected": "shape"}
    assert extract_facts_from_text(Bad(), "x" * 200, page=1) == []

    class Exploding(MockProvider):
        def generate_json(self, prompt, system="", cache_key=""):
            from src.llm import LLMError
            raise LLMError("boom")
    assert extract_facts_from_text(Exploding(), "y" * 200, page=1) == []
    assert extract_facts_from_text(MockProvider(), "tiny", page=1) == []
