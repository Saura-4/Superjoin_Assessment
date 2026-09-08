"""TASK3 hybrid retrieval tests (offline — HashEmbedder, no API)."""
import pytest

from src.db import create_collection, create_document, create_fact, init_db, upsert_embedding
from src.embed import HashEmbedder, cosine, semantic_text
from src.evalset import select_eval_set
from src.relate import deterministic_decide
from src.retrieve import SemanticIndex, find_candidates, hybrid_retrieve, rerank_score


def _db(tmp_path):
    conn = init_db(tmp_path / "t.db")
    c = create_collection(conn, "c")
    d1 = create_document(conn, c["id"], "a.pdf", "h1")
    d2 = create_document(conn, c["id"], "b.pdf", "h2")
    return conn, c, d1, d2


def _fact(conn, c, d, subj="S", pred="p", claim="c", vraw="", vnorm=None,
          unorm="", praw="", pnorm="", scope=""):
    return create_fact(conn, c["id"], d["id"], subject=subj, predicate=pred, claim=claim,
                       value_raw=vraw, value_norm=vnorm, unit_norm=unorm,
                       period_raw=praw, period_norm=pnorm, scope=scope)


def test_01_semantic_text_no_primary_numbers():
    f = {"subject": "Delhivery Limited", "predicate": "revenue_from_services",
         "period_raw": "FY24", "scope": "consolidated", "claim": "Revenue was 8,142 Cr."}
    t = semantic_text(f)
    assert "Delhivery Limited" in t and "revenue from services" in t and "FY24" in t
    assert "8,142" not in t.split("Context:")[0]  # numbers not the primary signal


def test_02_embedding_generation_shapes():
    vecs = HashEmbedder().embed(["hello world", "hello world", "zzz qqq"])
    assert len(vecs) == 3 and all(len(v) == 256 for v in vecs)
    assert vecs[0] == vecs[1]  # deterministic


def test_03_cosine():
    assert cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine([], []) == 0.0


def test_04_lexical_retrieval(tmp_path):
    conn, c, d1, d2 = _db(tmp_path)
    _fact(conn, c, d1, subj="Delhivery", pred="revenue_from_services")
    probe = _fact(conn, c, d2, subj="Delhivery", pred="revenue")
    got = find_candidates(conn, {**probe, "collection_id": c["id"]}, [c["id"]])
    assert any(x["predicate"] == "revenue_from_services" for x in got)
    conn.close()


def _index_two_docs(tmp_path):
    conn, c, d1, d2 = _db(tmp_path)
    f1 = _fact(conn, c, d1, subj="Delhivery", pred="revenue_from_services",
               claim="c1", vnorm=1.0, unorm="INR", pnorm="FY24")
    f2 = _fact(conn, c, d2, subj="Delhivery", pred="operating_revenue",
               claim="c2", vnorm=1.0, unorm="INR", pnorm="FY24")
    idx = SemanticIndex({f1["id"]: [1.0, 0.0], f2["id"]: [0.9, 0.1]})
    return conn, c, d1, d2, f1, f2, idx


def test_05_semantic_retrieval(tmp_path):
    _, _, _, _, f1, f2, idx = _index_two_docs(tmp_path)
    hits = idx.search([1.0, 0.0], top_k=5, exclude_ids={f1["id"]})
    assert hits and hits[0][0] == f2["id"]


def test_05b_numpy_path_matches_python(tmp_path):
    np = pytest.importorskip("numpy")
    conn, c, d1, d2, f1, f2, idx = _index_two_docs(tmp_path)
    f3 = _fact(conn, c, d2, subj="Other", pred="zzz", claim="q")
    idx.vectors[f3["id"]] = [0.0, 1.0]
    hits = idx.search([1.0, 0.0], top_k=10)
    assert [h[0] for h in hits] == [f1["id"], f2["id"], f3["id"]]
    assert hits[0][1] == pytest.approx(1.0) and hits[-1][1] == pytest.approx(0.0)
    conn.close()


def test_06_union_07_dedupe_08_same_doc_exclusion(tmp_path):
    conn, c, d1, d2, f1, f2, idx = _index_two_docs(tmp_path)
    f3 = _fact(conn, c, d1, subj="Delhivery", pred="revenue", claim="c3")
    got = hybrid_retrieve(conn, {**f1, "collection_id": c["id"]}, idx, [1.0, 0.0],
                          exclude_same_doc=True, collection_ids=[c["id"]])
    ids = [x["id"] for x in got]
    assert f2["id"] in ids  # cross-doc kept
    assert f3["id"] not in ids and f1["id"] not in ids  # same-doc + self excluded
    assert len(ids) == len(set(ids))  # deduped
    conn.close()


def test_09_subject_mismatch_filtered_by_rerank():
    a = {"subject": "Kapil Bharati", "predicate": "cost", "value_norm": 35.0,
         "unit_norm": "INR", "period_norm": "FY24", "scope": ""}
    b = {"subject": "CA Swift Investments", "predicate": "cost", "value_norm": 139.0,
         "unit_norm": "INR", "period_norm": "FY24", "scope": ""}
    assert rerank_score(a, b) < 0.4  # below survival threshold


def test_10_different_predicate_retrieval(tmp_path):
    conn, c, d1, d2, f1, f2, idx = _index_two_docs(tmp_path)
    got = hybrid_retrieve(conn, {**f1, "collection_id": c["id"]}, idx, [1.0, 0.0],
                          exclude_same_doc=True, collection_ids=[c["id"]])
    assert any(x["predicate"] == "operating_revenue" for x in got)  # no shared token, found semantically
    conn.close()


def test_11_exact_value_corroboration_no_llm():
    a = {"subject": "Delhivery", "predicate": "revenue", "value_norm": 8142e7,
         "unit_norm": "INR", "period_norm": "FY24", "scope": "s", "qualifiers": {}}
    b = dict(a)
    d = deterministic_decide(a, b)
    assert d is not None and d["type"] == "CORROBORATES"


def test_12_temporal_no_llm():
    a = {"subject": "S", "predicate": "fee", "value_norm": 5.0,
         "unit_norm": "INR", "period_norm": "FY23", "scope": "", "qualifiers": {}}
    b = dict(a, period_norm="FY24", value_norm=8.0)
    d = deterministic_decide(a, b)
    assert d is not None and d["type"] == "TEMPORAL_CHANGE"


def test_13_contradiction_candidate():
    a = {"subject": "S", "predicate": "x", "value_norm": 100.0,
         "unit_norm": "INR", "period_norm": "FY24", "scope": "s", "qualifiers": {}}
    b = dict(a, value_norm=999.0)
    d = deterministic_decide(a, b)
    assert d is not None and d["type"] == "CONTRADICTS"


def test_14_ambiguous_would_call_llm_15_obvious_needs_none():
    amb_a = {"subject": "S", "predicate": "p", "value_norm": None,
             "unit_norm": "", "period_norm": "FY22", "scope": "", "qualifiers": {}}
    amb_b = dict(amb_a, period_norm="FY24")
    assert deterministic_decide(amb_a, amb_b) is None  # would reach LLM
    obv = {"subject": "S", "predicate": "p", "value_norm": 10.0,
           "unit_norm": "COUNT", "period_norm": "FY24", "scope": "", "qualifiers": {}}
    assert deterministic_decide(obv, dict(obv))["type"] == "CORROBORATES"  # no LLM needed


def test_evalset_stratified_and_deterministic(tmp_path):
    conn, c, d1, d2 = _db(tmp_path)
    for i in range(10):
        _fact(conn, c, d1, pred=f"m{i % 3}", claim=f"c{i}")
    got1 = select_eval_set(conn, [d1["id"]], per_doc=6)
    got2 = select_eval_set(conn, [d1["id"]], per_doc=6)
    assert [f["id"] for f in got1] == [f["id"] for f in got2]
    assert len({f["predicate"] for f in got1}) == 3  # spread, not one metric
    conn.close()


def test_embeddings_table_crud(tmp_path):
    conn = init_db(tmp_path / "t.db")
    c = create_collection(conn, "c")
    d = create_document(conn, c["id"], "a.pdf", "h1")
    f = _fact(conn, c, d)
    from src.db import count_embeddings, get_embedding, upsert_embedding
    upsert_embedding(conn, f["id"], "m", [0.1, 0.2], "th")
    assert count_embeddings(conn) == 1
    row = get_embedding(conn, f["id"])
    assert row["dim"] == 2 and row["model"] == "m"
    idx = SemanticIndex.from_db(conn, "m")
    assert len(idx) == 1
    conn.close()
