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

Use embeddings or another semantic index only to find potentially related facts.

### Level 4 — LLM judgment

Use an LLM for genuinely ambiguous semantic/contextual cases.

Provide Fact A, its evidence, Fact B, its evidence, and relevant context—not entire PDFs.

## 9. PDF Processing

Process PDFs page/section-wise.

Pipeline:

PDF → page extraction → extraction quality → fact extraction → evidence → normalization → persistence

Architecture should support large PDFs, multiple PDFs, resumability, and future parallelism without introducing unnecessary distributed infrastructure.

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

Current pricing/limits must be checked against current provider documentation before locking a provider.

## 12. Cost Strategy

Target free or very low cost.

Prefer:
- local PDF parsing
- deterministic normalization
- local/inexpensive embeddings
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
Chart/visual-heavy earnings-presentation pages can be poorly represented by the PDF text layer.

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

## 19. Definition of Done

A user can:

Create collection → upload PDFs → process → inspect facts → open evidence → see normalized context → discover related facts → understand relationships → inspect failures/uncertainty.

The system accepts unseen PDFs and demonstrates the four required cases without special-casing them.

The repository runs from README instructions, accepts new PDFs, shows evidence and cross-document relationships, and explains limitations/next steps.
