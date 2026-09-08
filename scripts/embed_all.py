"""Embed all remaining facts, quota split 50/50 across two keys (local-only).

First half of the missing set goes through GEMINI_API_KEY, second half through
GEMINI_API_KEY2, each with its own thread pool (parallel requests, single
SQLite writer thread). Resume-safe via text_hash: already-embedded facts are
skipped. Model fixed to gemini-embedding-2.

Usage: python scripts/embed_all.py [--db ...] [--workers 3]
"""
import argparse
import hashlib
import os
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.db import init_db, upsert_embedding  # noqa: E402
from src.embed import EMBEDDING_MODEL, GeminiEmbedder, semantic_text  # noqa: E402


def load_env(path=".env"):
    if not os.path.isfile(path):
        return {}
    d = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                d.setdefault(k.strip(), v.strip())
    return d


def missing(conn, model):
    rows = [dict(r) for r in conn.execute("SELECT * FROM facts ORDER BY rowid").fetchall()]
    have = {r[0] for r in conn.execute(
        "SELECT fact_id FROM fact_embeddings WHERE model=?", (model,)).fetchall()}
    todo = []
    for f in rows:
        if f["id"] in have:
            continue
        txt = semantic_text(f)
        todo.append((f["id"], txt, hashlib.sha256(txt.encode()).hexdigest()[:16]))
    return todo


def live_keys(keys):
    """Probe each key once; drop 429-dead ones instead of burning retries on them."""
    live = []
    for k in keys:
        if not k:
            continue
        try:
            GeminiEmbedder(api_key=k, min_interval_s=0).embed(["Subject: probe"])
            live.append(k)
            print(f"key…{k[-4:]}: alive", flush=True)
        except Exception as e:
            print(f"key…{k[-4:]}: dead ({str(e)[:80]}), skipped", flush=True)
    return live


def run_half(embedder, jobs, workers):
    done = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(embedder.embed, [txt]): (fid, th) for fid, txt, th in jobs}
        for fut in futs:
            fid, th = futs[fut]
            done.append((fid, fut.result()[0], th))
    return done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/run_delhivery.db")
    ap.add_argument("--workers", type=int, default=3)
    args = ap.parse_args()
    env = load_env(".env")
    keys = live_keys([env.get("GEMINI_API_KEY", ""), env.get("GEMINI_API_KEY2", "")])
    if not keys:
        print("no live embedding keys; try again after quota reset")
        return 2
    conn = init_db(args.db)
    todo = missing(conn, EMBEDDING_MODEL)
    print(f"missing embeddings: {len(todo)}", flush=True)
    # split remaining work across live keys only
    chunks = [todo[i::len(keys)] for i in range(len(keys))]
    # 0.6s effective per key: 3 workers x 1.8s pacing ~= 100 RPM quota
    parts = [(GeminiEmbedder(api_key=k, min_interval_s=1.8), jobs)
             for k, jobs in zip(keys, chunks)]
    total = 0
    for emb, jobs in parts:
        if not jobs:
            continue
        print(f"key…{emb.api_key[-4:]}: {len(jobs)} facts", flush=True)
        for fid, vec, th in run_half(emb, jobs, args.workers):
            upsert_embedding(conn, fid, EMBEDDING_MODEL, vec, th)
            total += 1
            if total % 50 == 0:
                print(f"  {total}/{len(todo)}", flush=True)
    print(f"done: {total} embedded", flush=True)
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
