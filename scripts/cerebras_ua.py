import json
import os
import sys
import urllib.error
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


BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/126.0.0.0 Safari/537.36")

if __name__ == "__main__":
    d = load_env(".env")
    body = json.dumps({
        "model": "qwen-3.8-27b",
        "messages": [{"role": "user", "content": 'Return JSON only, exactly: {"ping": 1}'}],
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
        "max_tokens": 200,
    }).encode()
    req = urllib.request.Request(
        "https://api.cerebras.ai/v1/chat/completions", data=body,
        headers={"Authorization": "Bearer " + d["CEREBRAS_API_KEY"],
                 "Content-Type": "application/json",
                 "User-Agent": BROWSER_UA,
                 "Accept": "application/json, text/plain, */*",
                 "Accept-Language": "en-US,en;q=0.9"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            out = json.load(resp.read().decode())
        print("CONTENT:", out["choices"][0]["message"]["content"][:300])
        print("USAGE:", out.get("usage"))
    except urllib.error.HTTPError as e:
        print("HTTP", e.code, "BODY:", e.read().decode()[:300])
