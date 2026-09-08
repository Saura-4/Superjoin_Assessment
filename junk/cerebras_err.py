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


if __name__ == "__main__":
    d = load_env(".env")
    body = json.dumps({
        "model": "llama3.1-8b",
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 20,
    }).encode()
    req = urllib.request.Request(
        "https://api.cerebras.ai/v1/chat/completions", data=body,
        headers={"Authorization": "Bearer " + d["CEREBRAS_API_KEY"], "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            print("OK", resp.status)
    except urllib.error.HTTPError as e:
        print("HTTP", e.code)
        print("BODY:", e.read().decode()[:600])
