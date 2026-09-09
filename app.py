"""Fact Knowledge Layer — Streamlit UI (ui-ux-pro-max pass).

Design: minimal analytics dashboard. KPI row first, tables over dumps,
progressive disclosure (detail lives in expanders), semantic badges with text
labels (never color-alone), one primary CTA per screen, helpful empty states.
Data journey unchanged: Collection → Upload → Facts → Relationships → Demo Cases.
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

DB_PATH = os.environ.get("APP_DB", "data/app.db")
DATA_DIR = os.environ.get("DATA_DIR", "data/files")

BADGE = {
    "CORROBORATES": ("#e8f5e9", "#1b7a2e", "agree"),
    "CONTRADICTS": ("#fdecea", "#b3261e", "conflict"),
    "RECONCILED": ("#e8f0fe", "#1a56db", "context"),
    "TEMPORAL_CHANGE": ("#fff8e1", "#8a6d00", "over time"),
    "UNCERTAIN": ("#f1f3f4", "#5f6368", "unsure"),
}


def badge(rel_type: str) -> str:
    bg, fg, hint = BADGE.get(rel_type, ("#f1f3f4", "#5f6368", ""))
    label = f"{rel_type} · {hint}" if hint else rel_type
    return (f"<span style='background:{bg};color:{fg};border-radius:6px;"
            f"padding:2px 10px;font-size:12px;font-weight:600;white-space:nowrap;'>{label}</span>")


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

CSS = """
<style>
.block-container { max-width: 1100px; }
div[data-testid="stMetric"] { background:#fff; border:1px solid #e6e8eb; border-radius:12px; padding:12px 16px; }
.fact-card { background:#fff; border:1px solid #e6e8eb; border-radius:12px; padding:14px 18px; margin:10px 0; }
.fact-claim { font-size:17px; font-weight:600; margin:0 0 4px 0; }
.fact-meta { color:#5f6368; font-size:13px; }
.evidence { border-left:3px solid #1a56db; padding:6px 12px; color:#3c4043; font-size:14px; margin:8px 0; }
</style>
"""

st.set_page_config(page_title="Fact Knowledge Layer", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)
st.title("Fact Knowledge Layer")
st.caption("Turn PDFs into grounded facts, then see how facts across documents relate.")

db = init_db(DB_PATH)
provider = get_provider(cache_dir="data/llm_cache")

# ---- sidebar ----
st.sidebar.caption(f"LLM: **{provider.name}**" + (" (offline demo mode)" if provider.name == "mock" else ""))
cols = list_collections(db)
names = [c["name"] for c in cols]
sel = st.sidebar.selectbox("Collection", names + ["+ new collection"])
if sel == "+ new collection":
    new_name = st.sidebar.text_input("Name", "delhivery")
    if st.sidebar.button("Create collection", type="primary"):
        get_or_create_collection(db, new_name)
        st.rerun()
    st.info("Create a collection to begin.")
    st.stop()

col = next(c for c in cols if c["name"] == sel) if cols else get_or_create_collection(db, "delhivery")
stats = collection_stats(db, col["id"])
scope = st.sidebar.radio("Compare across", ["This collection", "All collections"],
                         help="Relationships are discovered inside the selected scope only.")

# ---- KPI row ----
k1, k2, k3, k4 = st.columns(4)
k1.metric("Documents", stats["documents"])
k2.metric("Facts", stats["facts"])
k3.metric("Relationships", stats["relationships"])
fail_pages = sum(1 for d in list_documents(db, col["id"]) for p in list_page_status(db, d["id"])
                 if p["status"] in ("empty_no_text", "failed"))
k4.metric("Pages needing review", fail_pages)

tabs = st.tabs(["Upload", "Facts", "Relationships", "Demo cases", "Collections"])

# ---- Upload ----
with tabs[0]:
    st.subheader(f"Add PDFs to **{col['name']}**")
    files = st.file_uploader("Drop PDFs here", type=["pdf"], accept_multiple_files=True,
                             label_visibility="collapsed")
    max_pages = st.slider("Pages per PDF (cost control)", 1, 100, 15)
    if st.button("Process", type="primary", disabled=not files):
        for f in files:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(f.read())
                tmp_path = tmp.name
            with st.spinner(f"Processing {f.name}…"):
                try:
                    res = process_document(db, provider, col["id"], tmp_path, data_dir=DATA_DIR,
                                           max_pages=max_pages,
                                           scope="all" if scope == "All collections" else "current",
                                           filename=f.name)
                except Exception as e:
                    st.error(f"{f.name}: {e}")
                    continue
            if res["duplicate"]:
                st.warning(f"{f.name}: already processed — reused, nothing rebuilt.")
            else:
                st.success(f"{f.name}: **+{res['facts_added']}** facts, **+{res['relationships_added']}** links.")
                for fail in res["failures"][:5]:
                    st.caption(f"Page {fail['page']}: {fail['kind']} — no facts fabricated.")
    st.divider()
    for d in list_documents(db, col["id"]):
        pages = list_page_status(db, d["id"])
        bad = sum(1 for p in pages if p["status"] in ("empty_no_text", "failed"))
        flag = f" · {bad} pages need review" if bad else ""
        with st.expander(f"**{d['filename']}** — {d['status']} · {d['num_pages']} pages{flag}"):
            for p in pages[:30]:
                st.caption(f"p.{p['page']}: {p['status']} ({p['quality']}, {p['text_len']} chars)")


def _doc_names(collection_id: str) -> dict[str, str]:
    return {d["id"]: d["filename"] for d in list_documents(db, collection_id)}


def _rel_card(r: dict, doc_names: dict[str, str]) -> None:
    a = db.execute("SELECT * FROM facts WHERE id=?", (r["fact_a_id"],)).fetchone()
    b = db.execute("SELECT * FROM facts WHERE id=?", (r["fact_b_id"],)).fetchone()
    if not (a and b):
        return
    st.markdown(f"{badge(r['type'])} <span class='fact-meta'>confidence {r['confidence']:.2f}</span>",
                unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    for colx, f in ((c1, a), (c2, b)):
        with colx:
            ev = list_evidence_for_fact(db, f["id"])
            src = f"{doc_names.get(f['document_id'], '?')}" + (f" · p.{ev[0]['page']}" if ev else "")
            st.markdown(f"<div class='fact-card'><p class='fact-claim'>{f['claim'][:160]}</p>"
                        f"<p class='fact-meta'>{f['subject']} · {f['predicate']} · "
                        f"<b>{f['value_raw']} {f['unit_raw']}</b> ({f['period_raw']})<br>{src}</p></div>",
                        unsafe_allow_html=True)
    st.caption(r["reason"] or "No explanation recorded.")


# ---- Facts ----
with tabs[1]:
    st.subheader("Facts")
    q = st.search_input if hasattr(st, "search_input") else st.text_input
    query = q("Search subject, metric, claim, or period", placeholder="e.g. revenue, FY24, parcels")
    facts = list_facts(db, col["id"], limit=2000)
    if query:
        ql = query.lower()
        facts = [f for f in facts if ql in f"{f['subject']} {f['predicate']} {f['claim']} {f['period_raw']}".lower()]
    if not facts:
        st.info("No facts yet — upload a PDF first.")
    else:
        st.caption(f"{len(facts)} facts · every row links to source evidence")
        options = [f"{f['subject']} · {f['predicate']} · {f['value_raw']} {f['unit_raw']} ({f['period_raw']})"
                   for f in facts]
        pick = st.selectbox("Open fact detail", options)
        f = next(x for x in facts if pick.startswith(x["subject"]) and x["predicate"] in pick)
        st.markdown(f"<div class='fact-card'><p class='fact-claim'>{f['claim']}</p>"
                    f"<p class='fact-meta'>normalized: <b>{f['value_norm']}</b> [{f['unit_norm']}] · "
                    f"period {f['period_norm']} · scope {f['scope'] or '—'} · "
                    f"confidence {f['confidence']:.2f}</p></div>", unsafe_allow_html=True)
        st.markdown("**Evidence**")
        for e in list_evidence_for_fact(db, f["id"]):
            doc = db.execute("SELECT filename FROM documents WHERE id=?", (e["document_id"],)).fetchone()
            st.markdown(f"<div class='evidence'>{doc['filename']} · page {e['page']}<br>{e['text'][:600]}</div>",
                        unsafe_allow_html=True)
        related = list_relationships_for_fact(db, f["id"])
        if related:
            st.markdown("**Related facts**")
            for r in related[:10]:
                other_id = r["fact_b_id"] if r["fact_a_id"] == f["id"] else r["fact_a_id"]
                o = db.execute("SELECT * FROM facts WHERE id=?", (other_id,)).fetchone()
                st.markdown(badge(r["type"]), unsafe_allow_html=True)
                st.caption((o["claim"][:160] if o else "?") + f" — {r['reason'][:200]}")

# ---- Relationships ----
with tabs[2]:
    st.subheader("Relationships")
    f1, f2 = st.columns([3, 1])
    with f1:
        rtype = st.selectbox("Type", ["all", "CORROBORATES", "CONTRADICTS", "RECONCILED",
                                      "TEMPORAL_CHANGE", "UNCERTAIN"], label_visibility="collapsed")
    with f2:
        cross_only = st.checkbox("Cross-document only")
    rels = list_relationships(db, col["id"], limit=2000, cross_doc_only=cross_only) \
        if rtype == "all" else list_relationships(
        db, col["id"], rel_type=rtype, limit=2000, cross_doc_only=cross_only)
    if not rels:
        st.info("No relationships of this type yet — process more documents.")
    else:
        st.caption(f"{len(rels)} relationships · showing up to 25")
        for r in rels[:25]:
            with st.container(border=True):
                _rel_card(r, _doc_names(col["id"]))

# ---- Demo cases ----
with tabs[3]:
    st.subheader("Demo cases — detected live, never hard-coded")
    doc_names = _doc_names(col["id"])

    def get_demo_cases(rtype: str, limit: int = 5) -> list[dict]:
        cross = list_relationships(db, col["id"], rel_type=rtype, limit=limit, cross_doc_only=True)
        if len(cross) >= limit:
            return cross
        rest = list_relationships(db, col["id"], rel_type=rtype, limit=limit)
        seen = {r["id"] for r in cross}
        return cross + [r for r in rest if r["id"] not in seen][:limit - len(cross)]

    cases = {
        "1 · Corroborated across documents": get_demo_cases("CORROBORATES", 5),
        "2 · Contradiction / temporal change": get_demo_cases("CONTRADICTS", 3)
        + get_demo_cases("TEMPORAL_CHANGE", 3),
        "3 · Reconciled by context": get_demo_cases("RECONCILED", 5),
    }
    for title, rs in cases.items():
        with st.expander(title, expanded=(title == "1 · Corroborated across documents")):
            if not rs:
                st.caption("Not detected yet — process more pages or documents.")
            for r in rs[:3]:
                _rel_card(r, doc_names)
    with st.expander("4 · Extraction failure (honest)"):
        shown = False
        for d in list_documents(db, col["id"]):
            for p in list_page_status(db, d["id"]):
                if p["status"] in ("empty_no_text", "failed", "low_text", "processed_no_facts"):
                    st.caption(f"{d['filename']} · p.{p['page']}: {p['status']} "
                               f"({p['quality']}, {p['text_len']} chars) — no facts fabricated.")
                    shown = True
                    break
            if shown:
                break
        if not shown:
            st.caption("No failures recorded — the chart-heavy earnings deck will show honest low-text handling.")

# ---- Collections ----
with tabs[4]:
    st.subheader("Collections")
    rows = [{"name": c["name"], **{k: v for k, v in collection_stats(db, c["id"]).items()}}
            for c in list_collections(db)]
    if rows:
        st.dataframe(rows, width="stretch", hide_index=True)
    else:
        st.info("No collections yet.")
