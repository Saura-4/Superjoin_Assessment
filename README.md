# Fact Knowledge Layer — Superjoin VIT 2026 Assignment

Provenance-first prototype: messy PDFs → structured, grounded facts → fact-to-fact
relationships (corroborate / contradict / reconcile) with evidence and explanations.
This is **not** a chatbot, summarizer, or graph-DB demo — the unit is the **fact**,
and every fact links to its source document + page + quote.

## Setup and Run

```bash
python -m venv .venv && .venv\Scripts\activate   # Windows; use source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt

# 1) offline checks (no key needed — MockProvider)
python -m pytest tests/ -q
python evaluations/evaluate.py
python evaluations/verify_delhivery.py

# 2) run the UI
streamlit run app.py
# open the shown localhost URL
```

Optional (real extraction + ambiguous-case judgments; free tier):

```bash
# get a free key at https://aistudio.google.com
set GEMINI_API_KEY=your_key        # Windows cmd; $env:GEMINI_API_KEY="..." in PowerShell
set GEMINI_MODEL=gemini-2.5-flash  # default
set LLM_PROVIDER=gemini
streamlit run app.py
```

Without a key the app runs fully offline on the mock provider (extraction returns
empty, deterministic engine + evaluations still run). No credentials are committed;
see `.gitignore` (`data/`, `*.db`, `.env` excluded).

## Starter data (git-ignored, local-only)

The starter PDF excerpts are intentionally **not** in git. A fresh clone contains
code only. To run dataset-dependent checks, unzip `starter-datasets.zip` (from the
assignment bundle) so this layout exists:

```
unzipped_starter/starter-datasets/delhivery/*.pdf
unzipped_starter/starter-datasets/india-macroeconomy/*.pdf
```

Behavior without the excerpts: `pytest` runs the offline suite and **skips** the 4
dataset tests; `evaluate.py` passes fully offline; `verify_delhivery.py` exits 2
with placement instructions instead of a confusing traceback. The UI works without
them — upload any PDF to a collection.

## Reproducing the four demo cases (Delhivery)

1. Create collection `delhivery` in the sidebar.
2. Upload (Upload tab, max-pages ≈ 15 for a fast free-tier run):
   - `01-delhivery-prospectus-2022-excerpt.pdf`
   - `02-delhivery-annual-report-fy24-excerpt.pdf`
   - `03-delhivery-q4-fy24-earnings-presentation.pdf`
3. Open **Demo Cases** — cases are retrieved live from the DB, never hard-coded:
   - **1 · Corroborated:** FY24 express parcels **740 Mn** — Annual Report text/table vs Earnings deck chart (different wording, same value).
   - **2 · Contradiction / temporal change:** same metric, same scope, different values → `CONTRADICTS`; same metric across 2022→FY24 with changed value → `TEMPORAL_CHANGE` (e.g. director active in 2022 prospectus vs ceased later — judged, not rule-coded).
   - **3 · Reconciled by context:** Q3-FY24 PAT (+₹117M scale) vs FY24 full-year PAT (negative, full-year granularity), or services-only vs total revenue scope — `RECONCILED` with the differing dimension named.
   - **4 · Extraction failure:** chart-heavy earnings-deck pages have empty/low text layers — recorded as `empty_no_text`/`low_text` with no fabricated facts.
4. Click any fact → evidence quote + document/page; related facts show the reason.

`python evaluations/verify_delhivery.py` checks these five behaviors against the real
excerpt texts offline (evidence presence + deterministic decisions + low-text surface).

## Approach / Architecture

```
PDF → hash → page text (PyMuPDF) → quality → LLM extract (1 call/page, JSON) →
validate+ground → normalize (deterministic) → persist fact+evidence →
selective candidates → deterministic decide → LLM judge ONLY if ambiguous →
persist relationship → Streamlit inspect
```

- **PDF processing (local):** page-aware PyMuPDF extraction with `good/low/empty`
  quality, page-text cache on disk, per-page statuses (`page_processing`) so one bad
  page never kills a 100-page doc and retries don't restart the doc.
- **LLM provider boundary (`src/llm.py`):** `LLMProvider` interface + `GeminiProvider`
  (REST, JSON mode, retry/backoff on 429/5xx, disk cache) + `MockProvider` (offline).
  Verified Sept 2026: Gemini API keeps a **$0 Free Tier** on eligible Flash models
  with per-project RPM/RPD caps — hence one small page-slice call at a time, never
  whole-PDF prompts. App logic never imports vendor SDKs; `LLM_PROVIDER`/`GEMINI_API_KEY`
  configure it. See `docs` in `src/llm.py` header.
- **Fact extraction (generic):** single page-slice prompt, max 12 facts, strict JSON
  schema `{subject, predicate, value_raw, unit_raw, period_raw, scope, qualifiers,
  claim, confidence, evidence_quote}`. Validation drops incomplete rows; quotes that
  don't overlap the source get confidence ×0.6 instead of false certainty.
  No filename/page/value rules anywhere.
- **Provenance (first-class):** `evidence(fact_id, document_id, page, text)`; UI shows
  claim + normalized value + source file/page/quote for every fact.
- **Normalization (deterministic, `src/normalize.py`):** Indian + SI scales
  (lakh/crore/Mn/Bn), ₹/INR→absolute, % passthrough, `740 Mn→740,000,000`,
  `₹8,142 Cr≈₹81,420 Mn` (agrees with `₹81,415 Mn` within 0.1%),
  periods `FY 2023-24→FY24`, `Q4 FY24→Q4-FY24`, `March 31, 2024→2024-03-31`.
  Raw values/claims preserved; LLM never does arithmetic.
- **Candidate retrieval (`src/retrieve.py`):** predicate/subject compatibility +
  unit match filter, ranked (predicate > subject > period > cross-doc), capped at 20.
  Scope defaults to current collection; `selected`/`all` still filter selectively —
  enabling cross-collection never means all-vs-all. Embeddings (if ever added) sit
  behind `SemanticIndex` for retrieval only.
- **Relationship reasoning (`src/relate.py`):** deterministic ladder first —
  granularity check (Q3-FY24 vs FY24 → `RECONCILED`), same-period value compare
  within 2% (`CORROBORATES`), scope-explained gaps (`RECONCILED`), cross-period
  numeric change (`TEMPORAL_CHANGE`), same-period conflict (`CONTRADICTS`) —
  then `llm_judge` (facts + evidence snippets only) for semantic/ambiguous pairs.
  Vocabulary is extensible data; demo values are not rules.
- **Incremental (`src/pipeline.py`):** content-hash dedup (re-upload = reuse),
  only **new** facts are compared against relevant existing ones; jobs table tracks
  runs. Large PDFs handled by page slicing + `max_pages` cost control.
- **Comparison scope:** one DB, many collections; `resolve_scope(current|selected|all)`;
  no `if collection == ...` logic exists in the codebase.
- **Storage:** SQLite is the source of truth
  (`collections, documents, facts, evidence, relationships, processing_jobs,
  page_processing`); predicates/relationship types are rows, not columns, so the
  schema evolves as new fact kinds appear. No graph DB — the relationships table
  *is* the graph; visualization is presentation. Page texts + LLM cache live under
  `data/` (git-ignored).

## Data model (key fields)

- `facts`: `subject, predicate, value_raw, value_norm, unit_raw, unit_norm,
  period_raw, period_norm, scope, qualifiers(JSON), claim, confidence`
- `evidence`: `fact_id, document_id, page, text`
- `relationships`: `fact_a_id, fact_b_id (canonical order), type, confidence,
  reason, dimensions(JSON)` — fact-to-fact, never doc-to-doc.

## Provider configuration / environment

| var | default | meaning |
|---|---|---|
| `LLM_PROVIDER` | `mock` (auto→`gemini` when key set) | `mock` \| `gemini` |
| `GEMINI_API_KEY` | — | free key from AI Studio; required for real LLM |
| `GEMINI_MODEL` | `gemini-2.5-flash` | eligible free-tier Flash model |
| `APP_DB` | `data/app.db` | SQLite path |
| `DATA_DIR` | `data/files` | page-text cache |

Cost strategy: local parsing + deterministic math + capped candidates + tiny
page-slice prompts + response cache + LLM-only-when-ambiguous. A 3-doc × 15-page
demo fits comfortably in free-tier quotas (429s are retried with backoff).

## Tests / evaluation

```bash
python -m pytest tests/ -q          # 34 tests; 4 dataset tests skip without local excerpts
python evaluations/evaluate.py      # 19 offline checks from expected_cases.json (never imported by prod code)
python evaluations/verify_delhivery.py  # real-PDF evidence + decision verification
```

## Limitations and Next Steps

- Text-layer only: scanned/chart pages yield `empty/low` honestly; **vision fallback**
  (render page → multimodal extract → same schema + confidence) is the top next step —
  failure taxonomy in `src/failures.py` already reserves the path.
- Mock offline mode extracts nothing (by design — no fabrication); needs key for live facts.
- Retrieval is token-based; a light embedding index (`sqlite-vec`/FAISS) behind
  `SemanticIndex` would help paraphrased predicates at scale.
- No bboxes yet (quotes + page numbers only), no multi-user auth, single SQLite file.
- Next: vision fallback → embedding retrieval → span highlights → eval on
  india-macroeconomy set (GDP vintages/forecast-vs-actual) → batched background jobs.

## Additional Notes

- AI tools used: coding agent for scaffolding/tests; Gemini free tier for extraction/judge design.
- `evaluations/expected_cases.json` contains representative values for tests only —
  production code has zero starter-PDF rules (grep for filenames to confirm).
- Sample flow for graders without a key: run pytest + both evaluation scripts, then
  use the UI with the mock provider to inspect pipeline states, or set the free key
  for the full 4-case demo.

## Before You Submit (grader checklist)

- [x] Runs from instructions, accepts new PDFs via UI
- [x] Facts carry source evidence; relationships are fact-to-fact with reasons
- [x] Four cases retrievable in Demo Cases view
- [x] Approach + limitations documented; video to be recorded (≤3 min: upload → fact → 4 cases)
