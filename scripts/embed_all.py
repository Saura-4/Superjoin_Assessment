"""Embed remaining facts, quota split across live keys (local-only).

Each live key embeds at most --per-key facts (default 200). Parallel requests
per key, single SQLite writer. Resume-safe via text_hash. Model fixed.
Usage: python scripts/embed_all.py [--db ...] [--workers 2] [--per-key 200]
"""
import argparse
import hashlib
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

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
    """Parallel embeds; one bad future never kills the batch (logged, skipped)."""
    done, failed = [], 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(embedder.embed, [txt]): (fid, th) for fid, txt, th in jobs}
        for fut in as_completed(futs):
            fid, th = futs[fut]
            try:
                done.append((fid, fut.result()[0], th))
            except Exception as e:
                failed += 1
                print(f"  ! {fid[:6]} failed: {str(e)[:100]}", flush=True)
    if failed:
        print(f"  {failed} failed, {len(done)} ok", flush=True)
    return done


def read_keys(env):
    keys = [env.get("GEMINI_API_KEY", ""), env.get("GEMINI_API_KEY2", ""),
            env.get("GEMINI_API_KEY3", "")]
    for k in env.get("GEMINI_API_KEYS", "").split(","):
        keys.append(k.strip())
    seen = []
    for k in keys:
        if k and k not in seen:
            seen.append(k)
    return seen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/run_delhivery.db")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=None,
                    help="cap new embeddings this run (quota budgeting)")
    ap.add_argument("--per-key", type=int, default=200,
                    help="max facts per live key this run")
    args = ap.parse_args()
    env = load_env(".env")
    keys = live_keys(read_keys(env))
    if not keys:
        print("no live embedding keys; try again after quota reset")
        return 2
    conn = init_db(args.db)
    todo = missing(conn, EMBEDDING_MODEL)
    if args.limit is not None:
        todo = todo[:args.limit]
    print(f"missing: {len(todo)}, live keys: {len(keys)}, per-key cap: {args.per_key}", flush=True)
    # round-robin split across live keys only
    chunks = [todo[i::len(keys)] for i in range(len(keys))]
    # ~90/min: 4 workers x 2.7s pacing rides under the 100 RPM ceiling
    parts = [(GeminiEmbedder(api_key=k, min_interval_s=2.7), jobs)
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
