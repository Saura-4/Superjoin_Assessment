"""Failure taxonomy helpers (Task 12).

Distinguishes extraction / fact-extraction / normalization / retrieval /
reasoning-uncertainty failures so the UI can surface uncertainty instead of
fabricating certainty. Vision fallback is an optional next step (see README);
safe failure behavior is implemented and tested here.
"""
from __future__ import annotations

from typing import Any


def describe_page_failure(status: str, quality: str, text_len: int) -> dict[str, Any]:
    kinds = {
        "empty_no_text": "extraction_failure",
        "failed": "extraction_failure",
        "low_text": "extraction_uncertainty",
        "processed_no_facts": "fact_extraction_empty",
    }
    return {
        "kind": kinds.get(status, "unknown"),
        "status": status,
        "quality": quality,
        "text_len": text_len,
        "honest": True,
        "detail": (
            "Page has no usable text layer (chart/scan/image-heavy). "
            "No facts were fabricated. Vision fallback would render this page "
            "as an image for a multimodal model."
            if status in ("empty_no_text", "failed") else
            "Low/empty extraction quality; facts from this page (if any) carry reduced confidence."
        ),
    }


def summarize_failures(page_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for p in page_rows:
        if p.get("status") in ("empty_no_text", "failed", "low_text", "processed_no_facts"):
            out.append({"page": p.get("page"), **describe_page_failure(
                p.get("status", ""), p.get("quality", "unknown"), p.get("text_len", 0))})
    return out
