"""Cache-key stability test (appended for audit fix)."""
import hashlib


def test_extract_cache_key_stable_across_processes():
    from src.extract import extract_facts_from_text
    from src.llm import MockProvider

    seen: list[str] = []

    class Rec(MockProvider):
        def generate_json(self, prompt, system="", cache_key="", namespace=""):
            seen.append(cache_key)
            return {"facts": []}

    canned_src = "z" * 200
    extract_facts_from_text(Rec(), canned_src, page=3)
    extract_facts_from_text(Rec(), canned_src, page=3)
    assert len(seen) == 2 and seen[0] == seen[1]
    expect = "extract:p3:" + hashlib.sha256(canned_src.encode()).hexdigest()[:16]
    assert seen[0] == expect  # sha256-based, NOT builtin hash() (randomized per process)
