"""Smoke-test the configured Gemini model (local-only, key from .env)."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_env(path=".env"):
    d = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                d[k.strip()] = v.strip()
    return d


if __name__ == "__main__":
    d = load_env()
    os.environ["GEMINI_API_KEY"] = d["GEMINI_API_KEY"]
    os.environ["GEMINI_MODEL"] = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")
    from src.llm import GeminiProvider

    p = GeminiProvider(cache_dir="data/llm_cache")
    t = time.time()
    out = p.generate_json(
        'Return JSON only, exactly: {"facts": [{"a": 1}]}',
        system="You output JSON only.",
        cache_key="smoke1",
    )
    print("model ok:", out, f"{time.time() - t:.1f}s")
