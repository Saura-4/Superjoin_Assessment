"""Phase C1 runner: process the 3 Delhivery excerpts end-to-end (local-only).

Reads GEMINI_API_KEY (+optional GEMINI_MODEL) from .env — never commits them.
Writes run stats (counts/timings/quality, no secrets) to
evaluations/delhivery_run_stats.json for reviewer evidence.

Usage: python scripts/run_delhivery.py [--max-pages N]
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.db import init_db, list_relationships  # noqa: E402
from src.llm import get_provider  # noqa: E402
from src.pipeline import collection_stats, get_or_create_collection, process_document  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = [
    "unzipped_starter/starter-datasets/delhivery/01-delhivery-prospectus-2022-excerpt.pdf",
    "unzipped_starter/starter-datasets/delhivery/02-delhivery-annual-report-fy24-excerpt.pdf",
    "unzipped_starter/starter-datasets/delhivery/03-delhivery-q4-fy24-earnings-presentation.pdf",
]


def load_env(path=".env"):
    d = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                d[k.strip()] = v.strip()
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-pages", type=int, default=None)
    ap.add_argument("--db", default="data/run_delhivery.db")
    ap.add_argument("--doc-index", type=int, default=None,
                    help="process only DOCS[i] (0-2); run three times for the full set")
    args = ap.parse_args()

    env = load_env(os.path.join(BASE, ".env"))
    os.environ["GEMINI_API_KEY"] = env["GEMINI_API_KEY"]
    os.environ.setdefault("GEMINI_MODEL", env.get("GEMINI_MODEL", "gemini-3.1-flash-lite"))

    db_path = os.path.join(BASE, args.db)
    conn = init_db(db_path)
    provider = get_provider(cache_dir=os.path.join(BASE, "data/llm_cache"))
    print(f"provider={provider.name} model={getattr(provider, 'model', 'mock')}", flush=True)
    col = get_or_create_collection(conn, "delhivery", "Delhivery starter set")

    stats: dict = {"model": getattr(provider, "model", "mock"), "docs": [], "started": time.time()}
    docs = [DOCS[args.doc_index]] if args.doc_index is not None else DOCS
    for rel in docs:
        p = os.path.join(BASE, rel)
        t = time.time()
        res = process_document(conn, provider, col["id"], p,
                               data_dir=os.path.join(BASE, "data/files"),
                               max_pages=args.max_pages, scope="current")
        doc = res["document"]
        entry = {
            "file": os.path.basename(rel), "seconds": round(time.time() - t, 1),
            "pages": doc["num_pages"], "duplicate": res["duplicate"],
            "facts_added": res["facts_added"], "relationships_added": res["relationships_added"],
            "failures": res["failures"],
        }
        stats["docs"].append(entry)
        print(json.dumps(entry), flush=True)

    stats["total_seconds"] = round(time.time() - stats["started"], 1)
    stats["collection"] = collection_stats(conn, col["id"])
    by_type: dict = {}
    for r in list_relationships(conn, col["id"], limit=100000):
        by_type[r["type"]] = by_type.get(r["type"], 0) + 1
    stats["relationships_by_type"] = by_type
    out = os.path.join(BASE, "evaluations/delhivery_run_stats.json")
    with open(out, "w") as f:
        json.dump(stats, f, indent=1)
    print("TOTAL: " + json.dumps({k: v for k, v in stats.items() if k != "docs"}), flush=True)
    conn.close()


if __name__ == "__main__":
    main()
