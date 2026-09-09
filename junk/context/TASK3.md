# TASK3 — Hybrid Semantic Fact Retrieval + Relationship Candidate Selection

## Goal

Improve the current fact-to-fact relationship pipeline by adding **hybrid retrieval**:

1. Lexical/word-based retrieval
2. Semantic/embedding-based retrieval
3. Candidate merging and deduplication
4. Structured deterministic reranking/filtering
5. Existing deterministic relationship logic
6. Existing LLM judge only for genuinely ambiguous cases

The immediate goal is **NOT** to process all 1,652 facts.

First validate the new retrieval architecture using **100 facts from each of the 3 existing documents (300 facts total)**. Inspect the retrieval quality and behavior before scaling embeddings to the remaining facts.

---

# Important Constraints

* Do NOT modify `context/TASK.md`.
* Do NOT set up Cerebras or any paid API.
* Do NOT regenerate the existing extracted facts.
* Do NOT run the complete 227-page pipeline.
* Do NOT embed all 1,652 facts initially.
* Initially embed **only 100 facts per source document = 300 facts total**.
* Use the existing extracted facts as the input.
* SQLite remains the source of truth.
* Embeddings are an auxiliary retrieval mechanism only.
* Do NOT embed the LLM relationship-decision cache.
* Do NOT add a vector database.
* Do NOT redesign the UI.
* Do NOT add vision/OCR/new infrastructure in this task.
* Preserve the existing LLMProvider/Gemini architecture.
* Preserve existing relationship taxonomy and persistence unless a minimal compatibility change is required.

---

# Current Fact Model

Each extracted occurrence is one independent fact.

For example, if the same revenue appears in two documents:

```text
Document A
    ↓
Fact A
    ↓
Evidence A


Document B
    ↓
Fact B
    ↓
Evidence B
```

Do NOT merge Fact A and Fact B before relationship detection.

The relationship between them may become:

```text
Fact A ── CORROBORATES ── Fact B
```

This preserves independent source evidence.

---

# Two Representations of Each Fact

A fact has one canonical structured representation:

```text
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
evidence
```

Separately, create a semantic text representation used only for embedding.

Example:

```text
Subject: Delhivery Limited
Metric: revenue from operations
Period: FY2024
Scope: consolidated
```

This text is embedded.

The embedding is NOT another fact.

Do not make the exact numerical value the primary semantic signal. Numerical/unit comparison is handled using the structured fields.

The claim may be included as additional semantic context if useful, but structured fields remain authoritative.

Keep semantic-text construction behind a small testable function.

---

# Target Architecture

```text
Existing extracted facts
        │
        │
        ├───────────────┐
        │               │
        ↓               ↓
 Lexical Retrieval   Semantic Retrieval
 (word/token/BM25)   (embedding similarity)
        │               │
        └───────┬───────┘
                ↓
        Merge candidate sets
                ↓
          Deduplicate pairs
                ↓
       Structured reranking
                ↓
        Candidate selection
                ↓
       ┌────────┴────────┐
       ↓                 ↓
    Obvious          Ambiguous
       ↓                 ↓
 Deterministic       LLM Judge
       │                 │
       └────────┬────────┘
                ↓
         Relationship
                ↓
          Persistence
```

---

# Phase 1 — Select the 300-Fact Test Set

Use the existing extracted facts.

Select:

```text
Document 1 → 100 facts
Document 2 → 100 facts
Document 3 → 100 facts
```

Total:

```text
300 facts
```

The selection should be deterministic/reproducible.

Prefer a representative spread of predicates/subjects rather than simply taking the first 100 rows.

If the existing database has enough metadata, use it to avoid a test set dominated by one metric or one section.

Do NOT modify or delete the other ~1,350 facts.

They simply remain outside the initial embedding/retrieval experiment.

---

# Phase 2 — Semantic Embedding

Embed only the selected 300 facts.

Use a local/free embedding model with no API key and no payment requirement.

Prefer a compact sentence-transformer model suitable for local inference, such as:

```text
all-MiniLM-L6-v2
```

if compatible with the current environment.

Before adding dependencies:

1. inspect `requirements.txt`;
2. inspect the current environment;
3. reuse an existing suitable dependency if available;
4. avoid heavy infrastructure.

Use an in-process vector index with cosine similarity.

A vector database is unnecessary for this scale.

The embedding component should have a small replaceable interface.

---

# Phase 3 — Semantic Retrieval

There is no external natural-language query.

For every selected fact A:

```text
embedding(A)
      ↓
semantic similarity search
      ↓
top-K similar facts
```

The fact itself acts as the query.

Exclude:

* A itself;
* same-document candidates for cross-document relationship discovery.

Do not compare every fact against every other fact.

Also prevent duplicate unordered pairs:

```text
A → B
B → A
```

must become one pair:

```text
(A, B)
```

and should be processed once.

---

# Phase 4 — Lexical Retrieval

Hybrid retrieval must include a lexical component in addition to embeddings.

Reuse or improve the existing lexical/token-based retrieval logic where practical.

The lexical retriever should identify candidates based on textual overlap in useful fields such as:

* subject;
* predicate;
* claim/semantic text where appropriate;
* relevant qualifiers.

If a proper BM25 implementation is already available or can be added cleanly, it may be used.

Do not add unnecessary infrastructure just to implement BM25.

The key requirement is that the retrieval stage has BOTH:

```text
Lexical candidates
+
Semantic candidates
```

---

# Phase 5 — Merge Hybrid Candidates

Do NOT simply take semantic top-K and ignore lexical retrieval.

For each fact:

```text
Lexical top-K
       +
Semantic top-K
       ↓
Union
       ↓
Remove duplicates
       ↓
Remove self/same-document candidates
```

Example:

```text
Lexical:
B
C
D

Semantic:
C
E
F

Merged:
B
C
D
E
F
```

Candidate pairs must then be passed through structured reranking.

---

# Phase 6 — Structured Reranking

Embedding/lexical similarity only answers:

> "Could these facts potentially refer to the same underlying concept?"

It does NOT determine the relationship.

For each merged candidate pair, calculate an explainable structured compatibility/reranking score using available fields such as:

* subject compatibility;
* predicate compatibility;
* period compatibility;
* scope compatibility;
* unit compatibility;
* normalized value compatibility;
* semantic similarity;
* lexical score;
* cross-document status.

Keep the scoring logic deterministic and independently testable.

### Important

Do NOT require exact predicate equality.

For example:

```text
revenue_from_operations
revenue
operating_revenue
consolidated_revenue
```

may refer to the same underlying metric.

Semantic retrieval should allow these to become candidates.

Similarly:

```text
different value
```

does NOT automatically mean:

```text
CONTRADICTS
```

Period, scope and qualifiers must be considered first.

---

# Phase 7 — Deterministic Relationship Layer

After retrieval and reranking, use the existing deterministic relationship logic.

The deterministic layer should confidently handle obvious cases.

### Example 1 — Corroboration

```text
A:
Revenue
FY2024
₹8,142 crore

B:
Revenue
FY2024
₹81,420 million
```

After normalization:

```text
same subject
same/compatible predicate
same period
same scope
same normalized value
```

→ `CORROBORATES`

No LLM call should be necessary.

---

### Example 2 — Temporal Change

```text
A:
Director fee
FY2023
₹5.13 Cr

B:
Director fee
FY2024
₹8.40 Cr
```

```text
same subject
same metric
different period
different value
```

→ `TEMPORAL_CHANGE`

No LLM call should be necessary when the interpretation is unambiguous.

---

### Example 3 — Strong Contradiction

```text
A:
Revenue
FY2024
₹8,142 Cr
Consolidated

B:
Revenue
FY2024
₹5,000 Cr
Consolidated
```

```text
same subject
same metric
same period
same scope
incompatible normalized values
```

→ strong `CONTRADICTS` candidate.

If qualifiers/context make it ambiguous, pass it to the LLM instead of forcing a deterministic contradiction.

---

### Example 4 — Ambiguous Semantic Equivalence

```text
A:
revenue_from_operations

B:
operating_revenue
```

If structured rules cannot confidently determine whether they represent the same metric:

```text
→ LLM judge
```

The LLM receives the two facts plus their evidence/context.

---

# Phase 8 — LLM Judge

Reuse the existing relationship judge.

The LLM should NOT receive every retrieved candidate.

Only ambiguous candidates that survive hybrid retrieval and structured filtering/reranking should reach the LLM.

The LLM should determine among the existing relationship categories, such as:

```text
CORROBORATES
CONTRADICTS
RECONCILES
TEMPORAL_CHANGE
UNRELATED
```

and provide the explanation/reason.

The goal is to reduce unnecessary LLM calls substantially.

---

# Phase 9 — First Validation: 300 Facts Only

Do NOT scale beyond 300 facts yet.

Run the entire retrieval + candidate-selection + relationship flow on:

```text
100 facts from Document 1
100 facts from Document 2
100 facts from Document 3
```

Inspect actual results.

Record:

```text
300 source facts

Lexical candidates:
    X

Semantic candidates:
    Y

Merged unique candidates:
    Z

Candidates surviving structured reranking:
    N

Deterministic relationships:
    D

LLM judge candidates:
    L

Final relationships:
    R
```

Also inspect examples manually.

---

# What Must Be Manually Checked

The 300-fact run should demonstrate that hybrid retrieval finds useful candidates such as:

### 1. Same fact, different wording

```text
revenue from operations
vs
operating revenue
```

### 2. Same fact, different units

```text
₹8,142 crore
vs
₹81,420 million
```

### 3. Same metric, different period

```text
FY2023
vs
FY2024
```

### 4. Genuine contradiction

Same entity + metric + period + scope but incompatible values.

### 5. False semantic neighbor

For example:

```text
revenue
vs
revenue growth
```

or another semantically close but materially different metric.

### 6. Subject mismatch

Similar metric wording belonging to different entities should not become a relationship merely because embeddings are similar.

---

# Retrieval Quality Is the First Gate

Before scaling beyond 300 facts, inspect whether:

* semantic retrieval finds predicate/wording variations that lexical retrieval misses;
* lexical retrieval catches exact terminology that semantic retrieval may rank lower;
* the merged candidate pool contains useful cross-document matches;
* structured reranking removes obvious noise;
* the deterministic layer handles obvious cases;
* only genuinely ambiguous candidates reach the LLM;
* same-document noise is excluded;
* duplicate pair processing is avoided.

If retrieval quality is poor, fix retrieval before scaling.

Do NOT proceed to the full 1,652-fact embedding run simply because the code executes.

---

# Phase 10 — Only After Approval/Validation

If the 300-fact run is healthy, expand the embedding index to all:

```text
~1,652 facts
```

Do not regenerate extraction.

Then compare the full run against the previous relationship system.

Measure:

* candidate count;
* relationship count;
* LLM calls;
* CORROBORATES;
* CONTRADICTS;
* RECONCILES;
* TEMPORAL_CHANGE;
* false-positive patterns;
* processing time.

The old token-based retrieval should remain available for comparison if practical.

---

# Required Files to Inspect Before Implementation

Inspect:

```text
src/retrieve.py
src/relate.py
src/pipeline.py
src/db.py
src/normalize.py
requirements.txt
tests/*
```

Understand the existing interfaces before changing them.

Do not perform a broad refactor.

---

# Testing Requirements

Add focused tests for:

1. semantic text construction;
2. embedding generation;
3. cosine similarity;
4. lexical retrieval;
5. semantic retrieval;
6. hybrid candidate union;
7. duplicate pair removal;
8. same-document exclusion;
9. subject mismatch filtering;
10. different-predicate candidate retrieval;
11. exact normalized-value corroboration;
12. temporal change;
13. contradiction candidate;
14. ambiguous candidate → LLM judge;
15. obvious candidate → no LLM call.

Tests must verify that the LLM is NOT called for every top-K candidate.

---

# Do Not Do in TASK3

* Do not embed all 1,652 facts initially.
* Do not run the full 227-page extraction pipeline.
* Do not regenerate existing facts.
* Do not embed the LLM cache.
* Do not use Cerebras.
* Do not introduce paid services.
* Do not introduce a vector database.
* Do not introduce a graph database.
* Do not redesign the UI.
* Do not add vision/OCR.
* Do not replace SQLite as source of truth.
* Do not make embeddings the relationship classifier.
* Do not require exact predicate equality.
* Do not classify different numeric values as contradictions without checking period/scope/qualifiers.
* Do not make broad unrelated refactors.

---

# Deliverable

After implementation:

1. List all files changed.
2. Explain the hybrid retrieval flow.
3. Explain the embedding representation.
4. Report the 300-fact test composition.
5. Report lexical candidate counts.
6. Report semantic candidate counts.
7. Report merged candidate counts.
8. Report candidates surviving structured reranking.
9. Report deterministic relationship counts.
10. Report LLM judge call count.
11. Show representative successful retrieval examples.
12. Show at least one case where lexical and semantic retrieval found different candidates.
13. Show at least one case where deterministic logic avoided an unnecessary LLM call.
14. Show any failures/limitations.
15. Do NOT scale to all 1,652 facts until the 300-fact behavior has been inspected and is clearly healthy.

If the 300-fact run is healthy, prepare the next step for scaling to all facts, but keep that as a separate controlled action.

Suggested commit message:

```
feat: add hybrid semantic fact retrieval
```
