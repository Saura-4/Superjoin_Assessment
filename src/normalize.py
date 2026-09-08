"""Deterministic normalization — no LLM for arithmetic/unit conversion.

Covers: million/billion/trillion (Mn/M/Bn), lakh/crore, INR scales,
percentages, Indian comma numeric strings, fiscal years, quarters, dates.
Original values/claims are always preserved; *_norm fields are derived.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional

SCALE = {
    "k": 1e3, "thousand": 1e3, "thousands": 1e3,
    "m": 1e6, "mn": 1e6, "million": 1e6, "millions": 1e6, "mm": 1e6,
    "b": 1e9, "bn": 1e9, "billion": 1e9, "billions": 1e9,
    "t": 1e12, "tn": 1e12, "trillion": 1e12,
    "lakh": 1e5, "lac": 1e5, "lakhs": 1e5,
    "cr": 1e7, "crore": 1e7, "crores": 1e7,
}
CURRENCY_TOKENS = {"₹", "inr", "rs", "rs.", "rupee", "rupees"}
USD_TOKENS = {"$", "usd", "us$", "u.s.", "dollar", "dollars"}
PERCENT_TOKENS = {"%", "percent", "per cent", "percentage"}

_NUM = r"\(?-?\s*₹?\s*(?:Rs\.?\s*)?\(?-?\d[\d,]*\.?\d*"
_SCALE_WORD = r"(thousands?|millions?|billions?|trillions?|lakhs?|lacs?|crores?|cr|[kmbt]|mn|bn|tn|mm)\b\.?"


def parse_first_number(text: str) -> Optional[float]:
    """Parse first numeric token, handling Indian commas and (neg) parens."""
    if not text:
        return None
    m = re.search(_NUM, text.replace("₹", " ₹ "))
    if not m:
        return None
    tok = m.group(0)
    neg = tok.strip().startswith("(") or tok.strip().startswith("-")
    digits = re.sub(r"[^\d.]", "", tok)
    if not digits:
        return None
    try:
        val = float(digits)
    except ValueError:
        return None
    return -val if neg and val > 0 else val


def detect_scale(text: str) -> float:
    t = (text or "").lower().replace("₹", " ")
    m = re.search(_SCALE_WORD, t)
    if not m:
        return 1.0
    return SCALE.get(m.group(1).rstrip("."), 1.0)


def is_currency(text: str) -> bool:
    t = (text or "").lower()
    return "₹" in (text or "") or any(tok in t for tok in ("inr", "rs", "rupee", "rupees"))


def is_usd(text: str) -> bool:
    if is_currency(text):
        return False  # INR markers win (e.g. "Rs" mixed text)
    t = (text or "").lower()
    if "$" in (text or "") or any(tok in t for tok in ("usd", "us$", "dollar", "dollars")):
        return True
    # "US billion/million" (no $ sign): US + explicit scale reads as USD amount
    words = set(re.split(r"[^a-z0-9$]+", t))
    return bool({"us", "u.s"} & words) and detect_scale(text) != 1.0


def is_percent(text: str) -> bool:
    t = (text or "").lower()
    return "%" in (text or "") or "percent" in t or "per cent" in t


def canonical_unit(unit_raw: str, value_raw: str = "") -> str:
    blob = f"{unit_raw} {value_raw}"
    if is_percent(blob):
        return "PERCENT"
    if is_currency(blob):
        return "INR"
    if is_usd(blob):
        return "USD"
    u = (unit_raw or "").strip().lower()
    if not u:
        # infer count-like units from value text
        v = (value_raw or "").lower()
        for key, canon in (("tonne", "TONNES"), ("ton", "TONNES"), ("parcel", "PARCELS"),
                           ("shipment", "SHIPMENTS"), ("pin", "PINCODES"), ("employee", "EMPLOYEES"),
                           ("workforce", "EMPLOYEES"), ("customer", "CUSTOMERS"), ("sq ft", "SQFT"),
                           ("sqft", "SQFT"), ("tractor", "TRACTORS"), ("gateway", "GATEWAYS"),
                           ("centre", "CENTRES"), ("center", "CENTRES")):
            if key in v:
                return canon
        return "COUNT"
    # bare scale words ("million", "US billion") carry no unit meaning — scale is
    # already folded into value_norm; don't leak them as units.
    cleaned = re.sub(r"[^a-z ]", "", u).strip()
    without_scale = re.sub(
        r"\b(thousands?|millions?|billions?|trillions?|lakhs?|lacs?|crores?|cr|[kmbt]|mn|bn|tn|mm|us|u\.s\.)\b",
        "", cleaned).strip()
    if not without_scale:
        return canonical_unit("", value_raw)
    u = re.sub(r"[^a-z%₹ ]", "", u).strip().upper().replace(" ", "_")
    return u or "COUNT"


_MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"])}
_MONTHS.update({m[:3]: i for m, i in list(_MONTHS.items())})

_DATE_RES = [
    re.compile(r"(Jan\w*|Feb\w*|Mar\w*|Apr\w*|May|Jun\w*|Jul\w*|Aug\w*|Sep\w*|Oct\w*|Nov\w*|Dec\w*)\s+\d{1,2},?\s+20\d{2}", re.I),
    re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]20\d{2}\b"),
    re.compile(r"\b20\d{2}[/-]\d{1,2}[/-]\d{1,2}\b"),
]


def looks_like_date(text: str) -> bool:
    t = (text or "").strip()
    if not t or parse_first_number(t) is None:
        return False
    # a date contains a day/month/year structure, not just a stray number
    return any(rx.search(t) for rx in _DATE_RES)


def normalize_period(period_raw: str) -> str:
    """FY24, Q4-FY24, YYYY-MM-DD, or cleaned passthrough."""
    t = (period_raw or "").strip()
    if not t:
        return ""
    # Q4 FY24 / Q3 FY2023-24
    m = re.search(r"Q\s*([1-4])\s*FY\s*(\d{2,4})(?:\s*[-–/]\s*(\d{2,4}))?", t, re.I)
    if m:
        q, y1 = m.group(1), m.group(2)
        fy = f"FY{y1[-2:]}"
        return f"Q{q}-{fy}"
    # FY2023-24 / FY24 / FY 24-25 → use END year (Indian FY convention)
    m = re.search(r"FY\s*(\d{2,4})(?:\s*[-–/]\s*(\d{2,4}))?", t, re.I)
    if m:
        y = m.group(2) if m.group(2) else m.group(1)
        return f"FY{y[-2:]}"
    # 2024-25 / 2023/24 standalone
    m = re.search(r"\b(20\d{2})\s*[-–/]\s*(\d{2,4})\b", t)
    if m and "Q" not in t.upper() and "FY" not in t.upper():
        return f"FY{m.group(2)[-2:]}"
    # March 31, 2024
    m = re.search(r"(Jan\w*|Feb\w*|Mar\w*|Apr\w*|May|Jun\w*|Jul\w*|Aug\w*|Sep\w*|Oct\w*|Nov\w*|Dec\w*)\s+(\d{1,2}),?\s+(20\d{2})", t, re.I)
    if m:
        mon = _MONTHS.get(m.group(1).lower()[:3], 1)
        try:
            return datetime(int(m.group(3)), mon, int(m.group(2))).strftime("%Y-%m-%d")
        except ValueError:
            pass
    # as of March 31, 2024 → same date
    return t[:64]


def normalize_value(value_raw: str, unit_raw: str = "") -> tuple[Optional[float], str]:
    """Return (value_norm absolute, unit_norm canonical). None when non-numeric."""
    blob = f"{value_raw} {unit_raw}"
    if looks_like_date(value_raw) and not is_percent(blob):
        return None, "DATE"  # dates compare semantically, never as day-of-month arithmetic
    if is_percent(blob):
        num = parse_first_number(value_raw)
        return (num, "PERCENT") if num is not None else (None, "PERCENT")
    num = parse_first_number(value_raw)
    if num is None:
        return None, canonical_unit(unit_raw, value_raw)
    scale = detect_scale(blob)
    return num * scale, canonical_unit(unit_raw, value_raw)


def slugify_predicate(pred: str) -> str:
    s = (pred or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s[:64] or "fact"


def normalize_fact_dict(f: dict[str, Any]) -> dict[str, Any]:
    """Enrich a raw extracted fact dict with *_norm fields (pure function)."""
    out = dict(f)
    out["predicate"] = slugify_predicate(out.get("predicate", "fact"))
    v_raw = str(out.get("value_raw", "") or "")
    u_raw = str(out.get("unit_raw", "") or "")
    p_raw = str(out.get("period_raw", "") or "")
    v_norm, u_norm = normalize_value(v_raw, u_raw)
    out["value_norm"] = v_norm
    out["unit_norm"] = u_norm
    out["period_norm"] = normalize_period(p_raw)
    try:
        out["confidence"] = max(0.0, min(1.0, float(out.get("confidence", 0.5))))
    except (TypeError, ValueError):
        out["confidence"] = 0.5
    return out
