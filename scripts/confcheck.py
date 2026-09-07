import glob
import json
from collections import Counter

ex_confs = []
judge_types = Counter()
judge_confs = []
n_ex = n_judge = 0
for f in glob.glob("data/llm_cache/*.json"):
    try:
        d = json.load(open(f))
    except Exception:
        continue
    if isinstance(d, dict) and "facts" in d and isinstance(d["facts"], list):
        n_ex += 1
        for fact in d["facts"]:
            if isinstance(fact, dict) and "confidence" in fact:
                try:
                    ex_confs.append(float(fact["confidence"]))
                except (TypeError, ValueError):
                    pass
    elif isinstance(d, dict) and "decisions" in d and isinstance(d["decisions"], list):
        n_judge += 1
        for dec in d["decisions"]:
            if isinstance(dec, dict):
                judge_types[str(dec.get("type"))] += 1
                try:
                    judge_confs.append(float(dec.get("confidence", -1)))
                except (TypeError, ValueError):
                    pass

print(f"cached extraction responses: {n_ex}, cached judge batches: {n_judge}")
h = Counter(round(c, 2) for c in ex_confs)
print(f"extraction confidencesCID ({len(ex_confs)} facts): {sorted(h.items())}")
print(f"judge types: {dict(judge_types)}")
jh = Counter(round(c, 2) for c in judge_confs)
print(f"judge confidences ({len(judge_confs)} decisions): {sorted(jh.items())}")

import sqlite3
c = sqlite3.connect("data/run_delhivery.db")
print("DB fact-confidence histogram:", c.execute(
    "select round(confidence,2), count(*) from facts group by 1 order by 1").fetchall())
print("DB rel-confidence by type:", c.execute(
    "select type, round(avg(confidence),2), count(*) from relationships group by 1").fetchall())
