# TASK2.md — Muse Hardening, Verification & Submission Plan

## Purpose

`TASK.md` is the original implementation plan and is intentionally left unchanged.

This file is the **post-implementation execution plan** for the next phase. The core prototype already exists. Muse must now harden, verify, and demonstrate the existing system rather than rebuild it from scratch.

The goal is to turn the working prototype into a reliable, honest, reviewer-friendly submission for the Superjoin assignment.

---

# 1. Current State

The repository already contains the core Fact Knowledge Layer implementation:

- SQLite persistence
- collection/document/fact/evidence/relationship model
- page-aware PDF ingestion
- content-hash duplicate detection
- generic LLM fact extraction
- provenance/evidence storage
- deterministic normalization
- selective candidate retrieval
- deterministic relationship reasoning with LLM fallback
- incremental processing
- collections and comparison scope
- Streamlit UI
- failure handling
- automated evaluation
- Delhivery verification script
- README and setup documentation

The implementation has already passed the available automated checks when the starter PDFs are supplied locally:

- `pytest -q` → 32 passed
- `python evaluations/evaluate.py` → 19 checks passed
- `python evaluations/verify_delhivery.py` → passed

Starter PDFs are intentionally **not committed to Git**. They are local/git-ignored test data. Do not remove this design merely to make the repository appear self-contained.

A fresh clone may therefore not contain the starter PDFs. README/setup instructions must make this explicit and provide a clear path for a reviewer to supply them.

---

# 2. Important Reality Check

Do not claim functionality that is not actually implemented.

Two architectural items need particular verification:

### 2.1 Retrieval

The current retrieval layer provides selective deterministic/token-based candidate retrieval and has a semantic-index abstraction/stub. It does **not** currently provide a production-grade embedding/vector search implementation.

Do not describe the current system as having real embedding-based hybrid retrieval unless it is actually implemented and tested.

First determine whether the current deterministic retrieval is sufficient for the assignment's starter cases and unseen-document behavior. Add embeddings only if testing shows a meaningful retrieval gap.

### 2.2 Chunking

The current extraction flow is page-aware. It is not yet a sophisticated section-aware semantic chunking system.

Do not add complex chunking merely for terminology. First inspect real extraction quality on the starter PDFs and determine whether page-level context is sufficient. If chunking is improved, preserve page provenance and avoid losing surrounding context.

---

# 3. Operating Rules for Muse

For every task:

1. Inspect the relevant existing code first.
2. Make the smallest change that solves the verified problem.
3. Do not rewrite working modules without evidence.
4. Run targeted tests after each change.
5. Run the full suite before considering the task complete.
6. Do not hard-code document names, facts, values, pages, or demo outputs into production logic.
7. Keep starter PDFs local/git-ignored.
8. Do not add unnecessary infrastructure.
9. Report files changed, tests run, decisions, risks, and remaining work.
10. If a proposed improvement is not justified by evidence, leave the code alone and record it as a possible future improvement.

---

# Phase A — Full Codebase Audit

## Task A1 — Audit before modifying

Read every source file, test, evaluation script, README, and context file.

Produce an audit covering:

- `app.py`
- `src/db.py`
- `src/ingest.py`
- `src/llm.py`
- `src/normalize.py`
- `src/extract.py`
- `src/retrieve.py`
- `src/relate.py`
- `src/pipeline.py`
- `src/failures.py`
- all tests
- all evaluation scripts
- README

For each module, identify:

- responsibility
- inputs/outputs
- important invariants
- error paths
- coupling
- suspicious assumptions
- missing tests
- places where claims in README differ from actual behavior

Do not make broad changes during this audit.

### Deliverable

Create a short audit note in `context/` only if useful. Do not modify `TASK.md`.

---

# Phase B — Clean Setup & Repository Reproducibility

## Task B1 — Verify clean clone behavior

Test the repository from a clean environment as closely as practical.

Verify:

- dependencies install
- application starts
- database initializes
- UI loads
- a new PDF can be uploaded
- starter PDFs are optional local test data
- tests that do not require starter PDFs pass without them
- Delhivery verification clearly reports missing local data rather than failing confusingly

Do not commit the starter PDFs.

If the current README is unclear, improve it.

## Task B2 — Make test/data expectations explicit

Separate tests into:

- unit/integration tests that run from repository contents
- optional dataset verification requiring local starter PDFs

Avoid making the whole test suite depend on files that are intentionally git-ignored.

The reviewer should understand exactly what they need to place locally.

---

# Phase C — Real Starter-PDF Run

## Task C1 — Run the actual pipeline with the three starter PDFs

With the real API key configured locally, process all three starter PDFs through the application pipeline.

Record:

- processing time per document
- page counts
- pages with low/empty extraction
- number of extracted facts
- number of evidence records
- number/type of relationships
- provider errors/retries if any
- suspicious extraction outputs

Do not put the API key in Git.

## Task C2 — Inspect fact quality manually

Sample facts from every starter document.

Check:

- subject correctness
- predicate usefulness
- numeric value correctness
- unit correctness
- period correctness
- scope/qualifier quality
- claim preservation
- confidence calibration
- evidence quote grounding

Look specifically for:

- hallucinated facts
- duplicate facts
- truncated claims
- wrong units
- wrong fiscal periods
- evidence that does not actually support the fact

Fix only demonstrated problems.

---

# Phase D — Provenance & Evidence Hardening

## Task D1 — Evidence integrity

Every persisted fact must have usable evidence.

Verify:

fact → evidence → document → page

No successful fact should appear without evidence.

If evidence grounding fails, the system must lower confidence or reject the fact rather than silently accept unsupported output.

## Task D2 — Evidence UX

In the UI, make source provenance obvious:

- document name
- page number
- original evidence text
- normalized fact
- confidence

If practical, link/open the relevant source page. Do not sacrifice correctness for visual polish.

---

# Phase E — Relationship Quality

## Task E1 — Verify the reasoning ladder

For representative fact pairs, verify the engine follows:

candidate retrieval
→ context compatibility
→ deterministic normalization/comparison
→ contextual reconciliation
→ LLM fallback only when ambiguity remains

The LLM must not be used for obvious arithmetic or unit conversion.

## Task E2 — Inspect false positives

Review relationships produced from the real starter run.

Look for:

- different metrics incorrectly matched
- different scopes treated as contradictions
- quarter vs full-year confusion
- adjusted vs unadjusted metrics confused
- different entities incorrectly linked
- same-looking numbers with different meanings

Improve candidate filters or deterministic context rules only when a real failure demonstrates the need.

## Task E3 — Preserve explainability

Every non-trivial relationship should have:

- relationship type
- confidence
- concise reason

The reason should be understandable without reading implementation code.

---

# Phase F — Four Mandatory Demo Cases

The demo must emerge from actual processing, not hard-coded production results.

Verify these cases using the starter PDFs:

### Case 1 — Corroboration

A numerical fact appears in two documents with compatible meaning, even if representation differs.

Target example: FY24 express parcel shipments.

### Case 2 — Genuine/likely contradiction or temporal change

A fact changes across documents/time.

Target example: director status between the 2022 prospectus and later annual reporting.

### Case 3 — Apparent contradiction explained by context

Two values look inconsistent but differ by period, scope, unit, definition, or granularity.

Target example: quarterly PAT versus full-year result.

### Case 4 — Extraction/reasoning failure

A chart/image-heavy page is difficult for the text extractor.

The system must surface uncertainty/failure honestly rather than fabricate a result.

Also verify the revenue normalization showcase:

- ₹81,415 Mn
- ₹8,142 Cr

These should reconcile/corroborate after deterministic normalization and sensible rounding.

---

# Phase G — Retrieval Decision: Do We Need Embeddings?

Do not add embeddings by default.

First measure whether deterministic candidate retrieval fails on realistic examples.

Consider adding a lightweight semantic index only if there is a demonstrated case such as:

- semantically equivalent predicates expressed with materially different wording
- synonymous subjects/entities
- wording differences that defeat token overlap
- meaningful false negatives in candidate retrieval

If embeddings are added:

- keep them behind the existing retrieval abstraction
- keep SQLite as source of truth
- use embeddings only for candidate generation/ranking
- never let similarity alone declare CORROBORATES or CONTRADICTS
- keep the feature optional if practical
- document the model/dependency/cost tradeoff
- add deterministic tests and at least one semantic retrieval test

A smaller deterministic system that is reliable is preferable to an impressive but fragile vector stack.

---

# Phase H — Chunking Decision

Do not build complex semantic chunking unless real PDFs show a need.

Current baseline: page-aware extraction with preserved page provenance.

If chunking is improved:

- page number must remain attached to every chunk/fact/evidence item
- section context must not be lost
- chunks must be bounded in size
- extraction must remain grounded
- tests must cover page/section boundaries

Possible future direction:

PDF → page blocks → section-aware chunks → extraction

But this is optional, not a requirement for the final prototype if page-aware processing performs well.

---

# Phase I — Failure Handling

Verify and, where necessary, distinguish:

- PDF parsing failure
- empty/low-text page
- fact extraction failure
- malformed LLM output
- evidence grounding failure
- normalization failure
- retrieval failure
- ambiguous relationship reasoning
- provider/API failure

Requirements:

- no fabricated facts
- useful error/status messages
- retryable page/document processing where already supported
- confidence/uncertainty exposed where appropriate

A visible honest failure is better than a confident wrong answer.

---

# Phase J — UI Verification & Minimal Improvements

Run the actual Streamlit application and inspect it as a reviewer.

Verify the full path:

1. create/select collection
2. upload PDF
3. process
4. inspect processing status
5. browse facts
6. open fact detail
7. inspect evidence
8. inspect related facts
9. inspect relationship explanation
10. inspect failure/uncertainty
11. inspect comparison scope

Fix functional problems first.

Only then consider small UX improvements such as:

- clearer status labels
- useful filters/search
- cleaner fact cards/tables
- clearer relationship badges
- better empty/error states

Do not turn this into a frontend redesign.

---

# Phase K — Evaluation Hardening

Expand evaluation only where real failures justify it.

Maintain separation between:

- production logic
- evaluation expectations
- starter-specific verification

Useful additional tests may include:

- unit scale conversions
- rounding tolerance
- FY/quarter compatibility
- scope mismatch
- adjusted vs unadjusted metrics
- evidence grounding
- duplicate document handling
- incremental processing
- cross-collection candidate filtering
- low-text page handling

The four demo cases must remain evaluation examples, not production rules.

---

# Phase L — README & Submission

README must be truthful and reviewer-friendly.

It should clearly state:

- what the project is
- why it is a Fact Knowledge Layer rather than a generic RAG chatbot
- architecture/data flow
- fact schema
- provenance model
- normalization
- candidate retrieval
- relationship reasoning
- incremental ingestion
- collection comparison scope
- failure handling
- current provider
- environment variable setup
- local starter-PDF setup
- test commands
- four demo cases
- limitations
- future improvements

Be precise about retrieval:

If no real embedding index exists, say so. Describe the current deterministic retrieval accurately and list semantic embeddings as a possible next step rather than claiming them as implemented.

Be precise about chunking:

If extraction is page-aware rather than section-aware, say so.

Do not oversell.

---

# Phase M — Demo Video

Record a maximum ~3-minute demonstration.

Suggested flow:

### 0:00–0:20 — Problem

Briefly explain:

"This turns messy financial PDFs into grounded facts and then explains how facts across documents relate."

### 0:20–0:45 — Architecture

Show the simple pipeline:

PDF → extraction → evidence → normalization → candidate retrieval → relationship reasoning → UI

### 0:45–1:30 — Upload and inspect

Upload/process PDFs and show:

- facts
- normalized values
- source page/evidence
- confidence

### 1:30–2:30 — Four required cases

Show one each:

- corroboration
- temporal change/contradiction
- contextual reconciliation
- honest extraction failure

### 2:30–3:00 — Engineering choices

Mention:

- provenance-first design
- deterministic normalization/reasoning before LLM judgment
- selective candidate retrieval
- incremental processing
- honest uncertainty

Avoid spending the demo on implementation trivia.

---

# Phase N — Final Verification Gate

Before submission, run all applicable checks.

## Automated

- [ ] `pytest -q` passes
- [ ] evaluation passes
- [ ] starter verification passes with local PDFs
- [ ] no secrets committed
- [ ] no starter PDFs committed
- [ ] no hard-coded starter facts in production code

## Functional

- [ ] new unseen PDF can be uploaded
- [ ] duplicate PDF is detected by content hash
- [ ] facts persist
- [ ] every successful fact has evidence
- [ ] source page is visible
- [ ] normalization works
- [ ] candidate retrieval is selective
- [ ] relationships are fact-to-fact
- [ ] explanations are visible
- [ ] failures are surfaced honestly
- [ ] incremental ingestion works
- [ ] comparison scope works

## Demo

- [ ] corroboration case works
- [ ] temporal/contradiction case works
- [ ] contextual reconciliation works
- [ ] extraction failure is shown honestly
- [ ] demo video is ≤3 minutes

## Submission

- [ ] README is accurate
- [ ] repo is public/accessibly runnable
- [ ] video link added
- [ ] submission form links filled

---

# Priority Order

## P0 — Must do

1. Full codebase audit
2. Clean setup verification
3. Real three-PDF run
4. Inspect fact/evidence quality
5. Verify relationship quality
6. Verify four demo cases
7. Verify UI end-to-end
8. Final tests/evaluation

## P1 — Do if evidence shows need

- evidence UX improvements
- better candidate filters
- better failure messages
- small UI improvements
- targeted test coverage
- lightweight semantic retrieval
- improved page/section chunking

## P2 — Only if time remains

- real embeddings if justified
- vision fallback
- page highlighting/bounding boxes
- graph visualization
- performance polish

Do not sacrifice P0 correctness for P2 features.

---

# Communication Protocol

After every task, Muse must report exactly:

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

If a task reveals that an earlier assumption was wrong, say so explicitly. Do not silently rewrite architecture.

---

# Immediate Next Task

**Start with Phase A / Task A1: full codebase audit.**

Do not add embeddings, vision, new infrastructure, or a frontend redesign before the audit and real-data verification establish that they are needed.
