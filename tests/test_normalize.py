"""Task 6 tests: deterministic normalization."""
from src.normalize import (
    canonical_unit,
    normalize_fact_dict,
    normalize_period,
    normalize_value,
    parse_first_number,
)


def test_indian_numbers():
    assert parse_first_number("₹8,142 Cr") == 8142.0
    assert parse_first_number("81,415") == 81415.0
    assert parse_first_number("(₹2,491.86M)") == -2491.86
    assert parse_first_number("no numbers") is None


def test_scale_normalization_examples():
    v, u = normalize_value("740 Mn", "")
    assert v == 740_000_000.0
    v1, _ = normalize_value("₹81,415 Mn", "")
    v2, _ = normalize_value("₹8,142 Cr", "")
    assert v1 is not None and v2 is not None
    # rounding-level agreement (81,415 Mn vs 8,142 Cr differ by <0.1%)
    assert abs(v1 - v2) / v1 < 0.002
    v3, _ = normalize_value("2.8 Bn", "")
    assert v3 == 2_800_000_000.0
    v4, u4 = normalize_value("12.7%", "")
    assert (v4, u4) == (12.7, "PERCENT")


def test_lakh_crore():
    v, _ = normalize_value("1.5 lakh", "")
    assert v == 150_000.0
    v, u = normalize_value("₹117M", "")
    assert v == 117_000_000.0 and u == "INR"


def test_periods():
    assert normalize_period("FY24") == "FY24"
    assert normalize_period("FY 2023-24") == "FY24"
    assert normalize_period("Q4 FY24") == "Q4-FY24"
    assert normalize_period("Q3 FY24") == "Q3-FY24"
    assert normalize_period("March 31, 2024") == "2024-03-31"
    assert normalize_period("as of March 31, 2024") == "2024-03-31"


def test_units():
    assert canonical_unit("", "740 Mn parcels") == "PARCELS"
    assert canonical_unit("%", "12") == "PERCENT"


def test_fact_dict_enrichment_preserves_raw():
    f = normalize_fact_dict({"predicate": "Revenue From Services", "value_raw": "₹8,142 Cr",
                             "unit_raw": "INR", "period_raw": "FY24", "confidence": 2.0})
    assert f["predicate"] == "revenue_from_services"
    assert f["value_raw"] == "₹8,142 Cr"  # preserved
    assert f["value_norm"] == 8142 * 1e7
    assert f["period_norm"] == "FY24"
    assert f["confidence"] == 1.0  # clamped (recalibration happens in extract.validate)


def test_usd_and_bare_scale_units():
    assert canonical_unit("", "US$ 5 billion deal") == "USD"
    v, u = normalize_value("US$ 5 billion", "")
    assert (v, u) == (5_000_000_000.0, "USD")
    v, u = normalize_value("4.8", "million")
    assert (v, u) == (4_800_000.0, "COUNT")  # bare scale is not a unit
    v, u = normalize_value("2", "US billion")
    assert (v, u) == (2_000_000_000.0, "USD")
    v, u = normalize_value("₹8,142 Cr", "")
    assert u == "INR"  # unchanged


def test_dates_are_not_day_numbers():
    assert normalize_value("October 1, 2021", "") == (None, "DATE")
    assert normalize_value("July 01, 2024", "") == (None, "DATE")
    assert normalize_value("March 31, 2024", "") == (None, "DATE")
    assert normalize_value("FY24", "")[1] != "DATE"
    assert normalize_value("740 Mn", "") == (740_000_000.0, "COUNT")
