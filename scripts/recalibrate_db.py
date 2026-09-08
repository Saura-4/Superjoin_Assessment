"""Offline migration: recalibrate stored fact confidences (no API calls).

Re-scores every fact with extract.recalibrate_confidence() using its stored
confidence + evidence quote, then applies the corroboration bump to facts
confirmed by an independent source. Idempotent (min() semantics + caps).
Usage: python scripts/recalibrate_db.py [--db data/run_delhivery.db] [--apply]
Default is dry-run histogram; --apply writes.
"""
import argparse
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.db import init_db  # noqa: E402
from src.extract import recalibrate_confidence  # noqa: E402
from src.normalize import normalize_fact_dict  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/run_delhivery.db")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    conn = init_db(args.db)
    facts = [dict(r) for r in conn.execute("SELECT * FROM facts").fetchall()]
    ev = {}
    for r in conn.execute("SELECT fact_id, text FROM evidence"):
        ev.setdefault(r[0], "")
        if len(r[1]) > len(ev[r[0]]):
            ev[r[0]] = r[1]
    corrob = set()
    for r in conn.execute("SELECT fact_a_id, fact_b_id FROM relationships WHERE type='CORROBORATES'"):
        corrob.add(r[0])
        corrob.add(r[1])

    plan = []
    renorm = 0
    for f in facts:
        # confidence: only touch never-recalibrated facts (exactly 1.0).
        # Recalibration is NOT idempotent (quote penalty would apply twice).
        if abs(f["confidence"] - 1.0) < 1e-9:
            new = recalibrate_confidence(f["confidence"], ev.get(f["id"], ""))
            if f["id"] in corrob:
                new = min(0.95, round(new + 0.05, 3))
            if abs(new - f["confidence"]) > 1e-9:
                plan.append((f["id"], f["confidence"], new))
        # re-derive normalization (unit/value/period rules evolve; raws are truth)
        enriched = normalize_fact_dict({
            "predicate": f["predicate"], "value_raw": f["value_raw"], "unit_raw": f["unit_raw"],
            "period_raw": f["period_raw"], "confidence": f["confidence"]})
        if (enriched["value_norm"] != f["value_norm"] or enriched["unit_norm"] != f["unit_norm"]
                or enriched["period_norm"] != f["period_norm"]):
            renorm += 1
            if args.apply:
                conn.execute("UPDATE facts SET value_norm=?, unit_norm=?, period_norm=? WHERE id=?",
                             (enriched["value_norm"], enriched["unit_norm"],
                              enriched["period_norm"], f["id"]))
    print(f"renormalized={renorm}")

    before = Counter(round(f["confidence"], 2) for f in facts)
    after_vals = {fid: new for fid, _, new in plan}
    after = Counter(round(after_vals.get(f["id"], f["confidence"]), 2) for f in facts)
    print(f"facts={len(facts)} to_update={len(plan)}")
    print("before:", sorted(before.items()))
    print("after: ", sorted(after.items()))
    if args.apply and plan:
        for fid, _, new in plan:
            conn.execute("UPDATE facts SET confidence=? WHERE id=?", (new, fid))
        conn.commit()
        print("applied.")
    elif not args.apply:
        print("dry-run; pass --apply to write.")
    conn.close()


if __name__ == "__main__":
    main()
