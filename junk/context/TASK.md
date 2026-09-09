# TASK.md — Muse Implementation Plan

## Instructions to Muse

Implement this project incrementally according to `PROJECT_CONTEXT.md`.

Do NOT build the entire application in one pass.

For every task:
1. Inspect the repository before changing it.
2. Implement only the requested scope.
3. Run relevant tests/checks.
4. Report files changed, implementation, verification, decisions, risks, and next task.
5. Do not make large architectural decisions outside the requested scope without reporting them.
6. Never hard-code starter PDF facts, filenames, page numbers, or dataset names.
7. Do not claim functionality that was not tested.

---

# Phase 0 — Reconnaissance

Inspect:
- repository structure
- existing framework/dependencies
- entrypoints
- existing functionality
- starter/sample data

Do not modify code.

Report current stack, structure, useful existing work, conflicts with PROJECT_CONTEXT.md, and recommended starting point.

---

# Task 1 — Foundation / Database

Implement a clean project structure and SQLite persistence for:

- collections
- documents
- facts
- evidence
- relationships
- processing jobs
- page processing if appropriate

Support:
- one DB
- many collections
- many documents/collection
- many facts/document
- multiple evidence/fact
- fact-to-fact relationships
- extensible predicates
- extensible relationship types
- document hashes
- processing status

Keep persistence separate from business logic.

Do not implement LLM calls or UI yet.

Add basic database CRUD tests.

---

# Task 2 — PDF Ingestion

Implement:

PDF → content hash → document registration → page count → page text extraction → extraction quality → persistence

Use a reliable local parser such as PyMuPDF unless an existing project choice is better justified.

Requirements:
- page-aware extraction
- page numbers preserved
- extracted text preserved
- low/empty text detection
- malformed PDF handling
- duplicate detection by hash
- no whole-PDF LLM prompts

Add tests for extraction, page numbering, duplicate detection, and low-text detection.

---

# Task 3 — LLM Provider Boundary

Create a small `LLMProvider` interface plus:
- one real provider
- mock provider

Support structured generation needed by extraction/reasoning.

Requirements:
- no vendor SDK calls scattered through application logic
- configuration via environment/config
- no committed secrets
- validate structured output
- controlled provider errors
- leave room for retry/rate-limit/cache/fallback

Verify current provider pricing/limits before selecting the real provider.

Do not create an oversized provider framework.

---

# Task 4 — Generic Fact Extraction

Extract meaningful numerical or semantic facts from page/section text.

Fact output should support:

- subject
- predicate
- value
- unit
- period
- scope
- qualifiers
- claim
- confidence
- evidence reference

Requirements:
- generic, not document-specific
- grounded only in supplied source text
- preserve source wording
- validated structured output
- confidence
- controlled malformed-response handling

Do not hard-code Delhivery facts/rules.

Text-based extraction first; vision later.

---

# Task 5 — Provenance

Make evidence first-class.

Every successful fact must have evidence containing at least:
- document ID
- page
- source text

Optional:
- bounding box

Implement retrieval:

fact → evidence → source document/page

Add tests proving facts are traceable.

---

# Task 6 — Deterministic Normalization

Implement reusable normalization for as many of these as practical:

- million/billion/trillion
- lakh/crore
- INR scales
- percentages
- numeric strings
- fiscal years
- quarters
- dates

Examples:
- 740 Mn → 740000000
- ₹8,142 Cr → approximately ₹81,420 Mn
- ₹81,415 Mn → ₹8,141.5 Cr

Preserve original extracted value and claim.

Do not use an LLM for arithmetic/unit conversion.

Add strong unit tests.

---

# Task 7 — Candidate Retrieval

Implement selective fact candidate retrieval.

Never compare every fact to every fact.

Initial retrieval should consider:
- same/compatible subject
- same/similar predicate
- compatible scope
- compatible period
- collection comparison scope

If semantic retrieval is useful, put it behind an abstraction.

Embeddings are retrieval only, not final relationship classification.

Keep SQLite as source of truth.

Do not introduce Chroma/vector infrastructure unless clearly justified at this stage.

Add candidate-retrieval tests.

---

# Task 8 — Relationship Engine

Implement:

candidate facts
→ deterministic context checks
→ normalization/value comparison
→ contextual comparison
→ LLM judge only when ambiguous
→ relationship + confidence + explanation

Initial relationship vocabulary may include:
- CORROBORATES
- CONTRADICTS
- RECONCILED
- TEMPORAL_CHANGE
- UNRELATED
- UNCERTAIN

Reasoning must consider:
- period
- granularity
- units
- scope
- predicate semantics
- qualifiers
- temporal changes

The engine must be generic and must not contain the Delhivery demo cases as rules.

Add tests for deterministic relationship behavior.

---

# Task 9 — Incremental Processing

Implement:

upload → hash → reuse if already processed, otherwise process → extract new facts → compare new facts with relevant existing facts → add relationships

Do not rebuild the full knowledge base for each new PDF.

Make page/document processing resumable enough that a failed page can be retried.

Do not introduce distributed infrastructure.

---

# Task 10 — Collections / Comparison Scope

Implement:
- create collection
- select collection
- upload PDFs
- view documents
- view facts
- view relationships

Comparison scope:
- This collection
- Selected collections
- All collections

Default to current collection.

Cross-collection comparison must still use selective candidate retrieval.

Never use collection names for special behavior.

---

# Task 11 — UI

Build a simple functional UI using the existing framework if possible.

Required journey:

Collection → Upload → Processing status → Facts → Fact Detail → Evidence → Related Facts → Relationship explanation

Views:

### Collections
Name, document count, fact count, relationship count.

### Collection
Documents, status, upload, comparison scope.

### Facts
Search/filter, claim/value, period, confidence, relationship status.

### Fact Detail
Structured fact, original claim, normalized value, period, scope, confidence, source/page/evidence, related facts, explanation.

### Relationships
Fact A, relationship, Fact B, reason, confidence.

### Demo Cases
A dedicated view that retrieves and displays actual detected cases. Do not hard-code the results.

---

# Task 12 — Extraction Failure / Vision

Inspect starter PDFs for low-text/chart-heavy pages.

At minimum:
- detect low extraction quality
- mark page/facts uncertain or failed
- explain why
- never fabricate facts

If time/API budget allows, add vision fallback:

page render → vision provider → structured facts → evidence + confidence

Vision is optional; safe failure behavior is mandatory.

---

# Task 13 — Evaluation

Create:

    evaluations/
      expected_cases.json
      evaluate.py

Cover:
- corroboration
- temporal change
- contextual reconciliation
- numerical normalization
- extraction failure

Add deterministic tests for:
- normalization
- unit conversion
- fiscal periods
- candidate filtering
- relationship logic

The evaluation data must not become production hard-coding.

---

# Task 14 — Delhivery Demo Verification

Using the actual starter PDFs, verify:

1. 740 Mn FY24 parcels across two documents → CORROBORATES
2. Director status across 2022 prospectus and later annual report → temporal change/reconciliation
3. Q3 FY24 PAT vs FY24 full-year result → RECONCILED_BY_TIME / RECONCILED
4. Chart/image-heavy page → honest extraction failure/uncertainty
5. ₹81,415 Mn vs ₹8,142 Cr revenue → CORROBORATES after normalization/rounding

Do not add special code for these examples.

---

# Task 15 — README / Submission Readiness

README must include:
1. Setup / Run
2. Architecture / Approach
3. Data model
4. Fact extraction
5. Provenance
6. Normalization
7. Relationship reasoning
8. Incremental processing
9. Comparison scope
10. Limitations
11. Next steps
12. Reproducing four demo cases
13. Provider configuration
14. Environment variables
15. Tests/evaluation

No credentials.

Verify clean setup from README instructions.

---

# Priority

## P0
- ingestion
- fact extraction
- evidence
- normalization
- candidate retrieval
- relationship engine
- four cases

## P1
- SQLite persistence
- collections
- incremental processing
- UI
- evaluation/tests

## P2
- vision fallback
- richer retrieval
- page highlighting
- graph visualization
- additional dataset polish

Core correctness takes priority over optional features.

---

# Final Quality Checklist

[ ] New unseen PDF can be uploaded
[ ] No document-specific hard-coding
[ ] Every successful fact has source evidence
[ ] Original claims preserved
[ ] Units/periods normalized
[ ] Candidate retrieval is selective
[ ] Relationships are fact-to-fact
[ ] Context prevents false contradictions
[ ] LLM is not used for deterministic arithmetic
[ ] Duplicate PDFs detected by hash
[ ] New PDFs do not require full rebuild
[ ] Extraction failures are surfaced honestly
[ ] Four assignment cases work
[ ] Tests pass
[ ] README reproduces project
[ ] No secrets committed
[ ] Architecture remains understandable

---

# Communication Protocol

After each task, report exactly:

## Completed
- ...

## Files Changed
- ...

## Verification
- Commands/tests run
- Results

## Decisions
- ...

## Issues / Risks
- ...

## Next Recommended Task
- ...

---

# Agent Execution Log (handoff — newest entries at bottom)

## 2026-09-07 — Builder agent (Tasks 0–15 COMPLETE, all green)
- Implemented full pipeline per PROJECT_CONTEXT.md: `src/{db,ingest,llm,normalize,extract,retrieve,relate,pipeline,failures}.py` + `app.py` (Streamlit) + 7 test files + `evaluations/{expected_cases.json,evaluate.py,verify_delhivery.py}` + README + `.gitignore`.
- Verification: `pytest tests/` 32 passed · `evaluate.py` 19 checks passed · `verify_delhivery.py` passed on real excerpts.
- Key decisions: Gemini `gemini-2.5-flash` free tier; PyMuPDF; SQLite only; Streamlit; MockProvider offline fallback. Zero hard-coded starter facts (grep-verified pattern: no filenames/values in `src/`).
- Repo pushed to https://github.com/Saura-4/Superjoin_Assessment (`main`). Starter PDFs/zip are git-ignored (local-only); a fresh clone needs the excerpts at `unzipped_starter/` to run `verify_delhivery.py`.
- DO NOT re-implement. Open items for next agent/user: (1) set GEMINI_API_KEY, run full 3-doc extraction; (2) record ≤3-min demo video, add link to README; (3) fill video + repo links in the submission form.
