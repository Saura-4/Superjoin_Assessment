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
