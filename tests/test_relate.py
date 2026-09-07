"""Tasks 7+8 tests: retrieval selectivity + deterministic relationships."""
from src.db import create_collection, create_document, create_fact, init_db
from src.llm import MockProvider
from src.relate import deterministic_decide, relate_pair, relate_new_fact, values_equal
from src.retrieve import find_candidates, predicate_compatible, subject_compatible


def _fact(**kw):
    base = {"id": "x", "collection_id": "c", "document_id": "d", "subject": "Delhivery",
            "predicate": "express_parcels", "value_raw": "", "value_norm": None,
            "unit_raw": "", "unit_norm": "COUNT", "period_raw": "", "period_norm": "",
            "scope": "", "qualifiers": "{}", "claim": "c", "confidence": 0.9}
    base.update(kw)
    return base


def test_subject_predicate_compat():
    assert subject_compatible("Delhivery", "Delhivery Limited")
    assert not subject_compatible("Delhivery", "Reserve Bank of India")
    assert predicate_compatible("revenue_from_services", "revenue_from_services")
    assert predicate_compatible("revenue", "revenue_from_services")
    assert not predicate_compatible("express_parcels", "repo_rate")


def test_values_equal_tol():
    assert values_equal(81_415_000_000.0, 81_420_000_000.0) is True  # rounding
    assert values_equal(100.0, 150.0) is False
    assert values_equal(None, 5.0) is None


def test_corrob_after_normalization():
    a = _fact(value_norm=81_415_000_000.0, unit_norm="INR", period_norm="FY24", scope="services")
    b = _fact(value_norm=81_420_000_000.0, unit_norm="INR", period_norm="FY24", scope="services")
    d = deterministic_decide(a, b)
    assert d["type"] == "CORROBORATES"


def test_contradiction_same_period_scope():
    a = _fact(value_norm=100.0, unit_norm="INR", period_norm="FY24", scope="s")
    b = _fact(value_norm=200.0, unit_norm="INR", period_norm="FY24", scope="s")
    assert deterministic_decide(a, b)["type"] == "CONTRADICTS"


def test_reconciled_scope_and_granularity():
    a = _fact(value_norm=8142e7, unit_norm="INR", period_norm="FY24", scope="services-only")
    b = _fact(value_norm=8360e7, unit_norm="INR", period_norm="FY24", scope="total")
    assert deterministic_decide(a, b)["type"] == "RECONCILED"
    q = _fact(value_norm=117e6, unit_norm="INR", period_norm="Q3-FY24", scope="")
    f = _fact(value_norm=-2491e6, unit_norm="INR", period_norm="FY24", scope="")
    assert deterministic_decide(q, f)["type"] == "RECONCILED"


def test_temporal_change():
    a = _fact(value_norm=100.0, unit_norm="COUNT", period_norm="FY22")
    b = _fact(value_norm=200.0, unit_norm="COUNT", period_norm="FY24")
    assert deterministic_decide(a, b)["type"] == "TEMPORAL_CHANGE"


def test_ambiguous_goes_to_llm_mock():
    a = _fact(value_norm=None, period_norm="FY22", scope="director X active")
    b = _fact(value_norm=None, period_norm="FY24", scope="director X ceased")
    out = relate_pair(MockProvider(), a, b, "X was appointed", "X ceased to be director")
    assert out["type"] == "UNCERTAIN"  # mock judge


def test_batch_judge_empty_and_mock_shape():
    from src.relate import llm_judge_batch
    assert llm_judge_batch(MockProvider(), []) == []
    a = _fact(value_norm=None, period_norm="FY22")
    b = _fact(value_norm=None, period_norm="FY24")
    out = llm_judge_batch(MockProvider(), [(a, "ev a", b, "ev b")] * 3)
    assert len(out) == 3 and all(d["type"] == "UNCERTAIN" for d in out)  # mock lacks decisions shape


def test_relate_new_facts_batches(tmp_path):
    from src.relate import relate_new_facts
    conn = init_db(tmp_path / "t.db")
    c1 = create_collection(conn, "c1")
    d1 = create_document(conn, c1["id"], "a.pdf", "h1")
    f1 = create_fact(conn, c1["id"], d1["id"], subject="S", predicate="p",
                     claim="c1", value_raw="10", value_norm=10.0, unit_norm="COUNT", period_norm="FY24")
    f2 = create_fact(conn, c1["id"], d1["id"], subject="S", predicate="p",
                     claim="c2", value_raw="10", value_norm=10.0, unit_norm="COUNT", period_norm="FY24")
    rels = relate_new_facts(conn, MockProvider(), [{**f2, "collection_id": c1["id"]}])
    assert any(r["type"] == "CORROBORATES" for r in rels)
    conn.close()


def test_relate_unlinked_facts_heals_and_idempotent(tmp_path):
    from src.relate import relate_unlinked_facts
    conn = init_db(tmp_path / "t.db")
    c1 = create_collection(conn, "c1")
    d1 = create_document(conn, c1["id"], "a.pdf", "h1")
    create_fact(conn, c1["id"], d1["id"], subject="S", predicate="p",
                claim="c1", value_raw="10", value_norm=10.0, unit_norm="COUNT", period_norm="FY24")
    create_fact(conn, c1["id"], d1["id"], subject="S", predicate="p",
                claim="c2", value_raw="10", value_norm=10.0, unit_norm="COUNT", period_norm="FY24")
    healed = relate_unlinked_facts(conn, MockProvider(), c1["id"], d1["id"], [c1["id"]])
    assert any(r["type"] == "CORROBORATES" for r in healed)
    assert relate_unlinked_facts(conn, MockProvider(), c1["id"], d1["id"], [c1["id"]]) == []
    conn.close()


def test_different_subjects_never_blind_contradiction():
    from src.relate import deterministic_decide
    a = _fact(subject="Kapil Bharati", predicate="cost", value_norm=35.0,
              unit_norm="INR", period_norm="FY24", scope="",
              qualifiers={})
    b = _fact(subject="CA Swift Investments", predicate="cost", value_norm=139.0,
              unit_norm="INR", period_norm="FY24", scope="",
              qualifiers={})
    assert deterministic_decide(a, b)["type"] == "UNRELATED"  # zero shared terms, different values


def test_differing_qualifiers_need_judgment():
    from src.relate import deterministic_decide
    a = _fact(subject="S", predicate="benefit", value_norm=98.0,
              unit_norm="INR", period_norm="", scope="",
              qualifiers={"condition": "ceases before 1yr"})
    b = _fact(subject="S", predicate="benefit", value_norm=49.0,
              unit_norm="INR", period_norm="", scope="",
              qualifiers={"condition": "ceases after 1yr"})
    assert deterministic_decide(a, b) is None


def test_retrieval_selective_and_scoped(tmp_path):
    conn = init_db(tmp_path / "t.db")
    c1 = create_collection(conn, "delhivery")
    c2 = create_collection(conn, "macro")
    d1 = create_document(conn, c1["id"], "a.pdf", "h1")
    d2 = create_document(conn, c1["id"], "b.pdf", "h2")
    d3 = create_document(conn, c2["id"], "m.pdf", "h3")
    f1 = create_fact(conn, c1["id"], d1["id"], subject="Delhivery", predicate="express_parcels",
                     claim="740m", value_raw="740 Mn", value_norm=740e6, unit_norm="COUNT", period_norm="FY24")
    f2 = create_fact(conn, c1["id"], d2["id"], subject="Delhivery", predicate="express_parcels",
                     claim="740m", value_raw="740M", value_norm=740e6, unit_norm="COUNT", period_norm="FY24")
    f3 = create_fact(conn, c2["id"], d3["id"], subject="India", predicate="gdp_growth",
                     claim="6.5%", value_norm=6.5, period_norm="FY24")
    got = find_candidates(conn, {**f1, "id": f1["id"], "collection_id": c1["id"]})
    ids = [c["id"] for c in got]
    assert f2["id"] in ids and f3["id"] not in ids  # default scope = current collection
    # explicit cross-collection allowed but still selective (predicate filter)
    gotx = find_candidates(conn, {**f1, "id": f1["id"], "collection_id": c1["id"]},
                           collection_ids=[c1["id"], c2["id"]])
    assert all(c["predicate"] == "express_parcels" for c in gotx)
    # relate persists CORROBORATES
    rels = relate_new_fact(conn, MockProvider(), {**f2, "collection_id": c1["id"]})
    assert any(r["type"] == "CORROBORATES" for r in rels)
    conn.close()
