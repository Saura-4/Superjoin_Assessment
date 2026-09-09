# Project Context — Superjoin Fact Knowledge Layer

## 1. Goal

Build the Superjoin engineering assignment as a small, understandable but technically thoughtful prototype of a **provenance-first Fact Knowledge Layer**.

Core idea:

> Turn messy PDF documents into structured, grounded facts, then determine how facts from different sources relate to one another.

This is NOT primarily a PDF chatbot, generic RAG app, summarizer, or knowledge-graph demo.

Core pipeline:

Documents → Fact Extraction → Evidence/Provenance → Normalization → Candidate Fact Retrieval → Relationship Analysis → Explanation → UI

The assignment prioritizes grounded facts, source evidence, corroboration/contradiction/contextual reconciliation, uncertainty, generalization, and thoughtful engineering tradeoffs.

The system must not hard-code starter-PDF facts, filenames, schemas, page numbers, or document-specific rules.

## 2. Product Mental Model

The fundamental unit is a **fact**, not a document.

A document is a source of facts.

Example:

Annual Report FY24
→ Fact: Delhivery shipped 740 Mn express parcels in FY24
→ Evidence: page + source text

Another document may contain the same fact.

The relationship is between the two facts:

Fact A ── CORROBORATES ── Fact B

The PDFs themselves are not directly classified as corroborating PDFs.

## 3. Collections

Use one logical knowledge database.

Collections are organizational and default comparison-scope units.

Example:

Delhivery
- Prospectus 2022
- Annual Report FY24
- Q4 FY24 Earnings Presentation

India Macroeconomy
- Economic Survey 2024-25
- RBI Annual Report 2024-25
- IMF Article IV 2025

Do NOT create one database per collection.

The UI should support comparison scope such as:

- This collection
- Selected collections
- All collections

Default: current collection.

Cross-collection comparison must remain selective through candidate retrieval; enabling it must NOT mean comparing every fact with every fact.

Do not use collection names to trigger special behavior. Never write logic such as `if collection == "Delhivery"`.

## 4. Core Data Model

Use one stable, extensible fact envelope:

    fact_id
    document_id
    subject
    predicate
    value
    unit
    period
    scope
    qualifiers
    claim
    confidence

Examples:

    subject = Delhivery
    predicate = revenue_from_services
    value = 81415
    unit = INR_MILLION
    period = FY24

Predicates are data, not database columns.

Do not create fixed columns such as revenue, parcels, EBITDA, employees, directors.

Recommended logical tables:

    collections
    documents
    facts
    evidence
    relationships
    processing_jobs
    page_processing (optional)

## 5. Provenance / Evidence

Evidence is first-class:

    evidence_id
    fact_id
    document_id
    page
    text
    bbox (optional)

Every extracted fact must be traceable to source evidence.

Fact detail should show the source document, page, evidence text, and, where practical, a rendered source page/highlight.

Never present an LLM-generated fact without provenance.

## 6. Relationships

Relationships connect facts, not documents.

Recommended structure:

    relationship_id
    fact_a_id
    fact_b_id
    type
    confidence
    reason
    created_at

Initial vocabulary may include:

    CORROBORATES
    CONTRADICTS
    RECONCILED
    TEMPORAL_CHANGE
    UNRELATED
    UNCERTAIN

Keep the vocabulary extensible.

Do not assume every similar fact is corroborating or contradicting.

## 7. Relationship Reasoning

Never compare every fact with every other fact.

Use:

    facts
      ↓
    candidate retrieval
      ↓
    context compatibility
      ↓
    deterministic comparison
      ↓
    LLM judgment only when needed
      ↓
    relationship + explanation

Embeddings, if used, are for candidate retrieval—not final relationship classification.

## 8. Hybrid Reasoning Ladder

### Level 1 — Deterministic context

Compare subject, predicate, period, scope, and qualifiers.

### Level 2 — Deterministic normalization

Normalize units, currencies, number scales, dates, fiscal periods, and names where appropriate.

Examples:

    740 Mn → 740,000,000
    ₹8,142 Cr → approximately ₹81,420 Mn
    ₹81,415 Mn → ₹8,141.5 Cr

Preserve original values/claims.

### Level 3 — Semantic candidate retrieval

Semantic retrieval is an **optional extension**, not a claim that the current prototype has a production embedding index. The current implementation uses selective deterministic/token-based candidate retrieval behind a retrieval abstraction.

If embeddings are later added, they must be used only for candidate generation/ranking, never as the final relationship classifier.

### Level 4 — LLM judgment

Use an LLM for genuinely ambiguous semantic/contextual cases.

Provide Fact A, its evidence, Fact B, its evidence, and relevant context—not entire PDFs.

## 9. PDF Processing

The current baseline is **page-aware processing**. It is not yet a sophisticated section-aware semantic chunking system.

Pipeline:

PDF → page extraction → extraction quality → fact extraction → evidence → normalization → persistence

Architecture should support large PDFs, multiple PDFs, resumability, and future parallelism without introducing unnecessary distributed infrastructure.

The extraction layer bounds the source text supplied to the model and preserves page provenance. More advanced section-aware chunking should be added only if real PDFs demonstrate that page-level context is insufficient.

Track page status when practical:

    document_id
    page
    status
    attempts
    error

If one page fails, it should eventually be retryable without restarting the entire document.

## 10. Incremental Ingestion

Use document content hashes.

Flow:

upload → hash → already processed?
- yes: reuse
- no: process → extract new facts → compare new facts with relevant existing facts → add relationships

Do not rebuild all knowledge/relationships for every new PDF.

## 11. LLM Provider Architecture

Use a small provider boundary:

    LLMProvider
      ├── real provider
      └── MockProvider

Application logic must not depend directly on vendor SDKs.

Provider boundary should leave room for structured output, retries, rate limiting, caching, and future provider fallback.

Start with one real provider plus a mock. Do not build a large provider framework.

Current provider configuration and pricing/limits must be checked against current provider documentation before final submission claims are made.

## 12. Cost Strategy

Target free or very low cost.

Prefer:
- local PDF parsing
- deterministic normalization
- local/inexpensive embeddings if later justified
- SQLite
- caching
- LLM calls only where judgment is needed

Do not use LLMs for arithmetic/unit conversion/obvious equality.

Spend model capacity on semantic extraction, ambiguous relationship reasoning, contextual explanation, and optional vision fallback.

## 13. Storage

SQLite is the source of truth for the prototype.

Potential embedding index can be separate.

Possible future choices:
- Chroma
- FAISS
- sqlite-vec
- another vector index

Do not introduce a graph database.

A graph visualization can be generated from the relationships table later; it is presentation, not the core knowledge layer.

## 14. UI / End Product

User journey:

1. Create/select collection
2. Upload PDFs
3. Process
4. Inspect facts
5. Open source evidence
6. See normalized values/context
7. Discover related facts
8. Understand why they corroborate, contradict, or reconcile

Suggested views:

### Collections
Collection name, document count, fact count, relationship count.

### Collection/Documents
Documents, processing status, upload control, comparison scope.

### Facts
Search/filter, claim/value, period, confidence, relationship status.

### Fact Detail
Structured fact, original claim, normalized value, period, scope, confidence, source, page, evidence, related facts, explanation.

### Relationships
Fact A ↔ relationship ↔ Fact B, reason, confidence.

### Demo Cases
Dedicated view for the four assignment cases.

## 15. Known Delhivery Demo Cases

These guide evaluation but MUST NOT be hard-coded into production logic.

### Case 1 — Corroboration
FY24 express parcel shipments:
- Annual Report FY24: 740 Mn
- Q4 FY24 Earnings Presentation: 740 Mn

Expected: CORROBORATES.

### Case 2 — Temporal change / apparent contradiction
2022 Prospectus lists a director; later Annual Report records that person ceasing to be a director.

Expected: TEMPORAL_CHANGE or temporal reconciliation rather than blindly claiming contradiction.

### Case 3 — Contextual reconciliation
- Q3 FY24 PAT: +₹117M
- FY24 full-year result: -₹2,491.86M

Expected: RECONCILED because reporting periods/granularity differ.

### Case 4 — Extraction failure
Chart/visual-heavy pages can be poorly represented by the PDF text layer.

Expected: detect low extraction quality, avoid fabricated facts, surface uncertainty/failure, and optionally support vision fallback.

### Additional normalization showcase
- Annual Report: ₹81,415 Mn revenue from services
- Earnings Presentation: ₹8,142 Cr revenue from services

Expected: CORROBORATES after normalization/rounding.

## 16. Evaluation

Evaluation should be first-class.

Suggested:

    evaluations/
      expected_cases.json
      evaluate.py

Cover:
- corroboration
- temporal change/contradiction
- contextual reconciliation
- numerical normalization
- extraction failure

Also test deterministic normalization, unit conversion, fiscal periods, candidate filtering, and relationship logic.

## 17. Failure Handling

Distinguish:

- extraction failure
- fact extraction failure
- normalization failure
- retrieval failure
- reasoning uncertainty

Expose uncertainty rather than fabricating certainty.

## 18. Engineering Principles

Prioritize:
1. Correctness over feature count
2. Provenance over impressive-looking output
3. Deterministic logic before LLM reasoning
4. Small interfaces over vendor coupling
5. Incremental processing over full rebuilds
6. Explainability over black-box classifications
7. Evaluation/testability over demo-only behavior
8. Generalization over starter-PDF hacks
9. Simple architecture over unnecessary infrastructure

Avoid authentication, Kubernetes, microservices, graph databases, elaborate frontend architecture, distributed queues, and excessive UI polish unless genuinely required.

## 19. Current Implementation Status — 2026-09-07

The original implementation plan in `context/TASK.md` has been completed. **Do not amend `TASK.md` for post-implementation work.**

The repository currently contains the working prototype and has been pushed to GitHub.

Verified locally with the starter PDFs supplied separately:

- `pytest -q` → **32 passed**
- `python evaluations/evaluate.py` → **19 checks passed**
- `python evaluations/verify_delhivery.py` → **DEMO VERIFICATION PASSED**

The verification covered corroboration, numerical normalization, contextual reconciliation, temporal change, and extraction-failure handling.

Starter PDFs are intentionally kept out of Git and remain git-ignored/local-only. This is expected. The repository is not empty and should not be treated as a blank starter repository.

### Implemented now

- SQLite persistence
- collections/documents/facts/evidence/relationships
- content-hash duplicate detection
- page-aware PDF extraction
- extraction-quality/failure handling
- generic structured fact extraction
- evidence grounding
- deterministic normalization
- selective deterministic candidate retrieval
- relationship engine with deterministic reasoning and LLM fallback
- incremental processing
- comparison scope
- Streamlit UI
- mock + real LLM provider boundary
- evaluation suite
- Delhivery verification script
- README/setup documentation

### Not yet proven to be necessary / not currently implemented as full features

- production-grade embedding/vector retrieval
- sophisticated semantic section chunking
- vision fallback
- page bounding-box highlighting
- graph visualization

These are optional extensions. They must not be added merely to make the architecture sound more advanced.

## 20. Post-Implementation Work

The next phase is defined in **`context/TASK2.md`**.

`TASK2.md` is the active Muse instruction file for hardening and submission readiness. It starts with a full codebase audit and then prioritizes:

1. clean setup/reproducibility
2. real three-PDF LLM run
3. fact/evidence quality inspection
4. relationship-quality inspection
5. four mandatory demo cases
6. UI end-to-end verification
7. evaluation hardening
8. truthful README/submission preparation
9. ≤3-minute demo video

Do not jump directly to embeddings, vision, or frontend redesign before these P0 checks are complete.

## 21. Definition of Done

A user can:

Create collection → upload PDFs → process → inspect facts → open evidence → see normalized context → discover related facts → understand relationships → inspect failures/uncertainty.

The system accepts unseen PDFs and demonstrates the four required cases without special-casing them.

The repository runs from README instructions, accepts new PDFs, shows evidence and cross-document relationships, and explains limitations/next steps.

For final submission, the reviewer should be able to understand what is implemented, reproduce the core workflow, see the four mandatory cases, and clearly distinguish implemented functionality from optional future improvements.

## 22. Implementation Status — 2026-09-08 (Phase C run + TASK3 hybrid pilot)

Supersedes the counts in §19 with verified live numbers. `context/TASK.md` remains unchanged.

### Keyed run (local `data/run_delhivery.db`, git-ignored)

- 227/227 pages ingested; **1652 facts + 1652 evidence rows**, 357 distinct predicates
- **572+ relationships**; confidence recalibrated (cap 0.9 single-source, quote-strength
  rules, corroboration bump; zero facts at 1.0); 121 date facts renormalized to DATE unit
- 3 honest chart-page extraction failures (deck pp. 2, 4, 18), nothing fabricated
- Four demo cases verified present with evidence (see `context/REPORT.md` §2).
  Textbook Q3-PAT pair is weak in the data — use revenue-scope/appointment cases for the demo.

### Providers (all behind `LLMProvider`; `src/llm.py`)

- Gemini `gemini-3.1-flash-lite` primary (15 RPM pacing, key+model failover, dead-combo
  circuit breaker, disk cache, browser User-Agent); fallbacks 3.5-flash-lite → 3.6/3.7/3.8.
- Groq `llama-3.3-70b-versatile` supported (OpenAI-compat JSON mode, 30 RPM pacing,
  fallback `llama-3.1-8b-instant`); selected via `LLM_PROVIDER=groq` + `GROQ_API_KEY`.
  No live Groq key available yet — offline-tested only.
- Cerebras probed and parked: Cloudflare 1010 was a Python-UA edge block (fixed with
  browser UA), underneath which the account returns 402 payment_required. Needs billing;
  provider NOT implemented (no untested code).

### Hybrid retrieval pilot (TASK3, `context/TASK3.md`)

- `src/embed.py` (`semantic_text`, `HashEmbedder`, `GeminiEmbedder`), model locked to
  **`gemini-embedding-2`** (code-enforced, never switch — vectors incomparable across models)
- `fact_embeddings` table (auxiliary; SQLite stays source of truth; no vector DB)
- Real `SemanticIndex` (in-process cosine) + `hybrid_retrieve` (lexical ∪ semantic,
  dedupe, self/same-doc exclusion) + deterministic `rerank_score`
- Deterministic 300-fact eval set (`src/evalset.py`, 100/doc stratified) + runner
  (`evaluations/hybrid_eval_300.py`, LLM dry-run by default)
- Live pilot: 300 embedded; lexical 2099 / semantic 2102 / merged 2553; rerank kept 724;
  deterministic 20; **LLM would-call 704**; semantic-only found real pairs lexical missed
  (e.g. differing address wordings corroborated, s=1.0)
- **Gate verdict: DO NOT SCALE.** Noise baseline (`acquired_entity ↔ fleet_size`) scores
  cos 0.777 — within one company's filings everything is semantically close, so cosine
  alone can't discriminate and rerank 0.4 lets mush through. Required before scaling:
  period/unit prefilter ahead of cosine + tighter rerank. Remaining ~1350 embeddings
  intentionally deferred (vectors stay valid whenever added: same model + text_hash guard).

### Design rules locked by evidence this phase

- LLM judges **cross-document pairs only**; same-doc ambiguity is skipped (no LLM, no row).
- Diff-predicate pairs reach the judge only with agreeing values or periods.
- Zero-overlap subjects with different values are UNRELATED deterministically.
- Dates never normalize to day-numbers (DATE unit; semantic comparison only).
- Confidence is earned by evidence (cap/bump/migration), never asserted by the model.

### Verification

- `pytest` → **67 passed**; `evaluate.py` → 19/19; `verify_delhivery.py` passes with local excerpts.
- Known unaudited area: post-gate CONTRADICTS sample (~130) — spot-check before filming.
- Next: retrieval-precision fix → re-run 300 gate → UI pass → README final → ≤3-min video → submission.
