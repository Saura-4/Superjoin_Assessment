# Handoff Report — Builder → Reviewer (2026-09-08, ~01:30 UTC)

Implementation agent's record of the Phase C keyed run and everything learned.
Reviewer: TASK2.md remains the active plan; this file is evidence, not instructions.

## 1. Run snapshot (queried live from local `data/run_delhivery.db`, git-ignored)

- Docs: prospectus 100p + annual 100p + earnings deck 27p = **227 pages, all ingested**
- **1652 facts + 1652 evidence rows**, 357 distinct predicates
- **572 relationships**: 100 CORROBORATES / 104 RECONCILED / 226 TEMPORAL_CHANGE / 130 CONTRADICTS / 12 UNCERTAIN
- 3 honest extraction failures (deck pp. 2, 4, 18 — chart-only, `empty_no_text`, nothing fabricated)
- Confidence (post-recalibration): 0.75×636 / 0.85×680 / 0.9×206 / 0.95×4 / lower tail 76; **zero at 1.0**
- Quota: ~630 cached calls across GEMINI_API_KEY + GEMINI_API_KEY2 (both in local `.env`, never committed);
  primary `gemini-3.1-flash-lite` hit its wall mid-run, failover served via `gemini-3.5-flash-lite`
- Tests: **49 passed**; `evaluate.py` 19/19. Head commits: `f1ece26` (latest).

## 2. Four demo cases — verified present with evidence (see `scripts/casecheck.py`)

1. Corroboration: deck `shipment_count 740 FY24` ↔ annual `count 740 FY24`; revenue
   `8142 Cr ↔ 81,415 Mn` with exact normalization math in the reason; EBITDA 127Cr↔1266Mn;
   DIN matches (Romesh Sobti, Saugata Gupta).
2. Temporal: resignation Sep 2021 → Mar 2024; director fees 5.13 (9M-2021) → 8.40 (FY24).
3. Reconciled: revenue scope consolidated-vs-standalone (named in reason); appointment
   events distinguished with real dates. NOTE: textbook Q3-PAT pair is mushy — recommend
   revenue-scope/appointments for the video, not PAT.
4. Failure: the 3 chart pages above.

## 3. Bugs found by real data → fixes (all committed, tested)

| # | Symptom | Cause | Fix (commit) |
|---|---------|-------|--------------|
| 1 | 1109 CONTRADICTS, 1108 cross-entity | same predicate ≠ same metric | subject + qualifier gates (`e6ba96b`) |
| 2 | dates corroborating (`Oct 1` = `1 COUNT`) | day-of-month arithmetic | DATE-unit guard + renormalize 121 facts (`7f0f26a`); migration commit-gate bug also fixed (`f1ece26`) |
| 3 | `count 3730 ↔ 740` "agrees exactly" | LLM hallucination on vague predicates | diff-predicate pairs need agreeing values/periods to reach judge |
| 4 | 148 UNCERTAIN flood | lite drops 8-pair batch entries | chunk 5 + confidence anchors |
| 5 | 3225 noise UNCERTAIN rows | persisting same-doc ambiguity | skip same-doc pairs entirely (`9ed63b6`), pruned |
| 6 | heal 13 min, +0 rels, then timeouts | O(n²) SQL scans; 429-retry overhead | pool prefetch (`dfde2b5`); key/model failover (`1eef53e`); circuit breaker (`4986d1d`); batch judging (`a8a1e88`); 15-RPM pacing (`72ad85e`) |
| 7 | confidence 1.0 everywhere (756/756) | model emits uncalibrated scores | deterministic recalibration cap 0.9 + quote-strength rules + corroboration bump; offline migration of stored facts (`08c8e6f`) |
| 8 | resume duplicated/skipped work | killed runs, temp filenames, cache misses | resumable pages, crash-safe page guard, upload filename passthrough, sha256 cache keys, heal-unlinked (`5e50fd7`, `d2300d1`, Phase B `7303b78`) |

Supporting scripts (committed): `scripts/{run_delhivery,smoke_llm,liveprobe,dbcheck,relcheck,democheck,casecheck,datecheck,linkcheck,distcheck,confcheck,recalibrate_db,cleanrels_db,prune_uncertain,healprobe}.py`.
Repro scripts: `scripts/democheck.py`, `scripts/casecheck.py` (casecheck needs `chcp 65001` for ₹ on Windows consoles).

## 4. Known gaps / reviewer action items

1. **130 CONTRADICTS unsampled** — post-gate contradictions not manually audited. Spot-check before filming.
2. 307 facts lack periods; DATE linkage sparse (5/121, mostly correctly UNRELATED strangers). Limits temporal recall; acceptable, document it.
3. Same-doc pairs never reach the LLM (documented design: cross-doc is the assignment). Relationships tab is cross-doc + deterministic by construction.
4. `evaluations/delhivery_run_stats.json` is committed (reviewer evidence) and regenerates per run — fine.
5. Quota state unknown for next run (both keys partially burned; RPD resets midnight PT). If judges 429 everywhere, mint a 3rd key or wait for reset — failover picks up `GEMINI_API_KEY2`/`GEMINI_API_KEYS` live, no code change needed.
6. Remaining TASK2 path: Phase J (UI pass against this data) → K (eval additions only if justified) → L (README: retrieval/chunking honesty already accurate; add calibration + cross-doc-judging notes) → M (video ≤3 min; use Case 3 = revenue-scope) → N (final gate).

## 5. How to resume the run (no code changes needed)

```
set GEMINI_API_KEY=...            # + GEMINI_API_KEY2=... if available (local .env, git-ignored)
python scripts/run_delhivery.py --doc-index N   # 0,1,2 — idempotent, resumable, crash-safe
python scripts/casecheck.py       # verify the four cases
python scripts/recalibrate_db.py --db data/run_delhivery.db --apply   # only if rules change again
```
