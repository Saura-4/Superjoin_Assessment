"""Small LLM provider boundary: real (Gemini free tier) + mock.

Verified 2026-09: Gemini API offers a $0 Free Tier on eligible models
(e.g. gemini-2.5-flash / flash-lite, 3.x Flash family) with per-project
RPM/RPD caps (429 when exceeded) — see https://ai.google.dev/gemini-api/docs/rate-limits
and https://ai.google.dev/gemini-api/docs/billing. We default to
`gemini-2.5-flash`, JSON mode, retry+backoff on 429/5xx, and keep all
vendor HTTP inside this module.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


class LLMError(Exception):
    pass


class LLMConfigError(LLMError):
    pass


class LLMRateLimitError(LLMError):
    pass


def extract_json(text: str) -> Any:
    """Parse JSON, tolerating ```json fences and leading/trailing prose."""
    t = (text or "").strip()
    if not t:
        raise LLMError("empty LLM response")
    if t.startswith("```"):
        # strip first fence line and last fence
        lines = t.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        start_candidates = [i for i, ch in enumerate(t) if ch in "{["]
        for s in start_candidates:
            for e in range(len(t), s, -1):
                if t[e - 1] in "}]":
                    try:
                        return json.loads(t[s:e])
                    except json.JSONDecodeError:
                        continue
        raise LLMError(f"invalid JSON from LLM: {text[:300]!r}")


class LLMProvider:
    """Interface. generate_json returns parsed JSON (dict or list)."""

    name: str = "base"

    def generate_json(self, prompt: str, system: str = "", cache_key: str = "") -> Any:
        raise NotImplementedError


@dataclass
class MockProvider(LLMProvider):
    """Deterministic offline provider for tests/dev without API keys."""

    name: str = "mock"
    canned: Any = None

    def generate_json(self, prompt: str, system: str = "", cache_key: str = "") -> Any:
        if self.canned is not None:
            return self.canned
        # Generic empty-but-valid extraction shape so pipelines run offline.
        if "RELATION" in prompt.upper() or "JUDGE" in prompt.upper():
            return {"type": "UNCERTAIN", "confidence": 0.3, "reason": "mock: ambiguous without real LLM"}
        return {"facts": []}


@dataclass
class GeminiProvider(LLMProvider):
    api_key: str = ""
    model: str = "gemini-3.1-flash-lite"
    timeout_s: float = 60.0
    max_retries: int = 4
    cache_dir: Optional[str] = None
    name: str = "gemini"
    min_interval_s: float = 4.2  # client-side pacing for low free-tier RPM (e.g. 15)
    _last_call: float = 0.0

    def __post_init__(self):
        self.api_key = self.api_key or os.environ.get("GEMINI_API_KEY", "")
        self.model = os.environ.get("GEMINI_MODEL", self.model)
        try:
            self.min_interval_s = float(os.environ.get("GEMINI_MIN_INTERVAL", self.min_interval_s))
        except ValueError:
            pass
        if not self.api_key:
            raise LLMConfigError("GEMINI_API_KEY is not set (get a free key at https://aistudio.google.com)")

    def _cache_path(self, key: str) -> Optional[Path]:
        if not self.cache_dir or not key:
            return None
        h = hashlib.sha256(f"{self.model}::{key}".encode()).hexdigest()
        return Path(self.cache_dir) / f"{h}.json"

    def _post(self, url: str, data: bytes) -> dict[str, Any]:
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
            return json.loads(resp.read().decode())

    def generate_json(self, prompt: str, system: str = "", cache_key: str = "") -> Any:
        cp = self._cache_path(cache_key or prompt[:2000])
        if cp is not None and cp.is_file():
            return json.loads(cp.read_text(encoding="utf-8"))

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        body: dict[str, Any] = {
            "system_instruction": {"parts": [{"text": system}]} if system else None,
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"response_mime_type": "application/json", "temperature": 0.1},
        }
        body = {k: v for k, v in body.items() if v is not None}
        data = json.dumps(body).encode()

        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                gap = time.time() - self._last_call
                if gap < self.min_interval_s:
                    time.sleep(self.min_interval_s - gap)
                self._last_call = time.time()
                payload = self._post(url, data)
                parts = payload.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                text = "".join(p.get("text", "") for p in parts)
                parsed = extract_json(text)
                if cp is not None:
                    cp.parent.mkdir(parents=True, exist_ok=True)
                    cp.write_text(json.dumps(parsed), encoding="utf-8")
                return parsed
            except urllib.error.HTTPError as e:  # type: ignore[attr-defined]
                code = getattr(e, "code", 0)
                if code == 429:
                    last_err = LLMRateLimitError(f"gemini 429 rate-limited (attempt {attempt+1})")
                elif 500 <= code < 600:
                    last_err = LLMError(f"gemini {code} server error (attempt {attempt+1})")
                else:
                    try:
                        detail = e.read().decode()[:500]  # type: ignore[union-attr]
                    except Exception:
                        detail = ""
                    raise LLMError(f"gemini HTTP {code}: {detail}")
                time.sleep(2 ** attempt * 2)
            except (LLMError, TimeoutError, ConnectionError, OSError) as e:
                last_err = e
                time.sleep(2 ** attempt * 2)
        raise last_err if last_err else LLMError("gemini request failed")


def get_provider(name: str = "", cache_dir: str = "data/llm_cache") -> LLMProvider:
    """Factory: 'mock' → MockProvider, else Gemini (requires GEMINI_API_KEY).

    Controlled by env LLM_PROVIDER or explicit name. Never import vendor SDKs elsewhere.
    """
    n = (name or os.environ.get("LLM_PROVIDER", "")).lower()
    if n == "mock" or (not n and not os.environ.get("GEMINI_API_KEY")):
        return MockProvider()
    return GeminiProvider(cache_dir=cache_dir)
