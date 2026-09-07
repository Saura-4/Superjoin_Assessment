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
import urllib.error
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
    _dead_combos: object = None  # replaced per-instance in __post_init__ (session circuit breaker)

    def __post_init__(self):
        self.api_key = self.api_key or os.environ.get("GEMINI_API_KEY", "")
        self.model = os.environ.get("GEMINI_MODEL", self.model)
        try:
            self.min_interval_s = float(os.environ.get("GEMINI_MIN_INTERVAL", self.min_interval_s))
        except ValueError:
            pass
        self._dead_combos = set()
        if not self.api_key:
            raise LLMConfigError("GEMINI_API_KEY is not set (get a free key at https://aistudio.google.com)")

    def _cache_path(self, key: str, model: str = "") -> Optional[Path]:
        if not self.cache_dir or not key:
            return None
        h = hashlib.sha256(f"{model or self.model}::{key}".encode()).hexdigest()
        return Path(self.cache_dir) / f"{h}.json"

    def _keys(self) -> list[str]:
        """All usable keys, re-read live so a 2nd key added mid-run is picked up."""
        keys: list[str] = []
        for k in [os.environ.get("GEMINI_API_KEY", ""), self.api_key,
                  os.environ.get("GEMINI_API_KEY2", ""),
                  *[x.strip() for x in os.environ.get("GEMINI_API_KEYS", "").split(",")]]:
            if k and k not in keys:
                keys.append(k)
        return keys or [""]

    def _models(self) -> list[str]:
        ms = [self.model]
        fb = os.environ.get("GEMINI_FALLBACK_MODELS",
                            "gemini-3.5-flash-lite,gemini-3.6-flash,gemini-3.7-flash,gemini-3.8-flash")
        for m in [x.strip() for x in fb.split(",") if x.strip()]:
            if m not in ms:
                ms.append(m)
        return ms

    def _post(self, url: str, data: bytes) -> dict[str, Any]:
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
            return json.loads(resp.read().decode())

    @staticmethod
    def _parts_text(payload: dict[str, Any]) -> str:
        parts = payload.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        return "".join(p.get("text", "") for p in parts)

    def _request_with_retry(self, url: str, data: bytes) -> dict[str, Any]:
        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                gap = time.time() - self._last_call
                if gap < self.min_interval_s:
                    time.sleep(self.min_interval_s - gap)
                self._last_call = time.time()
                return self._post(url, data)
            except urllib.error.HTTPError as e:
                code = getattr(e, "code", 0)
                if code == 429:
                    # quota wall: one quick retry then rotate (don't burn 14s per dead combo)
                    last_err = LLMRateLimitError(f"gemini 429 rate-limited (attempt {attempt + 1})")
                    if attempt >= 1:
                        break
                elif 500 <= code < 600:
                    last_err = LLMError(f"gemini {code} server error (attempt {attempt + 1})")
                else:
                    try:
                        detail = e.read().decode()[:500]
                    except Exception:
                        detail = ""
                    raise LLMError(f"gemini HTTP {code}: {detail}")
                time.sleep(2 ** attempt * 2)
            except (LLMError, TimeoutError, ConnectionError, OSError) as e:
                last_err = e
                time.sleep(2 ** attempt * 2)
        raise last_err if last_err else LLMError("gemini request failed")

    def generate_json(self, prompt: str, system: str = "", cache_key: str = "") -> Any:
        cp = self._cache_path(cache_key or prompt[:2000])
        if cp is not None and cp.is_file():
            return json.loads(cp.read_text(encoding="utf-8"))

        last_err: Exception | None = None
        tried: list[str] = []
        combos = [(k, m) for k in self._keys() for m in self._models()]
        live = [c for c in combos if c not in self._dead_combos] or combos
        for key, model in live:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
                body: dict[str, Any] = {
                    "system_instruction": {"parts": [{"text": system}]} if system else None,
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"response_mime_type": "application/json", "temperature": 0.1},
                }
                body = {k: v for k, v in body.items() if v is not None}
                data = json.dumps(body).encode()
                try:
                    payload = self._request_with_retry(url, data)
                except LLMRateLimitError as e:
                    last_err = e
                    tried.append(f"{model}/key…{key[-4:]}")
                    self._dead_combos.add((key, model))  # skip this combo for the rest of the run
                    continue  # rotate key/model on exhausted quota
                parsed = extract_json(self._parts_text(payload))
                # cache under the model that actually answered
                cp = self._cache_path(cache_key or prompt[:2000], model)
                if cp is not None:
                    cp.parent.mkdir(parents=True, exist_ok=True)
                    cp.write_text(json.dumps(parsed), encoding="utf-8")
                if model != self.model:
                    print(f"[llm] serving via fallback model {model}")
                return parsed
        raise LLMRateLimitError(f"all key/model combos rate-limited ({'; '.join(tried)}): {last_err}")


def get_provider(name: str = "", cache_dir: str = "data/llm_cache") -> LLMProvider:
    """Factory: 'mock' → MockProvider, else Gemini (requires GEMINI_API_KEY).

    Controlled by env LLM_PROVIDER or explicit name. Never import vendor SDKs elsewhere.
    """
    n = (name or os.environ.get("LLM_PROVIDER", "")).lower()
    if n == "mock" or (not n and not os.environ.get("GEMINI_API_KEY")):
        return MockProvider()
    return GeminiProvider(cache_dir=cache_dir)
