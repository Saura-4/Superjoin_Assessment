"""Fact Knowledge Layer — Streamlit UI.

High-clarity, provenance-first user interface with executive showcase,
interactive fact explorer, and relationship intelligence.
Works seamlessly in both Light and Dark mode using native Streamlit components.
Run: python -m streamlit run app.py
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pandas as pd
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
    """stdlib .env loader so streamlit picks up local keys."""
    if not os.path.isfile(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()

# Auto-detect pre-built demo DB if present, otherwise default to app.db
DB_PATH = os.environ.get("APP_DB")
if not DB_PATH:
    DB_PATH = "data/run_delhivery.db" if os.path.isfile("data/run_delhivery.db") else "data/app.db"
DATA_DIR = os.environ.get("DATA_DIR", "data/files")


def conn():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    return init_db(DB_PATH)


# ---- Page Setup ----
st.set_page_config(page_title="Fact Knowledge Layer", page_icon="📑", layout="wide")

db = conn()
provider = get_provider(cache_dir="data/llm_cache")

# ---- Sidebar Controls ----
st.sidebar.title("📑 Fact Knowledge Layer")
st.sidebar.caption("Provenance-First Intelligence Engine")
st.sidebar.markdown("---")

cols = list_collections(db)
names = [c["name"] for c in cols]
sel = st.sidebar.selectbox("Active Collection", names + ["+ new collection…"])
if sel == "+ new collection…":
    new_name = st.sidebar.text_input("New collection name", "delhivery")
    if st.sidebar.button("Create"):
        get_or_create_collection(db, new_name)
        st.rerun()
    st.info("Create a collection to begin.")
    st.stop()

col = next(c for c in cols if c["name"] == sel) if cols else get_or_create_collection(db, "delhivery")
scope = st.sidebar.radio("Comparison Scope", ["Current Collection", "All Collections"], index=0,
                         help="Default is current collection. 'All Collections' enables selective cross-collection retrieval.")
st.sidebar.markdown("---")
st.sidebar.caption(f"🤖 **Provider:** `{provider.name}`")
st.sidebar.caption(f"💾 **Database:** `{Path(DB_PATH).name}`")

# ---- Data Pre-loading ----
docs = list_documents(db, col["id"])
doc_names = {d["id"]: d["filename"] for d in docs}
facts_all = list_facts(db, col["id"], limit=3000)
rels_all = list_relationships(db, col["id"], limit=3000)

# Pre-compute document origin lookup
ev_rows = db.execute("SELECT fact_id, page, text, document_id FROM evidence").fetchall()
ev_map = {r["fact_id"]: (doc_names.get(r["document_id"], "Unknown Doc"), r["page"], r["text"]) for r in ev_rows}


def get_fact_meta(fid: str) -> tuple[str, str, str]:
    return ev_map.get(fid, ("Unknown Doc", "?", ""))


# Count cross-document relationships
cross_rels_count = sum(1 for r in rels_all if db.execute(
    "SELECT 1 FROM facts fa, facts fb WHERE fa.id=? AND fb.id=? AND fa.document_id != fb.document_id",
    (r["fact_a_id"], r["fact_b_id"])).fetchone() is not None)

# Header
st.title("Fact Knowledge Layer")
st.caption("A provenance-first intelligence system converting messy financial PDFs into grounded facts and cross-document reasoning.")

# KPI Metric Cards
kpi1, kpi2, kpi3, kpi4 = st.columns(4)
kpi1.metric("📁 Ingested Filings", f"{len(docs)} PDFs")
kpi2.metric("💡 Grounded Facts", f"{len(facts_all):,} Facts")
kpi3.metric("🔗 Discovered Links", f"{len(rels_all):,} Links")
kpi4.metric("🌐 Cross-Doc Insights", f"{cross_rels_count:,} Links")

st.markdown("---")

TYPE_ICONS = {
    "CORROBORATES": "✅ CORROBORATES",
    "CONTRADICTS": "❌ CONTRADICTS",
    "RECONCILED": "⚖️ RECONCILED",
    "TEMPORAL_CHANGE": "⏳ TEMPORAL CHANGE",
    "UNCERTAIN": "❓ UNCERTAIN",
}

# ========================================================
# TABS
# ========================================================
tabs = st.tabs([
    "🌟 Key Discoveries (Showcase)",
    "📊 Fact Explorer & Evidence",
    "🕸️ Relationship Intelligence",
    "📥 Document Ingestion & Audit"
])


# --------------------------------------------------------
# TAB 1: KEY DISCOVERIES
# --------------------------------------------------------
with tabs[0]:
    st.subheader("Key Cross-Document Discoveries")
    st.write("Demonstration cases detected live by comparing facts extracted across different financial filings.")

    showcase_category = st.radio(
        "Select Discovery Category",
        ["All Highlights", "✅ Corroborations", "⏳ Temporal Changes", "⚖️ Reconciliations", "❌ Contradictions", "🛡️ Extraction Failures"],
        horizontal=True
    )

    def render_showcase_card(r: dict):
        a = db.execute("SELECT * FROM facts WHERE id=?", (r["fact_a_id"],)).fetchone()
        b = db.execute("SELECT * FROM facts WHERE id=?", (r["fact_b_id"],)).fetchone()
        if not (a and b):
            return
        file_a, page_a, text_a = get_fact_meta(a["id"])
        file_b, page_b, text_b = get_fact_meta(b["id"])
        is_cross = (file_a != file_b)
        scope_str = "🌐 Cross-Document" if is_cross else "📄 Same-Document"
        type_str = TYPE_ICONS.get(r["type"], r["type"])

        with st.container(border=True):
            col_header1, col_header2 = st.columns([3, 1])
            with col_header1:
                st.markdown(f"**{type_str}**")
            with col_header2:
                st.caption(f"`{scope_str}` · Conf: **{r['confidence']:.2f}**")

            st.info(f"💡 **Reasoning:** {r['reason']}")

            col1, col2 = st.columns(2)
            with col1:
                st.markdown(f"📄 **Source A:** `{file_a}` · Page **{page_a}**")
                st.write(f"• **Claim:** {a['claim']}")
                st.caption(f"Metric: `{a['predicate']}` · Raw: `{a['value_raw']} {a['unit_raw']}` · Norm: `{a['value_norm']}` (Period: `{a['period_norm']}`)")
                if text_a:
                    with st.expander("🔍 View Verbatim Source Quote", expanded=False):
                        st.info(f"❝ *{text_a.strip()}* ❞\n\n— **{file_a}** (p.{page_a})")

            with col2:
                st.markdown(f"📄 **Source B:** `{file_b}` · Page **{page_b}**")
                st.write(f"• **Claim:** {b['claim']}")
                st.caption(f"Metric: `{b['predicate']}` · Raw: `{b['value_raw']} {b['unit_raw']}` · Norm: `{b['value_norm']}` (Period: `{b['period_norm']}`)")
                if text_b:
                    with st.expander("🔍 View Verbatim Source Quote", expanded=False):
                        st.info(f"❝ *{text_b.strip()}* ❞\n\n— **{file_b}** (p.{page_b})")

    def fetch_showcase(rtype: str, limit: int = 2):
        return list_relationships(db, col["id"], rel_type=rtype, limit=limit, cross_doc_only=True) or list_relationships(db, col["id"], rel_type=rtype, limit=limit)

    if showcase_category in ("All Highlights", "✅ Corroborations"):
        st.markdown("#### ✅ Corroborated Across Documents")
        st.caption("Facts from separate documents independently agreeing on numbers after deterministic unit normalization.")
        for r in fetch_showcase("CORROBORATES", 2):
            render_showcase_card(r)

    if showcase_category in ("All Highlights", "⏳ Temporal Changes"):
        st.markdown("#### ⏳ Temporal Evolution Across Documents")
        st.caption("Tracking how the same business metrics evolved over time across the 2021 Prospectus and 2024 Filings.")
        for r in fetch_showcase("TEMPORAL_CHANGE", 2):
            render_showcase_card(r)

    if showcase_category in ("All Highlights", "⚖️ Reconciliations"):
        st.markdown("#### ⚖️ Reconciled by Context & Scope")
        st.caption("Facts that appear conflicting on the surface, but are mathematically reconciled by reporting scope or time granularity.")
        for r in fetch_showcase("RECONCILED", 2):
            render_showcase_card(r)

    if showcase_category in ("All Highlights", "❌ Contradictions"):
        st.markdown("#### ❌ Cross-Document Contradictions")
        st.caption("Genuine numerical discrepancies flagged across reports for identical periods and scopes.")
        for r in fetch_showcase("CONTRADICTS", 2):
            render_showcase_card(r)

    if showcase_category in ("All Highlights", "🛡️ Extraction Failures"):
        st.markdown("#### 🛡️ Extraction Failures")
        st.caption("Scanned pages or chart-heavy graphics that lack extractable text layers are honestly recorded as unprocessable without fabricating facts.")
        fail_pages = [p for d in docs for p in list_page_status(db, d["id"]) if p["status"] in ("empty_no_text", "low_text")]
        if fail_pages:
            for p in fail_pages[:4]:
                doc_name = doc_names.get(p["document_id"], "Unknown")
                with st.container(border=True):
                    st.warning(f"📄 **{doc_name}** · **Page {p['page']}**")
                    st.write(f"• **Status:** `{p['status']}` | Quality: `{p['quality']}` | Extracted text length: `{p['text_len']}` characters.")
                    st.caption("Result: Page gracefully skipped; zero fake facts or hallucinated metrics emitted.")
        else:
            st.info("No failure pages in this collection.")


# --------------------------------------------------------
# TAB 2: FACT EXPLORER (Table + Inspect View)
# --------------------------------------------------------
with tabs[1]:
    st.subheader("Explore All Extracted Facts")
    st.caption("Every fact is extracted with strict schema compliance, deterministic normalization, and verbatim evidence.")

    f_col1, f_col2, f_col3 = st.columns([2, 1, 1])
    with f_col1:
        search_kw = st.text_input("🔍 Search facts", placeholder="Search by metric, subject, or claim (e.g. EBITDA, parcel, revenue)")
    with f_col2:
        doc_choice = st.selectbox("Document Filter", ["All Documents"] + list(doc_names.values()))
    with f_col3:
        periods_available = sorted(list(set(f["period_norm"] for f in facts_all if f["period_norm"])))
        period_choice = st.selectbox("Period Filter", ["All Periods"] + periods_available)

    # Filter logic
    fact_results = facts_all
    if doc_choice != "All Documents":
        target_did = next((did for did, name in doc_names.items() if name == doc_choice), None)
        if target_did:
            fact_results = [f for f in fact_results if f["document_id"] == target_did]

    if period_choice != "All Periods":
        fact_results = [f for f in fact_results if f["period_norm"] == period_choice]

    if search_kw:
        sk = search_kw.lower()
        fact_results = [f for f in fact_results if sk in f"{f['subject']} {f['predicate']} {f['claim']} {f['period_raw']} {f['value_raw']}".lower()]

    st.write(f"Showing **{len(fact_results)}** matching facts")

    # Build clean DataFrame for high-clarity viewing
    df_rows = []
    for f in fact_results:
        f_file, f_page, _ = get_fact_meta(f["id"])
        df_rows.append({
            "ID": f["id"][:8],
            "Document": f_file,
            "Page": f_page,
            "Subject": f["subject"],
            "Metric": f["predicate"],
            "Value": f"{f['value_raw']} {f['unit_raw']}".strip(),
            "Normalized": f"{f['value_norm'] or ''} {f['unit_norm']}".strip(),
            "Period": f["period_norm"] or f["period_raw"],
            "Confidence": round(float(f["confidence"]), 2),
            "_full_id": f["id"],
        })

    if df_rows:
        fact_df = pd.DataFrame(df_rows)
        st.dataframe(
            fact_df[["Document", "Page", "Subject", "Metric", "Value", "Normalized", "Period", "Confidence", "ID"]],
            use_container_width=True,
            hide_index=True,
            height=320,
        )

        st.markdown("### 🔎 Fact Detail & Evidence Inspector")
        fact_options = [f"[{r['Document']} p.{r['Page']}] {r['Subject']} · {r['Metric']} ({r['Value']}) — ID: {r['_full_id'][:6]}" for r in df_rows]
        chosen_label = st.selectbox("Select a fact from above to inspect full source evidence:", fact_options)

        if chosen_label:
            chosen_short_id = chosen_label.split("ID: ")[-1]
            f_selected = next((f for f in fact_results if f["id"][:6] == chosen_short_id), None)
            if f_selected:
                s_file, s_page, s_quote = get_fact_meta(f_selected["id"])

                with st.container(border=True):
                    st.markdown(f"**\"{f_selected['claim']}\"**")
                    st.caption(f"📄 **Source:** `{s_file}` · **Page {s_page}** · Confidence: `{f_selected['confidence']:.2f}`")
                    st.divider()

                    c_m1, c_m2, c_m3, c_m4 = st.columns(4)
                    with c_m1:
                        st.caption("SUBJECT")
                        st.markdown(f"**{f_selected['subject']}**")
                    with c_m2:
                        st.caption("METRIC")
                        st.markdown(f"`{f_selected['predicate']}`")
                    with c_m3:
                        st.caption("NORMALIZED VALUE")
                        norm_val = f"{f_selected['value_norm']:,.2f}".rstrip('0').rstrip('.') if isinstance(f_selected['value_norm'], (int, float)) else str(f_selected['value_norm'] or '—')
                        st.markdown(f"**{norm_val} {f_selected['unit_norm']}**")
                        st.caption(f"Raw: `{f_selected['value_raw']} {f_selected['unit_raw']}`")
                    with c_m4:
                        st.caption("PERIOD & SCOPE")
                        p_str = f_selected['period_norm'] or f_selected['period_raw'] or '—'
                        sc_str = f"({f_selected['scope']})" if f_selected['scope'] else ""
                        st.markdown(f"**{p_str}** {sc_str}")

                    if s_quote:
                        st.markdown("")
                        st.caption("VERBATIM SOURCE EVIDENCE (QUOTE FROM PDF)")
                        st.info(f"❝ *{s_quote.strip()}* ❞\n\n— **{s_file}** (Page {s_page})")

                    # Related links
                    connected_rels = list_relationships_for_fact(db, f_selected["id"])
                    if connected_rels:
                        st.markdown(f"**Connected Relationships ({len(connected_rels)}):**")
                        for cr in connected_rels:
                            other_fid = cr["fact_b_id"] if cr["fact_a_id"] == f_selected["id"] else cr["fact_a_id"]
                            other_f = db.execute("SELECT * FROM facts WHERE id=?", (other_fid,)).fetchone()
                            if other_f:
                                o_file, o_page, _ = get_fact_meta(other_f["id"])
                                is_x = (o_file != s_file)
                                x_label = "🌐 Cross-Doc" if is_x else "📄 Same-Doc"
                                t_label = TYPE_ICONS.get(cr["type"], cr["type"])
                                st.markdown(f"- **{t_label}** ({cr['confidence']:.2f}) · *{x_label}* ↔ `[{o_file} p.{o_page}]` {other_f['claim']}")
                                st.caption(f"  *Reasoning:* {cr['reason']}")
    else:
        st.info("No facts match your search criteria.")


# --------------------------------------------------------
# TAB 3: RELATIONSHIP INTELLIGENCE
# --------------------------------------------------------
with tabs[2]:
    st.subheader("Relationship Intelligence Explorer")
    st.caption("Inspect and filter verified fact-to-fact relationships across filings.")

    r_col1, r_col2, r_col3 = st.columns([2, 1, 1])
    with r_col1:
        rel_kw = st.text_input("🔍 Search relationships", placeholder="Search by topic, entity, or keyword (e.g. revenue, shares, margin)")
    with r_col2:
        rel_type_pick = st.selectbox("Relationship Type", ["All Types", "CORROBORATES", "TEMPORAL_CHANGE", "RECONCILED", "CONTRADICTS", "UNCERTAIN"])
    with r_col3:
        scope_pick = st.selectbox("Link Scope", ["🌐 Cross-Document Only", "All Relationships", "📄 Same-Document Only"])

    # Filtering
    cross_only_flag = True if scope_pick == "🌐 Cross-Document Only" else False
    active_relationships = list_relationships(db, col["id"], limit=3000, cross_doc_only=cross_only_flag)

    if rel_type_pick != "All Types":
        active_relationships = [r for r in active_relationships if r["type"] == rel_type_pick]

    if scope_pick == "📄 Same-Document Only":
        active_relationships = [r for r in active_relationships if not db.execute(
            "SELECT 1 FROM facts fa, facts fb WHERE fa.id=? AND fb.id=? AND fa.document_id != fb.document_id",
            (r["fact_a_id"], r["fact_b_id"])).fetchone()]

    if rel_kw:
        rk = rel_kw.lower()
        active_relationships = [r for r in active_relationships if rk in r["reason"].lower() or rk in r["type"].lower()]

    st.write(f"Found **{len(active_relationships)}** relationships")

    # Clean Pagination with Back / Next
    PAGE_CHUNK = 8
    total_chunks = max(1, (len(active_relationships) + PAGE_CHUNK - 1) // PAGE_CHUNK)

    if "rel_page" not in st.session_state:
        st.session_state.rel_page = 1

    # Keep page in bounds
    st.session_state.rel_page = min(max(1, st.session_state.rel_page), total_chunks)

    col_nav1, col_nav2, col_nav3 = st.columns([1, 2, 1])
    with col_nav1:
        if st.button("⬅️ Previous", disabled=(st.session_state.rel_page <= 1)):
            st.session_state.rel_page -= 1
            st.rerun()
    with col_nav2:
        st.write(f"<p style='text-align: center; margin-top: 8px;'>Page <b>{st.session_state.rel_page}</b> of <b>{total_chunks}</b></p>", unsafe_allow_html=True)
    with col_nav3:
        if st.button("Next ➡️", disabled=(st.session_state.rel_page >= total_chunks)):
            st.session_state.rel_page += 1
            st.rerun()

    start_r = (st.session_state.rel_page - 1) * PAGE_CHUNK
    slice_rels = active_relationships[start_r : start_r + PAGE_CHUNK]

    for r in slice_rels:
        a = db.execute("SELECT * FROM facts WHERE id=?", (r["fact_a_id"],)).fetchone()
        b = db.execute("SELECT * FROM facts WHERE id=?", (r["fact_b_id"],)).fetchone()
        if not (a and b):
            continue
        file_a, page_a, text_a = get_fact_meta(a["id"])
        file_b, page_b, text_b = get_fact_meta(b["id"])
        is_cross = (file_a != file_b)
        scope_tag = "🌐 Cross-Doc" if is_cross else "📄 Same-Doc"
        type_icon_str = TYPE_ICONS.get(r["type"], r["type"])

        with st.container(border=True):
            r_top1, r_top2 = st.columns([3, 1])
            with r_top1:
                st.markdown(f"**{type_icon_str}** | `{scope_tag}` | Conf: `{r['confidence']:.2f}`")
            with r_top2:
                st.caption(f"ID: `{r['id'][:8]}`")

            st.markdown(f"💡 **Reasoning:** {r['reason']}")

            col_a, col_b = st.columns(2)
            with col_a:
                st.markdown(f"📄 **`{file_a}`** (Page {page_a})")
                st.write(f"• **Claim:** {a['claim']}")
                st.caption(f"Metric: `{a['predicate']}` · Raw: `{a['value_raw']} {a['unit_raw']}` · Normalized: `{a['value_norm']}`")
                if text_a:
                    with st.expander("Show Evidence Quote A", expanded=False):
                        st.code(text_a[:350], language="text")

            with col_b:
                st.markdown(f"📄 **`{file_b}`** (Page {page_b})")
                st.write(f"• **Claim:** {b['claim']}")
                st.caption(f"Metric: `{b['predicate']}` · Raw: `{b['value_raw']} {b['unit_raw']}` · Normalized: `{b['value_norm']}`")
                if text_b:
                    with st.expander("Show Evidence Quote B", expanded=False):
                        st.code(text_b[:350], language="text")


# --------------------------------------------------------
# TAB 4: DOCUMENT INGESTION & AUDIT
# --------------------------------------------------------
with tabs[3]:
    st.subheader("Document Ingestion & Pipeline Audit")
    st.caption("Upload new PDF filings or inspect the page extraction health audit.")

    up_c1, up_c2 = st.columns([2, 1])
    with up_c1:
        st.markdown("#### Upload New PDF Filings")
        uploaded_files = st.file_uploader("Upload PDF files (joins active collection incrementally)", type=["pdf"], accept_multiple_files=True)
        max_p = st.slider("Max pages to process per PDF", 1, 100, 15, help="Cost & rate-limit control.")
        if st.button("🚀 Process Documents", disabled=not uploaded_files):
            for f in uploaded_files:
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                    tmp.write(f.read())
                    tmp_path = tmp.name
                with st.spinner(f"Ingesting {f.name}…"):
                    try:
                        res = process_document(db, provider, col["id"], tmp_path, data_dir=DATA_DIR,
                                               max_pages=max_p, scope="current" if scope == "Current Collection" else "all",
                                               filename=f.name)
                        if res["duplicate"]:
                            st.warning(f"📄 **{f.name}**: Duplicate file hash detected. Reused existing facts without re-processing.")
                        else:
                            st.success(f"📄 **{f.name}**: Added +{res['facts_added']} facts, +{res['relationships_added']} relationships.")
                    except Exception as e:
                        st.error(f"Error processing {f.name}: {e}")

    with up_c2:
        st.markdown("#### Collections Summary")
        for c in cols:
            s = collection_stats(db, c["id"])
            with st.container(border=True):
                st.markdown(f"**{c['name']}**")
                st.caption(f"{s['documents']} documents · {s['facts']} facts · {s['relationships']} links")

    st.markdown("---")
    st.markdown("#### Document Page Quality Audit")
    for d in docs:
        pages = list_page_status(db, d["id"])
        good_p = sum(1 for p in pages if p["quality"] == "good")
        low_p = sum(1 for p in pages if p["quality"] == "low")
        empty_p = sum(1 for p in pages if p["quality"] == "empty")
        with st.expander(f"📄 **{d['filename']}** — {d['status']} ({d['num_pages']} pages: {good_p} clean, {low_p} low-text, {empty_p} empty)"):
            page_df_rows = [{"Page": p["page"], "Status": p["status"], "Quality": p["quality"], "Characters": p["text_len"]} for p in pages]
            st.dataframe(pd.DataFrame(page_df_rows), use_container_width=True, hide_index=True, height=200)
