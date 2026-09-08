"""Relationship-engine scorer: grade production's decisions against hand labels.

Reads `evaluations/relationship_labels.json` (hand-labeled ground truth, owned by
the labeling pass — never imported by `src/`), replays each labeled pair through
**the same decision path production uses**, and reports precision / recall / F1,
a confusion matrix, LLM-deferral and drop rates, the headline false-contradiction
rate, and recall on pairs that should link but currently do not.

Measurement only:
  * opens the DB read-only (`mode=ro`) — it cannot write, so no backup is needed;
  * makes ZERO network / LLM calls (pairs the pipeline would send to the judge are
    reported as the predicted class `LLM`, never actually judged);
  * deterministic — same DB + same labels => identical output;
  * exits non-zero ONLY on usage/IO errors. A terrible score still exits 0:
    this is a thermometer, not a gate.

Usage:
    python evaluations/retrieval_precision.py
    python evaluations/retrieval_precision.py --db data/run_delhivery.db \
        --labels evaluations/relationship_labels.json
    python evaluations/retrieval_precision.py --json                 # JSON to stdout
    python evaluations/retrieval_precision.py --json out/base.json   # table + file
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.relate import deterministic_decide, values_equal  # noqa: E402
from src.retrieve import find_candidates, predicate_compatible, subject_compatible  # noqa: E402

# ---------------------------------------------------------------------------
# Decision path
# ---------------------------------------------------------------------------
# This scorer must always measure PRODUCTION's real path, never a parallel
# reimplementation that quietly drifts from src/relate.py.
#
# Today the per-pair decision is spread across two places inside
# `relate_new_facts`: (1) an inlined admission gate for different-predicate
# pairs ("same_val or same_per"), and (2) `deterministic_decide`, whose None
# return means "ambiguous" -> dropped when same-document, else sent to the LLM
# judge. There is no single production function to call, so `_replicated_path`
# below mirrors those inline gates line-for-line.
#
# A planned refactor lifts that logic into `src.relate.classify_pair`. The moment
# that symbol exists this scorer switches to it automatically and stops using the
# replica — so the baseline recorded today stays comparable with numbers measured
# after the refactor, and the replica can then be deleted rather than maintained.
try:  # pragma: no cover - only one branch exists at any given commit
    from src.relate import classify_pair as _CLASSIFY_PAIR  # type: ignore[attr-defined]
except ImportError:
    _CLASSIFY_PAIR = None

DECISION_PATH = ("src.relate.classify_pair" if _CLASSIFY_PAIR is not None
                 else "replicated:relate_new_facts gates + deterministic_decide")

# Classes a human label may carry.
GOLD_CLASSES = ("CORROBORATES", "CONTRADICTS", "RECONCILED", "TEMPORAL_CHANGE", "UNRELATED")
# Classes the system may output that a human never assigns:
#   LLM       - deterministic layer abstained; the pipeline pays for a judge call.
#   SKIPPED   - pair dropped before any judging (admission gate or same-doc rule);
#               no relationship row can ever be written for it.
#   UNCERTAIN - only reachable through an LLM verdict (or a future classify_pair).
SYSTEM_ONLY_CLASSES = ("UNCERTAIN", "LLM", "SKIPPED")
PRED_CLASSES = GOLD_CLASSES + SYSTEM_ONLY_CLASSES
# Classes that put an edge in the graph (a "link").
LINK_CLASSES = ("CORROBORATES", "CONTRADICTS", "RECONCILED", "TEMPORAL_CHANGE")


def pair_decision(a: dict[str, Any], b: dict[str, Any]) -> tuple[str, str]:
    """Return (predicted_class, reason) for one fact pair, exactly as production decides it.

    predicted_class is one of CORROBORATES / CONTRADICTS / RECONCILED /
    TEMPORAL_CHANGE / UNRELATED / SKIPPED / LLM (UNCERTAIN only if a future
    classify_pair emits it). Argument order follows the caller's (a, b), the same
    way `relate_new_facts` calls with (new_fact, candidate).
    """
    if _CLASSIFY_PAIR is not None:
        return _from_classify_pair(_CLASSIFY_PAIR(a, b))
    return _replicated_path(a, b)


def _from_classify_pair(result: Any) -> tuple[str, str]:
    """Adapt whatever shape the future `classify_pair` returns.

    Accepts a (type, reason) tuple, a decision dict shaped like
    `deterministic_decide`'s, a bare string, or None (None == "no deterministic
    answer", i.e. the pipeline would pay for an LLM judge call).
    """
    if result is None:
        return "LLM", "classify_pair abstained; pair would go to the LLM judge"
    if isinstance(result, dict):
        return str(result.get("type", "UNCERTAIN")).upper(), str(result.get("reason", ""))
    if isinstance(result, str):
        return result.upper(), ""
    if isinstance(result, (tuple, list)) and result:
        label = str(result[0]).upper()
        reason = str(result[1]) if len(result) > 1 and result[1] is not None else ""
        return label, reason
    return "UNCERTAIN", f"unrecognized classify_pair return: {type(result).__name__}"


def _replicated_path(a: dict[str, Any], b: dict[str, Any]) -> tuple[str, str]:
    """Mirror of the per-pair gates inlined in src/relate.py::relate_new_facts.

    Keep in lockstep with relate_new_facts until `classify_pair` lands; after
    that this is dead code and should be deleted, not maintained.
    """
    # Gate 1 (relate_new_facts): different predicate names only reach the judge
    # when the numbers or the period already agree.
    if a.get("predicate") != b.get("predicate"):
        va, vb = a.get("value_norm"), b.get("value_norm")
        pa, pb = a.get("period_norm") or "", b.get("period_norm") or ""
        same_val = values_equal(va, vb) is True if va is not None and vb is not None else False
        same_per = bool(pa and pb and pa == pb)
        if not (same_val or same_per):
            return ("SKIPPED",
                    "different predicates and neither value nor period agrees: "
                    "dropped by the diff-predicate admission gate")

    # Gate 2: the deterministic layer itself.
    dec = deterministic_decide(a, b)
    if dec is None:
        # Gate 3 (relate_new_facts): same-document ambiguity is dropped outright
        # (no LLM call, no row); only cross-document ambiguity is judged.
        if a.get("document_id") == b.get("document_id"):
            return ("SKIPPED",
                    "deterministic layer abstained and both facts are in one document: "
                    "dropped without judging")
        return ("LLM",
                "deterministic layer abstained on a cross-document pair: sent to the LLM judge")

    rel = str(dec.get("type", "UNCERTAIN")).upper()
    reason = str(dec.get("reason", ""))
    if rel == "UNRELATED":
        # Deterministic UNRELATED is a real decision, but it writes no row.
        reason = reason or "deterministic UNRELATED; no relationship row written"
    return rel, reason


# ---------------------------------------------------------------------------
# Metric math (pure functions over (gold, predicted) pairs — unit-tested)
# ---------------------------------------------------------------------------

def confusion_matrix(pairs: list[tuple[str, str]]) -> dict[str, dict[str, int]]:
    """gold -> predicted -> count. SKIPPED / LLM appear as predicted classes."""
    cm: dict[str, Counter] = defaultdict(Counter)
    for gold, pred in pairs:
        cm[gold][pred] += 1
    return {g: dict(c) for g, c in cm.items()}


def observed_classes(pairs: list[tuple[str, str]]) -> list[str]:
    """Canonical class order: known classes first, then anything unexpected."""
    seen = {g for g, _ in pairs} | {p for _, p in pairs}
    ordered = [c for c in PRED_CLASSES if c in seen]
    ordered += sorted(c for c in seen if c not in PRED_CLASSES)
    return ordered


def per_class_metrics(pairs: list[tuple[str, str]],
                      classes: Optional[list[str]] = None) -> dict[str, dict[str, Any]]:
    """Per-class precision / recall / F1 / support.

    support   = number of pairs whose GOLD label is this class
    predicted = number of pairs the system assigned this class
    tp        = both agree on this class
    precision = tp / predicted  (None when the system never predicted it)
    recall    = tp / support    (None when gold never contains it)
    f1        = harmonic mean   (None when either side is undefined)
    """
    classes = classes if classes is not None else observed_classes(pairs)
    out: dict[str, dict[str, Any]] = {}
    for c in classes:
        support = sum(1 for g, _ in pairs if g == c)
        predicted = sum(1 for _, p in pairs if p == c)
        tp = sum(1 for g, p in pairs if g == c and p == c)
        precision = (tp / predicted) if predicted else None
        recall = (tp / support) if support else None
        if precision is None or recall is None:
            f1 = None
        elif precision + recall == 0:
            f1 = 0.0
        else:
            f1 = 2 * precision * recall / (precision + recall)
        out[c] = {"support": support, "predicted": predicted, "tp": tp,
                  "precision": precision, "recall": recall, "f1": f1}
    return out


def macro_average(metrics: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Macro mean over classes present in gold; undefined (0-denominator) counts as 0.0."""
    cls = [c for c, m in metrics.items() if m["support"] > 0]
    if not cls:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0, "classes": 0}

    def mean(key: str) -> float:
        return sum((metrics[c][key] or 0.0) for c in cls) / len(cls)

    return {"precision": mean("precision"), "recall": mean("recall"),
            "f1": mean("f1"), "classes": len(cls)}


def accuracy(pairs: list[tuple[str, str]]) -> Optional[float]:
    return (sum(1 for g, p in pairs if g == p) / len(pairs)) if pairs else None


def false_contradiction_rate(pairs: list[tuple[str, str]]) -> dict[str, Any]:
    """Headline metric: of pairs predicted CONTRADICTS, the fraction gold disagrees with."""
    predicted = [(g, p) for g, p in pairs if p == "CONTRADICTS"]
    wrong = [(g, p) for g, p in predicted if g != "CONTRADICTS"]
    return {"predicted_contradicts": len(predicted), "false": len(wrong),
            "rate": (len(wrong) / len(predicted)) if predicted else None,
            "gold_of_false": dict(Counter(g for g, _ in wrong))}


def deferral_stats(pairs: list[tuple[str, str]]) -> dict[str, Any]:
    """How many labeled pairs the pipeline punts to the LLM, and how many it drops."""
    n = len(pairs)
    llm = sum(1 for _, p in pairs if p == "LLM")
    skipped = sum(1 for _, p in pairs if p == "SKIPPED")
    return {"total": n,
            "llm": llm, "llm_rate": (llm / n) if n else None,
            "skipped": skipped, "skipped_rate": (skipped / n) if n else None,
            "gold_of_llm": dict(Counter(g for g, p in pairs if p == "LLM")),
            "gold_of_skipped": dict(Counter(g for g, p in pairs if p == "SKIPPED"))}


def subset_recall(rows: list[dict[str, Any]], source: str) -> dict[str, Any]:
    """Recall restricted to one label `source` bucket.

    linked = the system emitted some edge (one of LINK_CLASSES);
    exact  = the system emitted exactly the gold class.
    For source="missed_pair" (pairs that SHOULD link but have no row today),
    `linked_rate` is the recall number that matters.
    """
    sub = [r for r in rows if r.get("source") == source]
    n = len(sub)
    linked = sum(1 for r in sub if r["pred"] in LINK_CLASSES)
    exact = sum(1 for r in sub if r["pred"] == r["gold"])
    gold_linkable = [r for r in sub if r["gold"] in LINK_CLASSES]
    linked_of_linkable = sum(1 for r in gold_linkable if r["pred"] in LINK_CLASSES)
    return {"total": n,
            "linked": linked, "linked_rate": (linked / n) if n else None,
            "exact": exact, "exact_rate": (exact / n) if n else None,
            "gold_linkable": len(gold_linkable),
            "linked_of_linkable": linked_of_linkable,
            "linked_of_linkable_rate": ((linked_of_linkable / len(gold_linkable))
                                        if gold_linkable else None),
            "predicted_breakdown": dict(Counter(r["pred"] for r in sub))}


# ---------------------------------------------------------------------------
# Retrieval reachability diagnostic (why a missed_pair was missed)
# ---------------------------------------------------------------------------

def _passes_lexical_filter(fact: dict[str, Any], cand: dict[str, Any]) -> bool:
    """The filter predicate inside src/retrieve.py::find_candidates, before the top-K cut."""
    return bool(
        predicate_compatible(fact.get("predicate", ""), cand.get("predicate", ""))
        or (subject_compatible(fact.get("subject", ""), cand.get("subject", ""))
            and fact.get("unit_norm") and fact.get("unit_norm") == cand.get("unit_norm")))


def retrieval_status(conn: sqlite3.Connection, a: dict[str, Any], b: dict[str, Any],
                     pool_cache: dict[str, list[dict[str, Any]]], limit: int = 20) -> str:
    """Would production's candidate retrieval ever put this pair in front of the judge?

    'retrieved'          - b is in a's candidate list (or vice versa)
    'truncated_by_limit' - passes the lexical filter but falls outside top-K
    'not_retrieved'      - fails the lexical filter in both directions
    'cross_collection'   - different collections; never compared by design
    """
    if a.get("collection_id") != b.get("collection_id"):
        return "cross_collection"
    cid = a["collection_id"]
    if cid not in pool_cache:
        pool_cache[cid] = [dict(r) for r in conn.execute(
            "SELECT * FROM facts WHERE collection_id = ?", (cid,)).fetchall()]
    pool = pool_cache[cid]
    if any(c["id"] == b["id"] for c in find_candidates(conn, a, None, limit=limit, pool=pool)):
        return "retrieved"
    if any(c["id"] == a["id"] for c in find_candidates(conn, b, None, limit=limit, pool=pool)):
        return "retrieved"
    if _passes_lexical_filter(a, b) or _passes_lexical_filter(b, a):
        return "truncated_by_limit"
    return "not_retrieved"


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

class UsageError(Exception):
    """Bad arguments / missing or malformed input files (exit code 2)."""


def open_db_readonly(db_path: str) -> sqlite3.Connection:
    p = Path(db_path)
    if not p.is_file():
        raise UsageError(f"database not found: {p}\n"
                         f"       pass --db <path to the run database>")
    uri = "file:" + p.resolve().as_posix().replace("?", "%3f").replace("#", "%23") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def load_labels(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        raise UsageError(
            f"ground-truth label file not found: {p}\n"
            f"       This scorer grades the relationship engine against hand-labeled pairs.\n"
            f"       Expected schema: {{\"version\": 1, \"note\": \"...\", \"pairs\": [\n"
            f"         {{\"a_id\": <facts.id>, \"b_id\": <facts.id>, \"gold\": CORROBORATES|\n"
            f"           CONTRADICTS|RECONCILED|TEMPORAL_CHANGE|UNRELATED, \"why\": ...,\n"
            f"           \"a_summary\": ..., \"b_summary\": ...,\n"
            f"           \"source\": existing_rel|missed_pair, \"cross_doc\": true|false}} ]}}\n"
            f"       Point --labels at an existing file to score a different label set.")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UsageError(f"could not read label file {p}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("pairs"), list):
        raise UsageError(f"label file {p} must be a JSON object with a \"pairs\" list")
    return data


def load_facts(conn: sqlite3.Connection, ids: set[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    id_list = list(ids)
    for i in range(0, len(id_list), 400):
        chunk = id_list[i:i + 400]
        ph = ",".join("?" for _ in chunk)
        for r in conn.execute(f"SELECT * FROM facts WHERE id IN ({ph})", tuple(chunk)).fetchall():
            out[r["id"]] = dict(r)
    return out


def load_stored_types(conn: sqlite3.Connection) -> dict[tuple[str, str], str]:
    """Existing relationships rows keyed by unordered fact pair (the DB stores them canonically)."""
    return {tuple(sorted((r["fact_a_id"], r["fact_b_id"]))): r["type"]
            for r in conn.execute("SELECT fact_a_id, fact_b_id, type FROM relationships").fetchall()}


def summarize(f: dict[str, Any]) -> str:
    """Fallback summary in the label file's shape: subject | predicate | value unit | period | scope."""
    return " | ".join([str(f.get("subject", ""))[:40], str(f.get("predicate", ""))[:34],
                       f"{f.get('value_raw', '')} {f.get('unit_raw', '')}".strip()[:24],
                       str(f.get("period_norm", "")) or "-", str(f.get("scope", "")) or "-"])


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score(conn: sqlite3.Connection, labels: dict[str, Any],
          check_retrieval: bool = True) -> dict[str, Any]:
    """Replay every labeled pair through pair_decision and compute all metrics."""
    issues: list[str] = []
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    raw_pairs = labels.get("pairs", [])
    wanted: set[str] = set()
    for entry in raw_pairs:
        if isinstance(entry, dict):
            wanted.add(str(entry.get("a_id", "")))
            wanted.add(str(entry.get("b_id", "")))
    facts = load_facts(conn, {i for i in wanted if i})
    stored = load_stored_types(conn)
    pool_cache: dict[str, list[dict[str, Any]]] = {}

    for n, entry in enumerate(raw_pairs):
        if not isinstance(entry, dict):
            issues.append(f"pairs[{n}]: not an object; skipped")
            continue
        a_id, b_id = str(entry.get("a_id", "")), str(entry.get("b_id", ""))
        gold = str(entry.get("gold", "")).upper()
        if not a_id or not b_id:
            issues.append(f"pairs[{n}]: missing a_id/b_id; skipped")
            continue
        if a_id == b_id:
            issues.append(f"pairs[{n}]: a_id == b_id ({a_id}); skipped")
            continue
        if gold not in GOLD_CLASSES:
            issues.append(f"pairs[{n}]: gold '{entry.get('gold')}' is not one of "
                          f"{'/'.join(GOLD_CLASSES)}; skipped")
            continue
        key = tuple(sorted((a_id, b_id)))
        if key in seen:
            issues.append(f"pairs[{n}]: duplicate pair {a_id}/{b_id}; first occurrence kept")
            continue
        seen.add(key)
        a, b = facts.get(a_id), facts.get(b_id)
        missing = [i for i, f in ((a_id, a), (b_id, b)) if f is None]
        if missing:
            issues.append(f"pairs[{n}]: fact id(s) not in this database: {', '.join(missing)}; skipped")
            continue

        pred, reason = pair_decision(a, b)
        rev_pred, _ = pair_decision(b, a)
        source = str(entry.get("source", "")) or "unspecified"
        db_cross_doc = a.get("document_id") != b.get("document_id")
        if "cross_doc" in entry and bool(entry["cross_doc"]) != db_cross_doc:
            issues.append(f"pairs[{n}]: label says cross_doc={entry['cross_doc']} but the DB says "
                          f"{db_cross_doc}; the DB value is used")
        rows.append({
            "a_id": a_id, "b_id": b_id, "gold": gold, "pred": pred, "reason": reason,
            "source": source, "cross_doc": db_cross_doc,
            "why": str(entry.get("why", "")),
            "a_summary": str(entry.get("a_summary") or summarize(a)),
            "b_summary": str(entry.get("b_summary") or summarize(b)),
            "stored_type": stored.get(key),
            "order_sensitive": pred != rev_pred,
            "retrieval": retrieval_status(conn, a, b, pool_cache) if check_retrieval else None,
        })

    gp = [(r["gold"], r["pred"]) for r in rows]
    classes = observed_classes(gp)
    metrics = per_class_metrics(gp, classes)
    by_source = {s: subset_recall(rows, s) for s in sorted({r["source"] for r in rows})}

    # Secondary view: what the DB actually shipped for these pairs — deterministic
    # decisions AND the LLM verdicts recorded during the real run, graded vs gold.
    stored_rows = [r for r in rows if r["stored_type"] is not None]
    stored_gp = [(r["gold"], str(r["stored_type"]).upper()) for r in stored_rows]

    return {
        "decision_path": DECISION_PATH,
        "labels_version": labels.get("version"),
        "labels_note": labels.get("note", ""),
        "counts": {"labeled_rows": len(raw_pairs), "scored": len(rows),
                   "unscored": len(raw_pairs) - len(rows),
                   "cross_doc": sum(1 for r in rows if r["cross_doc"]),
                   "same_doc": sum(1 for r in rows if not r["cross_doc"]),
                   "order_sensitive": sum(1 for r in rows if r["order_sensitive"])},
        "accuracy": accuracy(gp),
        "per_class": metrics,
        "macro": macro_average(metrics),
        "confusion": confusion_matrix(gp),
        "classes": classes,
        "deferral": deferral_stats(gp),
        "false_contradiction_rate": false_contradiction_rate(gp),
        "by_source": by_source,
        "missed_pair_recall": by_source.get("missed_pair", subset_recall(rows, "missed_pair")),
        "stored_relationships": {
            "graded_rows": len(stored_rows),
            "exact": sum(1 for g, p in stored_gp if g == p),
            "agreement": ((sum(1 for g, p in stored_gp if g == p) / len(stored_gp))
                          if stored_gp else None),
            "confusion": confusion_matrix(stored_gp),
            "false_contradiction_rate": false_contradiction_rate(stored_gp),
        },
        "retrieval": dict(Counter(r["retrieval"] for r in rows if r["retrieval"] is not None)),
        "issues": issues,
        "rows": rows,
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _pct(x: Optional[float]) -> str:
    return "  n/a" if x is None else f"{100 * x:5.1f}%"


def _line(width: int = 78) -> str:
    return "-" * width


def render(res: dict[str, Any], db: str, labels_path: str, show: int = 8) -> str:
    out: list[str] = []
    w = out.append
    c = res["counts"]
    w("=" * 78)
    w("RELATIONSHIP ENGINE - PRECISION / RECALL vs HAND LABELS")
    w("=" * 78)
    w(f"db            : {db}")
    w(f"labels        : {labels_path} (version {res['labels_version']})")
    w(f"decision path : {res['decision_path']}")
    w(f"pairs         : {c['scored']} scored / {c['labeled_rows']} labeled"
      f"   (cross-doc {c['cross_doc']}, same-doc {c['same_doc']})")
    w(f"exact-match   : {_pct(res['accuracy'])}   macro-F1 {_pct(res['macro']['f1'])}"
      f"   (macro P {_pct(res['macro']['precision'])} / R {_pct(res['macro']['recall'])})")
    w("")

    w("PER-CLASS (gold vs system decision)")
    w(_line())
    w(f"{'class':<16}{'support':>8}{'pred':>7}{'tp':>5}{'precision':>11}{'recall':>9}{'F1':>9}")
    w(_line())
    for cls in res["classes"]:
        m = res["per_class"][cls]
        w(f"{cls:<16}{m['support']:>8}{m['predicted']:>7}{m['tp']:>5}"
          f"{_pct(m['precision']):>11}{_pct(m['recall']):>9}{_pct(m['f1']):>9}")
    w(_line())
    w("support = gold count; pred = times the system said it; SKIPPED/LLM are system-only")
    w("")

    cols = res["classes"]
    head = f"{'gold \\ pred':<16}" + "".join(f"{col[:9]:>10}" for col in cols) + f"{'total':>8}"
    w("CONFUSION MATRIX  (rows = gold, columns = predicted)")
    w(_line(len(head)))
    w(head)
    w(_line(len(head)))
    for g in [x for x in cols if res["per_class"][x]["support"] > 0]:
        rowd = res["confusion"].get(g, {})
        cells = "".join(f"{rowd.get(col, 0):>10}" for col in cols)
        w(f"{g:<16}{cells}{sum(rowd.values()):>8}")
    w(_line(len(head)))
    w("")

    d = res["deferral"]
    w("PIPELINE DISPOSITION")
    w(_line())
    w(f"deferred to LLM      : {d['llm']:>4} / {d['total']}  ({_pct(d['llm_rate'])})"
      f"   gold: {d['gold_of_llm'] or '-'}")
    w(f"dropped before judge : {d['skipped']:>4} / {d['total']}  ({_pct(d['skipped_rate'])})"
      f"   gold: {d['gold_of_skipped'] or '-'}")
    f = res["false_contradiction_rate"]
    w(f"FALSE CONTRADICTION RATE : {f['false']}/{f['predicted_contradicts']} predicted CONTRADICTS "
      f"are wrong = {_pct(f['rate'])}")
    if f["gold_of_false"]:
        w(f"    their true labels    : {f['gold_of_false']}")
    w("")

    mp = res["missed_pair_recall"]
    w("RECALL ON source=\"missed_pair\"  (pairs that should link but have no row today)")
    w(_line())
    w(f"labeled : {mp['total']}   system links it: {mp['linked']} ({_pct(mp['linked_rate'])})"
      f"   exact gold class: {mp['exact']} ({_pct(mp['exact_rate'])})")
    w(f"system decisions: {mp['predicted_breakdown'] or '-'}")
    w("")

    if res["by_source"]:
        w("BY LABEL SOURCE")
        w(_line())
        for src, s in res["by_source"].items():
            w(f"{src:<14} n={s['total']:<4} exact {s['exact']:>3} ({_pct(s['exact_rate'])})"
              f"   linked {s['linked']:>3} ({_pct(s['linked_rate'])})")
        w("")

    st = res["stored_relationships"]
    if st["graded_rows"]:
        w("WHAT THE DATABASE ACTUALLY SHIPPED  (recorded rows incl. the run's LLM verdicts)")
        w(_line())
        w(f"labeled pairs with a relationships row : {st['graded_rows']}")
        w(f"stored type == gold                    : {st['exact']} ({_pct(st['agreement'])})")
        sf = st["false_contradiction_rate"]
        w(f"stored false-contradiction rate        : {sf['false']}/{sf['predicted_contradicts']} "
          f"({_pct(sf['rate'])})")
        w("")

    if res["retrieval"]:
        w("CANDIDATE RETRIEVAL REACHABILITY  (would find_candidates ever surface the pair?)")
        w(_line())
        for k, v in sorted(res["retrieval"].items()):
            w(f"  {k:<20} {v}")
        w("")

    wrong = [r for r in res["rows"] if r["gold"] != r["pred"]]
    if wrong and show:
        w(f"MISMATCHES (showing {min(show, len(wrong))} of {len(wrong)})")
        w(_line())
        for r in wrong[:show]:
            w(f"gold {r['gold']:<15} -> system {r['pred']:<10} [{r['source']}"
              f"{', cross-doc' if r['cross_doc'] else ''}]")
            w(f"    A: {r['a_summary']}")
            w(f"    B: {r['b_summary']}")
            if r["why"]:
                w(f"    why gold  : {r['why'][:150]}")
            if r["reason"]:
                w(f"    why system: {r['reason'][:150]}")
            w("")

    if res["issues"]:
        w(f"LABEL-FILE ISSUES ({len(res['issues'])}) - excluded from the numbers above")
        w(_line())
        for msg in res["issues"][:15]:
            w(f"  ! {msg}")
        if len(res["issues"]) > 15:
            w(f"  ... {len(res['issues']) - 15} more")
        w("")
    if c["order_sensitive"]:
        w(f"NOTE: {c['order_sensitive']} pair(s) decide differently when (a, b) is swapped.")
    w("measurement only: no writes, no LLM calls; a bad score still exits 0.")
    return "\n".join(out)


def _json_payload(res: dict[str, Any], db: str, labels_path: str, keep_rows: bool) -> dict[str, Any]:
    payload = {k: v for k, v in res.items() if k != "rows"}
    payload["db"] = db
    payload["labels"] = labels_path
    if keep_rows:
        payload["rows"] = res["rows"]
    return payload


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Score the relationship engine against hand-labeled pairs "
                    "(read-only, offline, never a CI gate).")
    ap.add_argument("--db", default="data/run_delhivery.db", help="run database (opened read-only)")
    ap.add_argument("--labels", default=str(Path("evaluations") / "relationship_labels.json"),
                    help="hand-labeled ground truth JSON")
    ap.add_argument("--json", nargs="?", const="-", default=None, metavar="PATH",
                    help="emit JSON: bare --json prints JSON instead of the table; "
                         "--json PATH writes the file and still prints the table")
    ap.add_argument("--with-rows", action="store_true",
                    help="include the per-pair decision rows in the JSON output")
    ap.add_argument("--show", type=int, default=8, help="how many mismatches to print (0 = none)")
    ap.add_argument("--no-retrieval-check", action="store_true",
                    help="skip the find_candidates reachability diagnostic (faster)")
    args = ap.parse_args(argv)

    try:  # rupee signs and other non-ASCII in fact text, on a cp1252 console
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover
        pass

    try:
        labels = load_labels(args.labels)
        conn = open_db_readonly(args.db)
    except UsageError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    try:
        res = score(conn, labels, check_retrieval=not args.no_retrieval_check)
    finally:
        conn.close()

    if args.json == "-":
        print(json.dumps(_json_payload(res, args.db, args.labels, args.with_rows), indent=1))
        return 0
    print(render(res, args.db, args.labels, show=args.show))
    if args.json:
        try:
            p = Path(args.json)
            if str(p.parent) not in ("", "."):
                p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(_json_payload(res, args.db, args.labels, args.with_rows),
                                    indent=1), encoding="utf-8")
        except OSError as exc:
            print(f"ERROR: could not write {args.json}: {exc}", file=sys.stderr)
            return 2
        print(f"\nJSON written to {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
