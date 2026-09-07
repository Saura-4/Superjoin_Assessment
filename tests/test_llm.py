"""Task 3 tests: provider boundary."""
import os

import pytest

from src.llm import (
    GeminiProvider,
    LLMConfigError,
    LLMError,
    MockProvider,
    extract_json,
    get_provider,
)


def test_extract_json_plain_and_fenced():
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json('```json\n{"a": [1,2]}\n```') == {"a": [1, 2]}
    assert extract_json('here you go {"x": 2} thanks') == {"x": 2}
    with pytest.raises(LLMError):
        extract_json('not json at all {{{')


def test_mock_provider_shapes():
    m = MockProvider()
    assert m.generate_json("extract facts") == {"facts": []}
    j = m.generate_json("RELATION JUDGE a vs b")
    assert j["type"] == "UNCERTAIN"


def test_gemini_missing_key():
    os.environ.pop("GEMINI_API_KEY", None)
    with pytest.raises(LLMConfigError):
        GeminiProvider(api_key="")


def test_factory_defaults_to_mock_without_key():
    os.environ.pop("GEMINI_API_KEY", None)
    os.environ.pop("LLM_PROVIDER", None)
    assert isinstance(get_provider(), MockProvider)
    assert isinstance(get_provider("mock"), MockProvider)


def test_gemini_rotation_on_429(monkeypatch):
    import io
    import urllib.error

    from src.llm import GeminiProvider
    monkeypatch.setenv("GEMINI_API_KEY", "key-one")
    monkeypatch.delenv("GEMINI_API_KEY2", raising=False)
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "fallback-model")
    monkeypatch.setenv("GEMINI_MIN_INTERVAL", "0")
    p = GeminiProvider(cache_dir=None, max_retries=1)
    seen_urls: list[str] = []

    def fake_post(url, data):
        seen_urls.append(url)
        if "3.1-flash-lite" in url:
            raise urllib.error.HTTPError(url, 429, "too many", {}, io.BytesIO(b"{}"))
        return {"candidates": [{"content": {"parts": [{"text": '{"ok": 2}'}]}}]}

    p._post = fake_post  # type: ignore[method-assign]
    assert p.generate_json("hi", cache_key="") == {"ok": 2}
    assert any("3.1-flash-lite" in u for u in seen_urls)
    assert any("fallback-model" in u for u in seen_urls)


def test_gemini_second_key_picked_up_live(monkeypatch):
    import io
    import urllib.error

    from src.llm import GeminiProvider
    monkeypatch.setenv("GEMINI_API_KEY", "key-one")
    monkeypatch.delenv("GEMINI_API_KEY2", raising=False)
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "")
    monkeypatch.setenv("GEMINI_MIN_INTERVAL", "0")
    p = GeminiProvider(cache_dir=None, max_retries=1)
    seen: list[str] = []

    def fake_post(url, data):
        seen.append(url)
        if "key-one" in url:
            raise urllib.error.HTTPError(url, 429, "slow down", {}, io.BytesIO(b"{}"))
        return {"candidates": [{"content": {"parts": [{"text": '{"ok": 3}'}]}}]}

    p._post = fake_post  # type: ignore[method-assign]
    # user mints key 2 mid-run → rotation must see it without reconstructing
    monkeypatch.setenv("GEMINI_API_KEY2", "key-two")
    assert p.generate_json("hi", cache_key="") == {"ok": 3}
    assert any("key-two" in u for u in seen)


def test_gemini_pacing_and_post_split(monkeypatch):
    import time

    from src.llm import GeminiProvider
    monkeypatch.setenv("GEMINI_API_KEY", "dummy")
    monkeypatch.setenv("GEMINI_MIN_INTERVAL", "0.05")
    p = GeminiProvider(cache_dir=None)
    calls: list[float] = []

    def fake_post(url, data):
        calls.append(time.time())
        return {"candidates": [{"content": {"parts": [{"text": '{"ok": 1}'}]}}]}

    p._post = fake_post  # type: ignore[method-assign]
    p.generate_json("hi", cache_key="")
    p.generate_json("hi2", cache_key="")
    assert len(calls) == 2
    assert calls[1] - calls[0] >= 0.04  # paced, not back-to-back


def test_cache_namespace_busts_stale_prompts(monkeypatch, tmp_path):
    from src.llm import GeminiProvider
    monkeypatch.setenv("GEMINI_API_KEY", "dummy")
    p = GeminiProvider(cache_dir=str(tmp_path))
    assert p._cache_path("k") != p._cache_path("k", "judge-v3-qualified")
    # empty namespace reproduces legacy keys (old extraction cache stays valid)
    assert p._cache_path("k", "") == p._cache_path("k")
