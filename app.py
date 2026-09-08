"""Fact Knowledge Layer — Streamlit UI.

Journey: Collection → Upload → Processing status → Facts → Fact Detail →
Evidence → Related Facts → Relationship explanation. Demo Cases view retrieves
actual detected cases from the DB (never hard-coded ids).
Run: streamlit run app.py
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import streamlit as st

from src.db import (
    init_db,
    list_collections,
    list_documents,
    list_evidence_for_fact,
    list_facts,
    list_page_status,
    list_relationships,
    list_relationships_for_fact,
)
from src.llm import get_provider
from src.pipeline import collection_stats, get_or_create_collection, process_document


def _load_dotenv(path=".env"):
    """stdlib .env loader so `streamlit run app.py` picks up local keys."""
    if not os.path.isfile(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()

DB_PATH = os.environ.get("APP_DB", "data/app.db")
DATA_DIR = os.environ.get("DATA_DIR", "data/files")


def conn():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    return init_db(DB_PATH)


st.set_page_config(page_title="Fact Knowledge Layer", layout="wide")
st.title("Fact Knowledge Layer — provenance-first prototype")

db = conn()
provider = get_provider(cache_dir="data/llm_cache")
st.sidebar.caption(f"LLM provider: **{provider.name}** (mock = offline, no key needed)")

# ---- sidebar: collection ----
cols = list_collections(db)
names = [c["name"] for c in cols]
sel = st.sidebar.selectbox("Collection", names + ["+ new collection…"])
if sel == "+ new collection…":
    new_name = st.sidebar.text_input("New collection name", "delhivery")
    if st.sidebar.button("Create"):
        get_or_create_collection(db, new_name)
        st.rerun()
    st.info("Create a collection to begin.")
    st.stop()

col = next(c for c in cols if c["name"] == sel) if cols else get_or_create_collection(db, "delhivery")
st.sidebar.write(f"Documents / facts / relationships: **{collection_stats(db, col['id'])}**")
scope = st.sidebar.radio("Comparison scope", ["current", "all"], index=0,
                         help="Default is current collection. 'all' enables selective cross-collection retrieval.")

tabs = st.tabs(["Upload", "Facts", "Relationships", "Demo Cases", "Collections"])

with tabs[0]:
    st.header(f"Upload PDFs → {col['name']}")
    files = st.file_uploader("Drop PDFs (they join this collection incrementally)", type=["pdf"],
                             accept_multiple_files=True)
    max_pages = st.slider("Max pages per PDF (cost control, free-tier safe)", 1, 100, 15)
    if st.button("Process", disabled=not files):
        for f in files:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(f.read())
                tmp_path = tmp.name
            with st.spinner(f"Processing {f.name}…"):
                try:
                    res = process_document(db, provider, col["id"], tmp_path, data_dir=DATA_DIR,
                                           max_pages=max_pages, scope="current" if scope == "current" else "all",
                                           filename=f.name)
                except Exception as e:
                    st.error(f"{f.name}: {e}")
                    continue
            # duplicate uploads reuse prior work via content hash (see pipeline.py)
            if res["duplicate"]:
                st.warning(f"{f.name}: duplicate (hash match) — reused, no rebuild.")
            else:
                st.success(f"{f.name}: +{res['facts_added']} facts, +{res['relationships_added']} relationships.")
                for fail in res["failures"][:10]:
                    st.caption(f"p.{fail['page']}: {fail['kind']} — {fail['detail']}")
    st.subheader("Documents")
    for d in list_documents(db, col["id"]):
        with st.expander(f"{d['filename']} — {d['status']} ({d['num_pages']} pages)"):
            for p in list_page_status(db, d["id"])[:30]:
                st.caption(f"p.{p['page']}: {p['status']} ({p['quality']}, {p['text_len']} chars)")

with tabs[1]:
    st.header("Facts (every row is grounded)")
    q = st.text_input("Filter (subject / predicate / claim / period)")
    facts = list_facts(db, col["id"], limit=2000)
    if q:
        ql = q.lower()
        facts = [f for f in facts if ql in f"{f['subject']} {f['predicate']} {f['claim']} {f['period_raw']}".lower()]
    st.write(f"{len(facts)} facts")
    ids = [f"{f['subject']} · {f['predicate']} · {f['value_raw']} {f['unit_raw']} ({f['period_raw']}) — {f['id'][:6]}" for f in facts]
    pick = st.selectbox("Fact detail", ids) if ids else None
    if pick:
        f = next(x for x in facts if x["id"][:6] in pick)
        st.subheader(f["claim"])
        st.json({k: f.get(k) for k in ("subject", "predicate", "value_raw", "value_norm",
                                       "unit_raw", "unit_norm", "period_raw", "period_norm",
                                       "scope", "confidence")})
        st.write("**Evidence**")
        for e in list_evidence_for_fact(db, f["id"]):
            doc = db.execute("SELECT filename FROM documents WHERE id=?", (e["document_id"],)).fetchone()
            st.code(f"{doc['filename']} p.{e['page']}: {e['text'][:800]}")
        st.write("**Related facts + why**")
        for r in list_relationships_for_fact(db, f["id"]):
            other_id = r["fact_b_id"] if r["fact_a_id"] == f["id"] else r["fact_a_id"]
            o = db.execute("SELECT * FROM facts WHERE id=?", (other_id,)).fetchone()
            st.markdown(f"**{r['type']}** ({r['confidence']:.2f}) — {r['reason']}")
            if o:
                st.caption(f"↔ {o['subject']} · {o['predicate']} · {o['value_raw']} ({o['period_raw']}) — {o['claim'][:160]}")

with tabs[2]:
    st.header("Relationships (fact-to-fact)")
    rtype = st.selectbox("Type", ["all", "CORROBORATES", "CONTRADICTS", "RECONCILED", "TEMPORAL_CHANGE", "UNCERTAIN"])
    rels = list_relationships(db, col["id"], limit=2000) if rtype == "all" else list_relationships(
        db, col["id"], rel_type=rtype, limit=2000)
    st.write(f"{len(rels)} relationships")
    for r in rels[:100]:
        a = db.execute("SELECT * FROM facts WHERE id=?", (r["fact_a_id"],)).fetchone()
        b = db.execute("SELECT * FROM facts WHERE id=?", (r["fact_b_id"],)).fetchone()
        if a and b:
            st.markdown(f"**{r['type']}** ({r['confidence']:.2f}): {a['claim'][:120]}  ↔  {b['claim'][:120]}")
            st.caption(r["reason"])

with tabs[3]:
    st.header("Demo Cases — detected live from this collection")
    docs = list_documents(db, col["id"])
    doc_names = {d["id"]: d["filename"] for d in docs}

    def show_rel(r):
        a = db.execute("SELECT * FROM facts WHERE id=?", (r["fact_a_id"],)).fetchone()
        b = db.execute("SELECT * FROM facts WHERE id=?", (r["fact_b_id"],)).fetchone()
        if not (a and b):
            return
        st.markdown(f"**{r['type']}** ({r['confidence']:.2f}) — {r['reason']}")
        for f in (a, b):
            ev = list_evidence_for_fact(db, f["id"])
            src = str(doc_names.get(f['document_id'], '?')) + (f" p.{ev[0]['page']}" if ev else "")
            st.caption(f"• {f['claim']} [{src}] — `{f['value_raw']} {f['unit_raw']}` norm={f['value_norm']} period={f['period_norm']}")
            if ev:
                st.code(ev[0]["text"][:500])

    cases = {
        "1 · Corroborated across documents": list_relationships(db, col["id"], "CORROBORATES", 5),
        "2 · Contradiction / temporal change": (
            list_relationships(db, col["id"], "CONTRADICTS", 5)
            + list_relationships(db, col["id"], "TEMPORAL_CHANGE", 5)),
        "3 · Reconciled by context": list_relationships(db, col["id"], "RECONCILED", 5),
        "4 · Extraction failure (honest)": [],
    }
    for title, rs in cases.items():
        with st.expander(title, expanded=True):
            if title.startswith("4"):
                shown = False
                for d in docs:
                    for p in list_page_status(db, d["id"]):
                        if p["status"] in ("empty_no_text", "failed", "low_text", "processed_no_facts"):
                            st.caption(f"{d['filename']} p.{p['page']}: {p['status']} ({p['quality']}, {p['text_len']} chars) — no facts fabricated.")
                            shown = True
                            break
                    if shown:
                        break
                if not shown:
                    st.caption("No failures recorded yet — upload the chart-heavy earnings deck to see honest low-text handling.")
            elif not rs:
                st.caption("Not detected yet — process more pages/documents.")
            else:
                for r in rs[:3]:
                    show_rel(r)

with tabs[4]:
    st.header("Collections")
    for c in list_collections(db):
        s = collection_stats(db, c["id"])
        st.write(f"**{c['name']}** — {s['documents']} docs, {s['facts']} facts, {s['relationships']} rels")
