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
    d = load_env(".env")
    key = d["CEREBRAS_API_KEY"]
    req = urllib.request.Request(
        "https://api.cerebras.ai/v1/models",
        headers={"Authorization": "Bearer " + key},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        models = json.load(resp.read().decode()).get("data", [])
    for m in models:
        print(m.get("id"), "| ctx:", m.get("context_window"), "| tokens:",
              {k: v for k, v in (m.get("rate_limits") or {}).items()} if m.get("rate_limits") else "-")
