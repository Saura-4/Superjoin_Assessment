"""TASK3 Phase 9: 300-fact hybrid retrieval evaluation (100 per document).

Embeds the eval set (Gemini gemini-embedding-2 by default; --embedder hash for
offline plumbing checks), runs lexical ∪ semantic retrieval, structured
reranking, and the deterministic layer. LLM judging is DRY-RUN by default
(reports L = would-call count, makes zero judge calls); pass --with-llm to
actually judge ambiguous pairs.

Usage: python evaluations/hybrid_eval_300.py [--db ...] [--embedder gemini|hash] [--with-llm]
"""
import argparse
import hashlib
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.db import count_embeddings, init_db, list_documents, upsert_embedding  # noqa: E402
from src.embed import cosine, get_embedder, semantic_text  # noqa: E402
from src.evalset import select_eval_set  # noqa: E402
from src.relate import REL_TYPES, deterministic_decide  # noqa: E402
from src.retrieve import SemanticIndex, find_candidates, hybrid_retrieve, rerank_score  # noqa: E402

LEX_K, SEM_K, RERANK_MIN = 20, 20, 0.55


def load_env(path=".env"):
    if not os.path.isfile(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


load_env(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/run_delhivery.db")
    ap.add_argument("--embedder", default="gemini", choices=["gemini", "hash"])
    ap.add_argument("--per-doc", type=int, default=100)
    ap.add_argument("--with-llm", action="store_true")
    args = ap.parse_args()

    conn = init_db(args.db)
    col = conn.execute("select id from collections where name='delhivery'").fetchone()
    if not col:
        print("no delhivery collection in", args.db)
        return 2
    docs = [d["id"] for d in list_documents(conn, col[0])[:3]]
    eval_facts = select_eval_set(conn, docs, per_doc=args.per_doc)
    eval_ids = {f["id"] for f in eval_facts}
    print(f"eval set: {len(eval_facts)} facts across {len(docs)} docs")

    embedder = get_embedder(args.embedder)
    new_vecs = 0
    for f in eval_facts:
        txt = semantic_text(f)
        th = hashlib.sha256(txt.encode()).hexdigest()[:16]
        row = conn.execute("select text_hash from fact_embeddings where fact_id=? and model=?",
                           (f["id"], embedder.name)).fetchone()
        if row and row[0] == th:
            continue
        vec = embedder.embed([txt])[0]
        upsert_embedding(conn, f["id"], embedder.name, vec, th)
        new_vecs += 1
    print(f"embeddings: +{new_vecs} new ({embedder.name}), total={count_embeddings(conn)}")
    index = SemanticIndex.from_db(conn, embedder.name)
    by_id = {f["id"]: f for f in eval_facts}

    stat = Counter()
    det_types = Counter()
    examples: dict[str, list] = {}
    llm_pairs = 0
    seen_pairs: set[tuple[str, str]] = set()
    for f in eval_facts:
        vec = index.vectors.get(f["id"])
        if vec is None:
            continue
        cands = hybrid_retrieve(conn, f, index, vec, lex_k=LEX_K, sem_k=SEM_K,
                                exclude_same_doc=True, collection_ids=[col[0]],
                                require_compatible_context=True)
        cands = [c for c in cands if c["id"] in eval_ids]  # pilot scope: 300 only
        lex_only = find_candidates(conn, f, [col[0]], limit=LEX_K)
        lex_ids = {c["id"] for c in lex_only if c["document_id"] != f["document_id"]}
        stat["lex_total"] += len(lex_ids)
        sem_ranked = index.search(vec, top_k=SEM_K, exclude_ids={f["id"]})
        sem_ids = {fid for fid, _ in sem_ranked}
        # restrict semantic to eval set + cross-doc for fair comparison
        sem_ids = {fid for fid in sem_ids if fid in eval_ids
                   and by_id.get(fid, {}).get("document_id") != f["document_id"]}
        stat["sem_total"] += len(sem_ids)
        stat["merged_total"] += len(cands)
        for c in cands:
            pair = tuple(sorted((f["id"], c["id"])))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            sem_s = cosine(vec, index.vectors.get(c["id"], []))
            lex_s = 1.0 if c["id"] in lex_ids else 0.0
            score = rerank_score(f, c, sem_s, lex_s)
            if score < RERANK_MIN:
                stat["rerank_dropped"] += 1
                continue
            stat["rerank_kept"] += 1
            if c["id"] in lex_ids and c["id"] in sem_ids:
                stat["both"] += 1
            elif c["id"] in lex_ids:
                stat["lex_only_kept"] += 1
                examples.setdefault("lexical-only", []).append((f, c, score))
            else:
                stat["sem_only_kept"] += 1
                examples.setdefault("semantic-only", []).append((f, c, score))
            dec = deterministic_decide(f, c)
            if dec is None:
                llm_pairs += 1
                examples.setdefault("ambiguous-llm", []).append((f, c, score))
            else:
                det_types[dec["type"]] += 1
                if dec["type"] in ("CORROBORATES", "CONTRADICTS", "RECONCILED", "TEMPORAL_CHANGE"):
                    examples.setdefault(dec["type"], []).append((f, c, score))

    print(json.dumps({"lex_total": stat["lex_total"], "sem_total": stat["sem_total"],
                      "merged_total": stat["merged_total"], "both": stat["both"],
                      "lex_only_kept": stat["lex_only_kept"], "sem_only_kept": stat["sem_only_kept"],
                      "rerank_dropped": stat["rerank_dropped"], "rerank_kept": stat["rerank_kept"],
                      "deterministic": dict(det_types), "llm_would_call": llm_pairs}, indent=1))
    for title in ("CORROBORATES", "RECONCILED", "TEMPORAL_CHANGE", "semantic-only",
                  "lexical-only", "ambiguous-llm"):
        items = examples.get(title, [])[:2]
        for a, b, s in items:
            print(f"[{title} s={s}] {a['subject'][:24]}|{a['predicate'][:30]}|{a['value_raw'][:16]}"
                  f"  <->  {b['subject'][:24]}|{b['predicate'][:30]}|{b['value_raw'][:16]}")
    if not args.with_llm:
        print("LLM dry-run: 0 judge calls made. Pass --with-llm to judge ambiguous pairs.")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
