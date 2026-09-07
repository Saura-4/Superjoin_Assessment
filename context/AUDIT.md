# Audit — 2026-09-07 (TASK2 Phase A / Task A1)

Read: `app.py`, all of `src/` (db, ingest, llm, normalize, extract, retrieve,
relate, pipeline, failures), all tests, both evaluation scripts, README,
`context/PROJECT_CONTEXT.md`, `context/TASK2.md`. No broad rewrites made.

## Module responsibilities (confirmed as-designed)
- `db.py` — SQLite schema + CRUD only, no business logic. Canonical pair ordering
  for relationships, extensible predicate/type data. Sound.
- `ingest.py` — local PyMuPDF page extraction, quality tiers, disk cache,
  hash dedup. Sound.
- `llm.py` — provider boundary respected (no vendor imports elsewhere).
  Retry/backoff + disk cache present. Sound.
- `normalize.py` — deterministic math only. Edge cases verified by tests
  (Indian commas, lakh/crore, FY/Q/date). Sound.
- `extract.py` — one page-slice call, validation + grounding penalty. Sound
  except cache-key bug (fixed, see below).
- `retrieve.py` — selective token filter + cap + scope. No embedding claims in
  code (stub only). Matches TASK2 §2.1 reality check.
- `relate.py` — deterministic ladder before LLM judge. Sound; UNIT-tested.
- `pipeline.py` — incremental (new-facts-only linking), per-page statuses. Sound.
- `failures.py` — taxonomy only, untested (gap, low risk).
- `app.py` — full reviewer journey present; Demo Cases read live from DB.
  No hard-coded ids/values found in `src/` or `app.py`.

## Real bugs found and fixed (this audit)
1. **Cache never hit across runs** — `extract.py` built the LLM cache key with
   builtin `hash()` (randomized per process). Fixed to sha256; added
   `tests/test_cachekey.py`.
2. **Uploads stored under temp names** — documents list showed `tmpXXXX.pdf`.
   Added `db.rename_document` + `pipeline.process_document(filename=...)`,
   wired in `app.py`; tests added.

## Genuine gaps / watch-items (NOT fixed — need real-run evidence first)
- **Predicate synonym gap**: `predicate_compatible` needs token overlap, so
  LLM-emitted synonyms (`pat` vs `profit_after_tax`) would miss candidacy.
  Per Phase G: no embeddings until the real 3-PDF run demonstrates misses.
- **`resolve_scope(selected)`** exists but the UI only offers current/all.
  Cosmetic drift; fix during Phase J if scope UI is touched.
- `relate_new_fact` persists UNCERTAIN links (noise in Relationships tab).
- `failures.py` has no dedicated test; Streamlit connections leak per rerun
  (prototype-acceptable).
- README "32 tests" count is now stale (34). Update during Phase L.

## README-vs-behavior check
- Setup/run, offline mock behavior, scope model, cost strategy: accurate.
- Retrieval described as deterministic/token-based: accurate, no embedding
  oversell. Chunking described as page-aware: accurate.
- Demo-case reproduction path presumes a keyed run; unverified end-to-end
  until Phase C.

## Next
Phase B: clean-setup verification (fresh-clone behavior, test/data separation).
