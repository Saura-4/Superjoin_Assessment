import os
import random
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
    d = load_env(".env")
    os.environ["GEMINI_API_KEY"] = d["GEMINI_API_KEY"]
    print("KEY2 present:", bool(d.get("GEMINI_API_KEY2")), flush=True)
    from src.llm import GeminiProvider

    p = GeminiProvider(cache_dir="data/llm_cache")
    t = time.time()
    try:
        out = p.generate_json(
            'Return JSON only, exactly: {"ping": 1}',
            system="You output JSON only.",
            cache_key="liveprobe-%d" % random.randint(0, 999999),
        )
        print("LIVE OK:", out, "%.1fs" % (time.time() - t), flush=True)
    except Exception as e:
        print("LIVE FAIL:", type(e).__name__, str(e)[:300], "%.1fs" % (time.time() - t), flush=True)
