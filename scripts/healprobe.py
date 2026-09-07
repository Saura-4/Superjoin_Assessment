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
    from src.db import init_db
    from src.llm import get_provider
    from src.relate import relate_new_facts

    env = load_env(".env")
    os.environ["GEMINI_API_KEY"] = env["GEMINI_API_KEY"]
    conn = init_db("data/run_delhivery.db")
    col = conn.execute("select id from collections where name='delhivery'").fetchone()[0]
    doc = conn.execute("select id from documents where filename like '%prospectus%'").fetchone()[0]
    rows = [dict(r) for r in conn.execute(
        "select * from facts where collection_id=? and document_id=?", (col, doc)).fetchall()]
    linked = set()
    for r in conn.execute("select fact_a_id, fact_b_id from relationships where collection_id=?", (col,)):
        linked.add(r[0])
        linked.add(r[1])
    unl = [f for f in rows if f["id"] not in linked]
    print(f"unlinked={len(unl)}", flush=True)
    provider = get_provider(cache_dir="data/llm_cache")
    t = time.time()
    rels = relate_new_facts(conn, provider, unl[:20], [col], {})
    print(f"20 facts -> {len(rels)} rels in {time.time()-t:.1f}s", flush=True)
    from collections import Counter
    print(Counter(r["type"] for r in rels), flush=True)
    conn.close()
