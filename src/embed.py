"""Fact embeddings for hybrid retrieval (TASK3).

Two representations per fact (per spec):
- canonical structured row in `facts` (source of truth, never replaced);
- semantic text (Subject/Metric/Period/Scope + claim context) embedded ONLY
  for candidate retrieval. Numerical/unit comparison stays deterministic.

Model is fixed to `gemini-embedding-2` (user decision: fast, RPM 100, never
switch mid-project — vectors from mixed models are not comparable).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Optional

from src.llm import BROWSER_UA, LLMConfigError, LLMError

EMBEDDING_MODEL = "gemini-embedding-2"


def semantic_text(fact: dict[str, Any]) -> str:
    """Small testable serializer: semantics in, numbers out (as primary signal).

    Values/units are deliberately NOT the focus — the deterministic ladder owns
    arithmetic. Period/scope stay because they disambiguate meaning.
    """
    subj = str(fact.get("subject", "") or "").strip()
    pred = str(fact.get("predicate", "") or "").replace("_", " ").strip()
    period = str(fact.get("period_raw", "") or fact.get("period_norm", "") or "").strip()
    scope = str(fact.get("scope", "") or "").strip()
    claim = str(fact.get("claim", "") or "").strip()[:300]
    lines = [f"Subject: {subj}", f"Metric: {pred}"]
    if period:
        lines.append(f"Period: {period}")
    if scope:
        lines.append(f"Scope: {scope}")
    if claim:
        lines.append(f"Context: {claim}")
    return "\n".join(lines)


class Embedder:
    """Interface: text in, vectors out. Implementations are interchangeable."""

    name: str = "base"
    dim: int = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


class HashEmbedder(Embedder):
    """Deterministic offline stand-in (tests/dev). Hashed token buckets, L2-normed.

    NOT semantically meaningful — only exercises plumbing (shapes, ranking math).
    """

    name: str = "hash"
    dim: int = 256

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            vec = [0.0] * self.dim
            for tok in (t or "").lower().split():
                vec[int(hashlib.sha256(tok.encode()).hexdigest(), 16) % self.dim] += 1.0
            n = math.sqrt(sum(x * x for x in vec)) or 1.0
            out.append([x / n for x in vec])
        return out


@dataclass
class GeminiEmbedder(Embedder):
    api_key: str = ""
    model: str = EMBEDDING_MODEL
    timeout_s: float = 60.0
    max_retries: int = 4
    min_interval_s: float = 0.7  # ~100 RPM headroom
    name: str = "gemini-embedding-2"
    dim: int = 0  # set from first response
    _last_call: float = 0.0

    def __post_init__(self):
        self.api_key = self.api_key or os.environ.get("GEMINI_API_KEY", "")
        self.model = os.environ.get("GEMINI_EMBEDDING_MODEL", self.model)
        if self.model != EMBEDDING_MODEL:
            raise LLMConfigError(f"embedding model is fixed to {EMBEDDING_MODEL}, got {self.model}")
        if not self.api_key:
            raise LLMConfigError("GEMINI_API_KEY is not set")

    def _post(self, text: str) -> list[float]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:embedContent?key={self.api_key}"
        data = json.dumps({"content": {"parts": [{"text": text}]}}).encode()
        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                gap = time.time() - self._last_call
                if gap < self.min_interval_s:
                    time.sleep(self.min_interval_s - gap)
                self._last_call = time.time()
                req = urllib.request.Request(url, data=data, headers={
                    "Content-Type": "application/json", "User-Agent": BROWSER_UA,
                    "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                    payload = json.loads(resp.read().decode())
                return [float(x) for x in payload["embedding"]["values"]]
            except urllib.error.HTTPError as e:
                code = getattr(e, "code", 0)
                if code in (429,) or 500 <= code < 600:
                    last_err = LLMError(f"embedding HTTP {code} (attempt {attempt + 1})")
                else:
                    try:
                        detail = e.read().decode()[:300]
                    except Exception:
                        detail = ""
                    raise LLMError(f"embedding HTTP {code}: {detail}")
                time.sleep(2 ** attempt * 2)
            except (TimeoutError, ConnectionError, OSError) as e:
                last_err = e
                time.sleep(2 ** attempt * 2)
        raise last_err if last_err else LLMError("embedding request failed")

    def embed(self, texts: list[str]) -> list[list[float]]:
        vecs = [self._post(t) for t in texts]
        if vecs and not self.dim:
            self.dim = len(vecs[0])
        return vecs


def cosine(a: list[float], b: list[float]) -> float:
    n = len(a)
    if not n or len(b) != n:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def get_embedder(name: str = "") -> Embedder:
    """'hash' → offline stub; default → Gemini (needs GEMINI_API_KEY)."""
    n = (name or os.environ.get("EMBEDDER", "")).lower()
    if n == "hash" or (not n and not os.environ.get("GEMINI_API_KEY")):
        return HashEmbedder()
    return GeminiEmbedder()
