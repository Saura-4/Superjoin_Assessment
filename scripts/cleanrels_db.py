"""Offline cleanup: drop relationships invalidated by newer deterministic rules.

Deletes rels where (a) either fact renormalized to DATE (old day-number verdicts),
or (b) predicates differ with neither values nor periods agreeing (new skip rule).
Deterministic + offline. Re-heal re-judges what remains.
Usage: python scripts/cleanrels_db.py [--db ...] [--apply]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.db import init_db  # noqa: E402
from src.relate import values_equal  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/run_delhivery.db")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    conn = init_db(args.db)
    facts = {r[0]: dict(zip(
        ["id", "predicate", "value_norm", "period_norm", "unit_norm"],
        r)) for r in conn.execute(
        "select id, predicate, value_norm, period_norm, unit_norm from facts").fetchall()}
    drop = []
    for r in conn.execute("select id, fact_a_id, fact_b_id, type from relationships").fetchall():
        rid, a, b, t = r[0], facts.get(r[1]), facts.get(r[2]), r[3]
        if a is None or b is None:
            drop.append((rid, "orphan"))
            continue
        if a["unit_norm"] == "DATE" or b["unit_norm"] == "DATE":
            drop.append((rid, f"date-unit stale {t}"))
            continue
        if a["predicate"] != b["predicate"]:
            va, vb, pa, pb = a["value_norm"], b["value_norm"], a["period_norm"] or "", b["period_norm"] or ""
            same_val = values_equal(va, vb) is True if va is not None and vb is not None else False
            if not (same_val or (pa and pb and pa == pb)):
                drop.append((rid, f"diff-pred noise {t}"))
    print(f"rels={conn.execute('select count(*) from relationships').fetchone()[0]} drop={len(drop)}")
    if args.apply:
        for rid, _ in drop:
            conn.execute("delete from relationships where id=?", (rid,))
        conn.commit()
        print("applied.")
    else:
        print("dry-run; pass --apply.")
    conn.close()


if __name__ == "__main__":
    main()
