"""Offline evaluation runner (Task 13): python evaluations/evaluate.py.

Checks deterministic normalization, periods, relationship logic, candidate
filtering, and failure taxonomy against evaluations/expected_cases.json.
Needs no API key and never touches production code paths with fixtures.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.failures import describe_page_failure  # noqa: E402
from src.normalize import normalize_period, normalize_value  # noqa: E402
from src.relate import deterministic_decide, values_equal  # noqa: E402
from src.retrieve import predicate_compatible, subject_compatible  # noqa: E402


def _fact(**kw):
    base = {"subject": "S", "predicate": "p", "value_norm": None, "unit_norm": "",
            "period_norm": "", "scope": ""}
    base.update(kw)
    return base


def main() -> int:
    spec = json.loads((ROOT / "evaluations" / "expected_cases.json").read_text())
    fails: list[str] = []

    for n in spec["normalization"]:
        v, u = normalize_value(n["raw"], n.get("unit", ""))
        if v is None or abs(v - n["expect_norm"]) / max(abs(n["expect_norm"]), 1e-9) > 0.005:
            fails.append(f"normalization {n['raw']}: got {v}, want {n['expect_norm']}")
        if "expect_unit" in n and u != n["expect_unit"]:
            fails.append(f"unit {n['raw']}: got {u}")
    # cross-check the headline pair agrees
    a = spec["normalization"][2]
    b = spec["normalization"][3]
    va, _ = normalize_value(a["raw"], "")
    vb, _ = normalize_value(b["raw"], "")
    if values_equal(va, vb) is not True:
        fails.append("revenue pair should agree after normalization")

    for p in spec["periods"]:
        if normalize_period(p["raw"]) != p["expect"]:
            fails.append(f"period {p['raw']}: got {normalize_period(p['raw'])}")

    for r in spec["relationships"]:
        d = deterministic_decide(_fact(**r["a"]), _fact(**r["b"]))
        got = d["type"] if d else "NEEDS-LLM"
        if got != r["expect"]:
            fails.append(f"relationship {r['name']}: got {got}, want {r['expect']}")

    # candidate filtering sanity
    if not predicate_compatible("revenue", "revenue_from_services"):
        fails.append("predicate compat")
    if subject_compatible("Delhivery", "Reserve Bank of India"):
        fails.append("subject incompat")
    if not subject_compatible("Delhivery", "Delhivery Limited"):
        fails.append("subject compat")

    # failure taxonomy honesty
    f = describe_page_failure("empty_no_text", "empty", 0)
    if f["kind"] != "extraction_failure" or not f["honest"]:
        fails.append("failure taxonomy")

    if fails:
        print("EVALUATION FAILED:")
        for x in fails:
            print(" -", x)
        return 1
    print(f"EVALUATION PASSED ({len(spec['normalization']) + len(spec['periods']) + len(spec['relationships']) + 4} checks).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
