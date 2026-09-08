import json
import os
import sys
import urllib.request

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
    model = sys.argv[1] if len(sys.argv) > 1 else "qwen-3-32b"
    d = load_env(".env")
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": 'Return JSON only, exactly: {"ping": 1}'}],
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
        "max_tokens": 200,
    }).encode()
    req = urllib.request.Request(
        "https://api.cerebras.ai/v1/chat/completions", data=body,
        headers={"Authorization": "Bearer " + d["CEREBRAS_API_KEY"], "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            out = json.load(resp.read().decode())
        print("MODEL:", model)
        print("CONTENT:", out["choices"][0]["message"]["content"][:300])
        print("USAGE:", out.get("usage"))
    except Exception as e:
        print("FAIL:", type(e).__name__, str(e)[:400])
