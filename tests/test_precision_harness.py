"""Tests for evaluations/retrieval_precision.py — the relationship-engine scorer.

Two things are checked: the metric math (a known confusion matrix in, hand-computed
precision/recall/F1 out) and that `pair_decision` really tracks the production
decision path in src/relate.py rather than a drifting parallel implementation.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluations.retrieval_precision import (  # noqa: E402
    accuracy, confusion_matrix, deferral_stats, false_contradiction_rate, macro_average,
    main, observed_classes, pair_decision, per_class_metrics, score, subset_recall,
)
from src.db import create_collection, create_document, create_fact, init_db  # noqa: E402
from src.llm import MockProvider  # noqa: E402
from src.relate import relate_new_facts  # noqa: E402

# A tiny hand-built confusion:
#   CONTRADICTS  support 1, predicted 4, tp 1  -> P .25   R 1.00  F1 .40
#   CORROBORATES support 3, predicted 1, tp 1  -> P 1.0   R .333  F1 .50
#   UNRELATED    support 3, predicted 1, tp 1  -> P 1.0   R .333  F1 .50
#   RECONCILED   support 1, predicted 0, tp 0  -> P None  R 0     F1 None
#   LLM/SKIPPED  support 0, predicted 1 each   -> P 0     R None  F1 None
PAIRS = [
    ("CONTRADICTS", "CONTRADICTS"),
    ("UNRELATED", "CONTRADICTS"),
    ("UNRELATED", "CONTRADICTS"),
    ("RECONCILED", "CONTRADICTS"),
    ("CORROBORATES", "CORROBORATES"),
    ("CORROBORATES", "LLM"),
    ("CORROBORATES", "SKIPPED"),
    ("UNRELATED", "UNRELATED"),
]


def test_per_class_metrics_known_confusion():
    m = per_class_metrics(PAIRS)
    assert m["CONTRADICTS"] == {"support": 1, "predicted": 4, "tp": 1,
                                "precision": pytest.approx(0.25), "recall": pytest.approx(1.0),
                                "f1": pytest.approx(0.4)}
    assert m["CORROBORATES"]["precision"] == pytest.approx(1.0)
    assert m["CORROBORATES"]["recall"] == pytest.approx(1 / 3)
    assert m["CORROBORATES"]["f1"] == pytest.approx(0.5)
    assert m["UNRELATED"]["f1"] == pytest.approx(0.5)
    # never predicted: precision is undefined, recall is a real zero
    assert m["RECONCILED"]["precision"] is None and m["RECONCILED"]["recall"] == 0.0
    # system-only classes: gold can never contain them, so recall stays undefined
    assert m["LLM"]["precision"] == 0.0 and m["LLM"]["recall"] is None
    assert m["SKIPPED"]["support"] == 0 and m["SKIPPED"]["predicted"] == 1


def test_accuracy_macro_and_class_order():
    assert accuracy(PAIRS) == pytest.approx(3 / 8)
    macro = macro_average(per_class_metrics(PAIRS))
    assert macro["classes"] == 4  # only classes present in gold
    assert macro["precision"] == pytest.approx((0.25 + 1.0 + 1.0 + 0.0) / 4)
    assert macro["recall"] == pytest.approx((1.0 + 1 / 3 + 1 / 3 + 0.0) / 4)
    assert macro["f1"] == pytest.approx((0.4 + 0.5 + 0.5 + 0.0) / 4)
    assert accuracy([]) is None
    assert observed_classes(PAIRS) == ["CORROBORATES", "CONTRADICTS", "RECONCILED",
                                       "UNRELATED", "LLM", "SKIPPED"]


def test_confusion_matrix_counts_system_only_classes():
    cm = confusion_matrix(PAIRS)
    assert cm["UNRELATED"] == {"CONTRADICTS": 2, "UNRELATED": 1}
    assert cm["CORROBORATES"] == {"CORROBORATES": 1, "LLM": 1, "SKIPPED": 1}
    assert sum(sum(row.values()) for row in cm.values()) == len(PAIRS)


def test_false_contradiction_rate_and_deferral():
    fc = false_contradiction_rate(PAIRS)
    assert fc["predicted_contradicts"] == 4 and fc["false"] == 3
    assert fc["rate"] == pytest.approx(0.75)
    assert fc["gold_of_false"] == {"UNRELATED": 2, "RECONCILED": 1}
    assert false_contradiction_rate([("UNRELATED", "LLM")])["rate"] is None  # no division by zero

    d = deferral_stats(PAIRS)
    assert (d["llm"], d["skipped"]) == (1, 1)
    assert d["llm_rate"] == pytest.approx(1 / 8) and d["skipped_rate"] == pytest.approx(1 / 8)
    assert d["gold_of_llm"] == {"CORROBORATES": 1}


def test_missed_pair_recall_counts_links_and_exact_matches():
    rows = [
        {"source": "missed_pair", "gold": "CORROBORATES", "pred": "LLM"},
        {"source": "missed_pair", "gold": "CORROBORATES", "pred": "CORROBORATES"},
        {"source": "missed_pair", "gold": "TEMPORAL_CHANGE", "pred": "CONTRADICTS"},
        {"source": "missed_pair", "gold": "CORROBORATES", "pred": "SKIPPED"},
        {"source": "existing_rel", "gold": "UNRELATED", "pred": "CONTRADICTS"},
    ]
    mp = subset_recall(rows, "missed_pair")
    assert mp["total"] == 4
    assert mp["linked"] == 2 and mp["linked_rate"] == pytest.approx(0.5)  # any edge emitted
    assert mp["exact"] == 1 and mp["exact_rate"] == pytest.approx(0.25)   # right edge emitted
    assert mp["predicted_breakdown"] == {"LLM": 1, "CORROBORATES": 1, "CONTRADICTS": 1, "SKIPPED": 1}
    assert subset_recall(rows, "nobody")["linked_rate"] is None


def _seed(conn):
    c = create_collection(conn, "c1")
    d1 = create_document(conn, c["id"], "a.pdf", "h1")
    d2 = create_document(conn, c["id"], "b.pdf", "h2")
    return c, d1, d2


def test_pair_decision_matches_what_production_writes(tmp_path):
    """A pair production records as CONTRADICTS must score as CONTRADICTS."""
    conn = init_db(tmp_path / "t.db")
    c, d1, d2 = _seed(conn)
    a = create_fact(conn, c["id"], d1["id"], subject="Widget Co", predicate="units_sold",
                    claim="100", value_raw="100", value_norm=100.0, unit_norm="COUNT",
                    period_norm="FY24", scope="consolidated")
    b = create_fact(conn, c["id"], d2["id"], subject="Widget Co", predicate="units_sold",
                    claim="200", value_raw="200", value_norm=200.0, unit_norm="COUNT",
                    period_norm="FY24", scope="consolidated")
    rels = relate_new_facts(conn, MockProvider(), [b], [c["id"]])
    assert [r["type"] for r in rels] == ["CONTRADICTS"]
    assert pair_decision(b, a)[0] == "CONTRADICTS"
    conn.close()


def test_pair_decision_reports_skipped_where_production_writes_nothing(tmp_path):
    """Different predicates with neither value nor period agreeing never reach the judge."""
    conn = init_db(tmp_path / "t.db")
    c, d1, d2 = _seed(conn)
    a = create_fact(conn, c["id"], d1["id"], subject="Widget Co", predicate="alpha_count",
                    claim="5", value_raw="5", value_norm=5.0, unit_norm="COUNT")
    b = create_fact(conn, c["id"], d2["id"], subject="Widget Co", predicate="beta_count",
                    claim="9", value_raw="9", value_norm=9.0, unit_norm="COUNT")

    class NoLLM(MockProvider):
        def generate_json(self, prompt, system="", cache_key="", namespace=""):
            raise AssertionError("scorer/pipeline must not call the LLM here")

    assert relate_new_facts(conn, NoLLM(), [b], [c["id"]]) == []
    assert conn.execute("SELECT count(*) FROM relationships").fetchone()[0] == 0
    label, reason = pair_decision(b, a)
    assert label == "SKIPPED" and "admission gate" in reason
    conn.close()


def test_score_end_to_end_and_flags_bad_labels(tmp_path):
    conn = init_db(tmp_path / "t.db")
    c, d1, d2 = _seed(conn)
    a = create_fact(conn, c["id"], d1["id"], subject="Widget Co", predicate="units_sold",
                    claim="100", value_raw="100", value_norm=100.0, unit_norm="COUNT",
                    period_norm="FY24", scope="consolidated")
    b = create_fact(conn, c["id"], d2["id"], subject="Widget Co", predicate="units_sold",
                    claim="200", value_raw="200", value_norm=200.0, unit_norm="COUNT",
                    period_norm="FY24", scope="consolidated")
    labels = {"version": 1, "note": "fixture", "pairs": [
        {"a_id": a["id"], "b_id": b["id"], "gold": "UNRELATED", "why": "different line items",
         "source": "existing_rel", "cross_doc": True},
        {"a_id": a["id"], "b_id": "does-not-exist", "gold": "CORROBORATES",
         "source": "missed_pair", "cross_doc": False},
        {"a_id": a["id"], "b_id": b["id"], "gold": "NONSENSE", "source": "existing_rel"},
    ]}
    res = score(conn, labels)
    assert res["counts"] == {"labeled_rows": 3, "scored": 1, "unscored": 2,
                             "cross_doc": 1, "same_doc": 0, "order_sensitive": 0}
    assert res["rows"][0]["pred"] == "CONTRADICTS"
    assert res["false_contradiction_rate"]["rate"] == pytest.approx(1.0)
    assert res["rows"][0]["a_summary"].startswith("Widget Co | units_sold")
    assert len(res["issues"]) == 2  # unknown fact id + illegal gold label
    conn.close()


def test_missing_label_file_is_a_usage_error(tmp_path, capsys):
    rc = main(["--labels", str(tmp_path / "nope.json"), "--db", str(tmp_path / "t.db")])
    capsys.readouterr()
    assert rc == 2  # IO error exits non-zero; a bad score never does
