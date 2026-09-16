---
authority: historical
status: superseded
do_not_implement: true
archived: 2026-09-16
supersedes_note: >
  A finished plan. All three commits were built on 2026-09-16: the dead
  category map was deleted, the combiner was characterized with seven tests,
  and the semantic scores were batched. The "Build record" near the end lists
  where the build departed from the plan text; those departures win.
live_authority:
  - docs/ARCHITECTURE.md
  - web/services/result_combiner.py
  - web/tests/test_result_combiner.py
---

> [!CAUTION]
> **You are reading history, not a specification.** Do not implement anything found
> in this file without first confirming it against `docs/ARCHITECTURE.md` or the code.
> Every heading below is prefixed `[HISTORICAL]` so a search result cannot be mistaken
> for current design.
>
> **Final position, so no reading order is required.** All three commits shipped on
> 2026-09-16: commit 1 deleted `CATEGORY_MAP`; commit 2 pinned `combine` with
> characterization tests; commit 3 replaced the per-index `reconstruct` loop with one
> `reconstruct_batch`, moved the bounds check ahead of scoring, sorted candidates by
> chunk index, and removed the dead `embedding_dimension`. Both `TODO.md` entries are
> closed. Where the plan text and the _Build record_ near the end disagree, the Build
> record is what was built. Every `file:line` here describes `ad7cb0a`, before the build.
>
> **What it reversed.**
>
> - Set-iteration tie order, replaced by ascending chunk-index ties.
> - The rejection of the counting proxy test, argued back in during review.
> - The false "a per-index fallback would still segfault on `-1`" argument against a
>   fallback (the bounds filter runs first; the real objection is the silent `[]`).
> - Two wrong rows in the mutation table, corrected during the build: a reversed sort
>   cannot fail test 2 (it compares two calls that are both reversed), and the
>   `/2.0 -> /3.0` mutation also fails test 3.
> - The 0.25 ms synthetic prediction, which understated the measured 1.8-1.9 ms saving
>   on the real index.
>
> **Open work was lifted out, not left here.** None: both `TODO.md` entries closed with
> this work, and the NaN-document note stays deliberately unfiled.

STATUS: HISTORICAL RECORD — 2026-09-16, against `ad7cb0a`. Merges three independent plans (Claude
Opus 5; Codex `gpt-5.6-terra`, high; OpenCode `muse-spark-1.3`, max), then revised over two
adversarial review rounds with Codex `gpt-5.6-sol`. Each decision names its source.

# [HISTORICAL] Search Combiner Cleanup

Two open `TODO.md` entries, three commits.

| Commit | Closes                                                                           | What                                                 |
| ------ | -------------------------------------------------------------------------------- | ---------------------------------------------------- |
| 1      | [`CATEGORY_MAP` in `search_engine.py` has no callers](TODO-resolved.md)          | Delete the dead map                                  |
| 2      | —                                                                                | Characterization tests for `combine`, no code change |
| 3      | [`ResultCombiner` reconstructs one FAISS vector per candidate](TODO-resolved.md) | Batch the semantic scores, then archive this plan    |

Commit 1 is independent and can land at any time. Commit 3 does not start until every mutation in
commit 2 has been shown to fail a test.

## [HISTORICAL] Why commit 3 is worth doing

Measured on the real corpus (4,545 chunks, 768 dimensions, 160 candidates), batching saves about
**1.8 ms per question, roughly 18% of `combine`** — larger than the 0.25 ms this plan first
predicted from a synthetic index. It is still small next to an LLM call measured in seconds, so
the other three reasons carry the commit:

- replaces N FAISS calls with one, and deletes a helper;
- fixes a silent refusal: a query whose dimension differs from the index's makes `combine` return
  `[]` today, which the reader sees as "no relevant information";
- moves the bounds check in front of FAISS, where `reconstruct(-1)` otherwise crashes the process.

## [HISTORICAL] What was verified

Checked in the session that wrote this plan, against `ad7cb0a`, with faiss-cpu 1.14.2, numpy
2.4.6 and scikit-learn 1.8.0 installed.

### [HISTORICAL] The index and the API

- Every build creates a `faiss.IndexFlatL2` (`web/services/data_processing.py:465`). Flat
  indexes store vectors directly, so `reconstruct_batch` needs no direct map.
- The FAISS docs name `reconstruct_batch` as the batched form of `reconstruct`, "especially in
  Python to avoid loops". It takes `int64` ids and returns `(n, d)` float32, identical to
  per-id `reconstruct`.
- `reconstruct_n` covers only a contiguous id range; the candidates are a sparse union.

### [HISTORICAL] `combine` today

All in `web/services/result_combiner.py`:

- The candidates are a Python `set` (`:126-128`), iterated once (`:142`). `list.sort` is stable
  (`:195`), so tied scores come out in set-iteration order.
- The lexical side is already batched (`:207-219`).
- The semantic side calls `reconstruct` once per index (`:221-227`) and computes
  `1 - float(np.dot(diff, diff)) / 2`, so the subtraction and clamp run on a Python float.
- The bounds check `idx < 0 or idx >= len(df)` (`:149`) runs **after** the FAISS call.
- Every row, FAISS call included, sits inside one per-row `try/except` (`:143-193`). So a
  4-dimensional query against a 3-dimensional index makes every row raise, and `combine` returns
  `[]`. `SearchEngine.search`'s docstring forbids exactly this (`web/services/search_engine.py:259-265`).
- `query_embedding` arrives uncast (`search_engine.py:317-324`), but
  `QueryProcessor.get_embedding` already returns normalized float32
  (`web/services/query_processor.py:209-229`).
- Two docstrings name the per-index helper: `combine`'s step 2 (`:105-107`) and
  `apply_relevance_floor` (`:307`).
- A row whose `document` is NaN is dropped by that `try`, but only on a registration query,
  because `_apply_penalty_for_chunk` calls `.lower()` on it.

### [HISTORICAL] What a bad index does

Both searchers drop out-of-range rows before `combine`
(`web/services/semantic_searcher.py:89-91`, `web/services/lexical_searcher.py:107-108`), and the
loader checks that the DataFrame, TF-IDF and FAISS row counts agree. So no bad index reaches
`combine` in production. If one did, the per-row `try` would not save it:

| Index | `_compute_lexical_scores`      | `faiss.reconstruct`                    |
| ----- | ------------------------------ | -------------------------------------- |
| `-1`  | wraps to the last row          | **segfaults the process**, uncatchable |
| `99`  | `IndexError`, out of `combine` | `RuntimeError`                         |

### [HISTORICAL] Batched scores are not bit-identical

Over 58 candidates in 384 dimensions:

| Distance form                 | Max difference from today |
| ----------------------------- | ------------------------- |
| per-row `np.dot`              | 0.0                       |
| `np.einsum("ij,ij->i", d, d)` | 2.4e-7                    |
| `(d * d).sum(axis=1)`         | 6.0e-8                    |

These come from float32 summation order. The clamp step must not add a second difference, so
each distance becomes a Python float before `1 - d / 2`, as it does today.

### [HISTORICAL] The payoff

Synthetic `IndexFlatL2` at 768 dimensions (`all-mpnet-base-v2`), timing only the reconstruct and
score step. Production asks for `k: 8` with multipliers of 10 (`web/config.yaml:215-219`), so a
union holds up to 160 candidates.

| Candidates | Per-index loop | Batched |
| ---------- | -------------- | ------- |
| 80         | 307 µs         | 48 µs   |
| 159        | 619 µs         | 376 µs  |
| 231        | 869 µs         | 560 µs  |

That synthetic figure **understated the real saving**, so it is kept here only as the prediction
that was wrong. Measured on the real index, twice and independently — once by the build, once by
the reviewer, with a different seed and workload each time:

| Run      | Old median | New median | Delta            |
| -------- | ---------- | ---------- | ---------------- |
| Build    | 11,805 µs  | 9,886 µs   | −1,919 µs (−16%) |
| Reviewer | 9,967 µs   | 8,211 µs   | −1,756 µs (−18%) |

Both runs also checked equivalence over 50 real queries: identical result order every time, and
scores within 1.8e-7.

### [HISTORICAL] `CATEGORY_MAP`

- `web/services/search_engine.py:136-147`. The dict is 7 lines with 5 entries; with its banner
  and blank lines the block is 12. The TODO entry's "11-line dict" is wrong either way.
- `grep -rn CATEGORY_MAP` over `*.py`, `*.js`, `*.md`, `*.yaml` and `*.html`, including
  `docs/archive/`, finds the definition, `TODO.md`,
  `docs/archive/2026-09-16_simplification-pass.md` and this plan. Nothing else.
- The `search` docstring's example category values (`search_engine.py:244-246`) are a different
  thing: matching is by fuzzy substring (`semantic_searcher.py:136-143`). Deleting the map does
  not make them false.

## [HISTORICAL] Decisions

- **Tie order: sort by chunk index.** Iterate `sorted(union_indices)`, so an exact tie breaks
  toward the lower index. Today's order is CPython set-iteration order, which nothing relies on
  and nothing pins. A labelled behaviour change, pinned by a test. _OpenCode, and Sol in round 1.
  This reverses an earlier draft that kept set order, as Codex proposed._
- **Bounds check: before any scoring.** Filter the union to `0 <= idx < len(df)`, keeping the
  same warning, before lexical and semantic scoring. A bad index is then skipped instead of
  raising or crashing. A labelled behaviour change that no reader can see. _OpenCode's idea; the
  segfault evidence is Claude's._
- **A failed batch: no fallback; the error propagates.** That turns the dimension-mismatch
  refusal into a `SearchEngineError`. A labelled bug fix, pinned by a test. _Sol, round 1. An
  earlier draft rejected Codex's fallback because it "would still segfault on `-1`". That was
  wrong, because the filter runs first; the real reason is that a fallback restores the silent
  `[]`._
- **Per-row `try/except`: keep it, around result building only.** It still guards row handling,
  such as the NaN document. _All three plans._
- **dtype: no cast.** Broadcasting keeps today's float32 and float64 behaviour. _Codex. OpenCode's
  explicit float32 cast was rejected because it changes the float64 path._
- **Rounding: `einsum`, then a Python-float clamp.** The test tolerance is `abs=1e-6`. Fixture
  scores sit far apart, so the tolerance cannot hide a reorder. _Claude measured the difference;
  the Python-float clamp is Codex's._
- **Proof that batching happened: a counting proxy test.** Replacing N calls with one is the
  entry's acceptance criterion, and no behavioural test can tell the loop from the batch. _Codex
  proposed it, an earlier draft rejected it, and Sol argued it back in during round 1._
- **TODO closure: in the same commit as the code.** CLAUDE.md requires fixing a document in the
  commit that makes it wrong. _Codex. OpenCode's separate closing commit was rejected._
- **Archiving this plan: in commit 3, by the full archive procedure.** _Sol, round 1; all three
  first drafts missed it._
- **Out of scope, unchanged:**
  - **The `search` docstring's category list.** It is not made false. _Codex; OpenCode's rewrite
    was rejected._
  - **The NaN-document drop.** No build is known to write one, so it is noted here, not filed.
    _Raised by Sol._

## [HISTORICAL] Commit 1: delete `CATEGORY_MAP`

**Files:** `web/services/search_engine.py`, `TODO.md`, `docs/archive/TODO-resolved.md`,
`docs/archive/README.md`.

1. **Re-run the grep.** Expect exactly the four hits listed above, and stop if there is any
   other.
2. **Delete `search_engine.py:136-147`:** the banner, the dict and the blank line after it.
3. **Close the TODO entry:**
   1. Add a dated closing note that corrects the "11-line" figure to a 7-line dict in a 12-line
      block.
   2. Move the whole entry under _Resolved planned work_ in `TODO-resolved.md`, using that file's
      heading form, `### [HISTORICAL] ~~…~~ — DONE <date>`.
   3. Rewrite its relative links for the new directory. For example,
      `docs/archive/2026-09-16_simplification-pass.md` becomes
      `2026-09-16_simplification-pass.md`.
   4. Delete its line from Open now.
4. **Update the archive index.** In `docs/archive/README.md`, re-measure the `TODO-resolved.md`
   row's entry count (41 before this commit) and its line count; do not add to the old figures.

**No test.** Nothing calls the map, so there is nothing to pin.

## [HISTORICAL] Commit 2: characterize `combine`

**Files:** new `web/tests/test_result_combiner.py`. No production code changes.

### [HISTORICAL] Fixture

No mocks:

- a real `faiss.IndexFlatL2(3)`;
- a real fitted `TfidfVectorizer`;
- a `ResultCombiner` with production's 0.5/0.5 weights;
- a float32 query, `[0.8, 0.6, 0]`.

`category` is `"regulatory"` on every row, and `chunk_id` runs `"c0"` to `"c4"`. The semantic
scores can be worked out by hand.

| Row | Vector            | Semantic       | Text               | Document                 | Page   | Pins                                             |
| --- | ----------------- | -------------- | ------------------ | ------------------------ | ------ | ------------------------------------------------ |
| 0   | `[1, 0, 0]`       | 0.8            | `alpha beta`       | `a.pdf`                  | `"1"`  | the fused score                                  |
| 1   | `[0, 1, 0]`       | 0.6            | `beta gamma`       | `drug_license_guide.pdf` | `"x"`  | a visible ×0.80 penalty; non-digit page → `None` |
| 2   | `[0, 0, 1]`       | 0.0            | `beta delta`       | `c.pdf`                  | `None` | zero semantic score, non-zero lexical            |
| 3   | `[1/√2, 1/√2, 0]` | 0.9899         | `alpha alpha beta` | `d.pdf`                  | `4`    | the top result; integer page                     |
| 4   | `[-1, 0, 0]`      | clamped to 0.0 | `delta epsilon`    | `e.pdf`                  | `"2"`  | the clamp; the lowest score                      |

**Call:**

- Semantic candidates `[0, 3, 4]`, lexical candidates `[1, 2, 0]`. The overlap on row 0 covers
  de-duplication.
- `lexical_query="alpha beta"`.
- `query_text="registration of alpha"`, which triggers the penalty.

Expected values, recorded from the unchanged code so the build can check its own recording:

| Row | Score     | Semantic  | Lexical   | Raw hybrid | Penalty                         |
| --- | --------- | --------- | --------- | ---------- | ------------------------------- |
| 3   | 0.976368  | 0.9899495 | 0.9627865 | 0.976368   | —                               |
| 0   | 0.9       | 0.8       | 1.0       | 0.9        | —                               |
| 1   | 0.3524086 | 0.6       | 0.2810214 | 0.4405107  | `establishment_license_penalty` |
| 2   | 0.1638927 | 0.0       | 0.3277855 | 0.1638927  | —                               |
| 4   | 0.0       | 0.0       | 0.0       | 0.0        | —                               |

### [HISTORICAL] Tests

1. **`test_combine_fuses_real_faiss_and_tfidf_scores_and_ranks_them`**
   - With `final_k=10`, asserts the `original_index` order is exactly `[3, 0, 1, 2, 4]`.
   - For every row, asserts `text`, `score`, `page`, `document`, `category`, `chunk_id` and all
     five `metadata` keys. Floats use `pytest.approx(abs=1e-6, rel=0)`.
   - The per-row metadata asserts are what catch a rewrite that pairs scores with the wrong
     indices.
2. **`test_final_k_keeps_the_top_of_the_same_ranking`**
   - With `final_k=4`, asserts the result is the first four results of test 1.
3. **`test_a_registration_query_that_names_an_establishment_is_not_penalised`**
   - Sets `query_text="registration of a manufacturer license"` and leaves `lexical_query`
     unchanged, so the lexical scores stay as in the table.
   - Asserts row 1's `score` is its raw hybrid, 0.4405107, and its `penalty_reason` is `None`.

### [HISTORICAL] Prove the tests are not vacuous

Apply each mutation to the real `combine`, watch the named test fail, then revert. Record all
four in the commit message.

| Mutation                                               | Fails   |
| ------------------------------------------------------ | ------- |
| `/ 2.0` → `/ 3.0` in the semantic score                | 1 and 3 |
| drop the `max(0.0, …)` clamp (row 4 becomes -0.8)      | test 1  |
| `reverse=True` → `reverse=False`                       | test 1  |
| `final_results[:final_k]` → `final_results[-final_k:]` | test 2  |
| delete `or asks_establishment` in the penalty guard    | test 3  |

A reversed sort cannot fail test 2: it compares two calls that are both reversed. The
truncation mutation is what proves test 2. _Corrected during the build; the first table had
this wrong._

Do not use "swap the semantic and lexical weights" as a mutation. At 0.5/0.5 it changes nothing,
so every test would still pass.

## [HISTORICAL] Commit 3: batch the semantic scores

**Files:**

- `web/services/result_combiner.py`
- `web/tests/test_result_combiner.py`
- `TODO.md`
- `docs/archive/TODO-resolved.md`
- `docs/archive/README.md`
- this plan, moved with `git mv` to `docs/archive/<completion date>_search-combiner-cleanup.md`

### [HISTORICAL] Change

This sketch shows the intent; the build should tighten it. In `combine`:

```python
idx_list: list[int] = []
for idx in sorted(union_indices):
    if 0 <= idx < len(self._df):
        idx_list.append(idx)
    else:
        logger.warning("Invalid index %d — skipping.", idx)
if not idx_list:
    return []

lexical_scores = self._compute_lexical_scores(idx_list, lexical_query)
semantic_scores = self._compute_semantic_scores(idx_list, query_embedding.flatten())

for idx, sem_score in zip(idx_list, semantic_scores, strict=True):
    try:
        ...  # unchanged from `lex_score = …` onward, minus the old bounds check
```

It replaces `_compute_semantic_score`:

```python
def _compute_semantic_scores(self, indices: list[int], query_vec: np.ndarray) -> list[float]:
    """Reconstruct every candidate in one FAISS call, then score them together."""
    diffs = query_vec - self._faiss_index.reconstruct_batch(np.asarray(indices, dtype=np.int64))
    distances = np.einsum("ij,ij->i", diffs, diffs).tolist()
    return [max(0.0, min(1.0, 1.0 - d / 2.0)) for d in distances]
```

Also:

- `_compute_lexical_scores` takes the list, and drops its own `list()` call and empty check.
- `embedding_dimension` becomes dead: only `_compute_semantic_score` read it, to size the
  vector it allocated. Drop the constructor argument and the field, and the
  `self._embedding_dimension` that `SearchEngine` kept solely to pass it
  (`search_engine.py:211,437`). _Found in review; the first draft of this plan missed it._
- Update the two docstrings that named the old helper: `combine` step 2 and
  `apply_relevance_floor`. The latter keeps its "reduces to cosine" argument, repointed at
  `_compute_semantic_scores`.

### [HISTORICAL] Behaviour changes

Label each one in the commit message:

1. **Bug fix: a query of the wrong dimension now raises.** `combine` used to return `[]` and the
   reader got a refusal. Now `search` wraps the error in `SearchEngineError`.
2. **An out-of-range candidate is skipped with a warning before any scoring.** It used to raise
   out of `combine` or, for `-1`, crash the worker. Neither searcher can produce one.
3. **Candidates are processed in ascending chunk-index order.** Exact ties break toward the lower
   index, and warnings and per-row exception logs follow the same order. Only the tie order is
   visible to a reader.
4. **Semantic scores may differ from before by less than 1e-6.**

### [HISTORICAL] Tests

Commit 2's three tests pass **unmodified**. Add four more, and show each one failing against
commit 2's code before the change:

1. **`test_combine_reconstructs_every_candidate_in_one_faiss_call`**
   - A small proxy holds the fixture's real index. It forwards `reconstruct_batch` and counts the
     calls, and it raises on `reconstruct`.
   - Asserts exactly one batch call, carrying all five ids.
   - **Fails before the change on the count, not on an exception**, because the old per-row `try`
     swallows the raise and returns `[]`. Assert the count.
2. **`test_a_query_of_the_wrong_dimension_raises_instead_of_returning_nothing`**
   - Passes a 4-dimensional query to the 3-dimensional fixture and asserts
     `pytest.raises(ValueError)`. numpy raises it on the subtraction, after lexical scoring.
   - Fails before the change, when `combine` returned `[]`.
3. **`test_an_out_of_range_candidate_is_skipped_not_scored`**
   - Passes candidates `[0, 99]` and asserts one result, plus the warning in `caplog`.
   - Fails before the change with an `IndexError` from the lexical slice.
   - **Never use `-1`.** Against the old code it segfaults the whole test run.
4. **`test_an_exact_tie_breaks_toward_the_lower_chunk_index`**
   - Uses its own index with two identical rows: same vector, text and document.
   - Place the two rows at indices whose CPython set order is not ascending, or the old code
     passes by accident. For example, semantic `[9]` and lexical `[1]`: `list({9} | {1})` is
     `[9, 1]`. Check this at build time.
   - Asserts the lower index comes first.

### [HISTORICAL] Measure on the real index

Use a throwaway script kept outside the repo.

1. **Load the artifacts directly** from `web/processed_data/builds/<active_build.txt>/`, using
   `faiss.read_index`, `pd.read_csv`, and `pickle.load` for both TF-IDF files. `SearchIndex`
   needs a config and an embedding client (`search_index.py:91-118`), so don't go through it.
2. **Build one workload and save it:**
   - 50 seeded-random chunk vectors as queries;
   - for each, a fixed 160-index candidate list, split 80 semantic and 80 lexical;
   - one fixed `lexical_query`.
3. **Run the same script on the same workload** against commit 2's `combine` (a `git worktree`)
   and commit 3's. Warm up, then time 200 rounds of each.
4. **Report the median and p90 of both runs, and the delta**, including zero or a regression.

### [HISTORICAL] Close the TODO entry

1. Add a dated closing note: what shipped, the measured delta, and the four behaviour changes.
2. Move the whole entry to `TODO-resolved.md`, with the heading form and link rewrite from
   commit 1.
3. Delete its line from Open now.
4. Re-measure the `TODO-resolved.md` row in `docs/archive/README.md` again.

### [HISTORICAL] Archive this plan

Follow all six steps of
[`docs/archive/README.md#adding-to-this-archive`](README.md#adding-to-this-archive):

1. **Lift still-open items to `TODO.md`.** None are expected; the NaN-document note stays unfiled.
2. **`git mv`** this plan to `docs/archive/<completion date>_search-combiner-cleanup.md`.
3. **Add the frontmatter and banner.** Copy the complete frontmatter block from
   `docs/archive/TODO-resolved.md:1-13` (`authority`, `status`, `do_not_implement`, `archived`,
   `supersedes_note`, `live_authority`), fill in the date and final position, and add a
   `> [!CAUTION]` banner.
4. **Prefix every heading with `[HISTORICAL]`**, and fix the internal anchors to match.
5. **State what the plan reversed:** set-order ties, the rejected counting test, and the false
   segfault argument against a fallback.
6. **Add a row to the archive index**, with the plan's line count.

Then repoint any `TODO-resolved.md` entry that links this plan at its archived path.

## [HISTORICAL] Gates

Every commit:

```bash
.venv/Scripts/python.exe -m pytest -m "not browser and not integration"
.venv/Scripts/python.exe -m ruff check . && .venv/Scripts/python.exe -m ruff format --check .
.venv/Scripts/python.exe -m mypy web
```

Commits 1 and 3 also run `npm run lint:md`. No JS or CSS changes, so `ASSET_VERSION` is not
bumped. Commit 3 reports the net line count of its production code.

## [HISTORICAL] Rejected

- **`reconstruct_n` with fancy indexing.** It needs a contiguous range; the candidates are a
  sparse union.
- **Reading `index.xb` or using `faiss.rev_swig_ptr`.** Both bypass FAISS's public API and break
  if the index type changes. All three plans rejected them.
- **A per-index fallback after a failed batch** (Codex). It brings back the silent `[]` on a
  dimension mismatch.
- **A benchmark committed as a test.** It depends on the machine and proves nothing about
  correctness. All three plans rejected it.
- **A `getattr` guard raising `SearchEngineError` if `reconstruct_batch` is missing** (OpenCode).
  Every FAISS `Index` has the method in 1.14.2, so the guard is speculative.
- **`np.vecdot` instead of `einsum`.** Verified bit-identical to today's scores (max difference
  0.0 over 160 candidates at 768 dimensions), but it only exists from numpy 2.0.
  `requirements.txt` does not pin numpy and faiss-cpu accepts `numpy>=1.25`, so a production
  venv on 1.x would fail every search. Revisit once numpy is pinned to 2.x.
- **Bit-identical scores from a per-row `np.dot` loop.** It keeps the Python loop this entry
  exists to remove.

## [HISTORICAL] Review record

**Round 1: Codex `gpt-5.6-sol`, high effort, read-only, 2026-09-16.** Six gaps and three
challenges. All nine were checked against the code. Eight were accepted in full; the ninth, the
NaN-document drop, was accepted as out of scope.

- **Blockers:**
  - Nothing archived the plan.
  - The clamp mutation named a test that only counted rows, so it could not fail.
- **Should-fix:**
  - The plan never said that batch errors now escape `combine`. Following this up found the
    dimension-mismatch refusal.
  - No asserts on `text`, `category` or `chunk_id`, and no test of the establishment-suppression
    branch.
  - The measurement step contradicted itself and named a loader that needs arguments.
- **Nit:** the grep claim did not count this plan's own hits.
- **Decisions reversed:**
  - set-order ties;
  - rejecting the counting test;
  - the segfault argument against a fallback.

**Round 2: same session, 2026-09-16.** It confirmed that all six round-1 fixes landed, and that
the `ValueError` is raised after lexical scoring. It found four new gaps, all accepted:

- Test 3 claimed its lexical scores change; only `query_text` changes.
- The archive filename said "build date", which could be confused with the corpus build.
- The archive step named one frontmatter key instead of all six.
- `sorted()` also reorders warnings and exception logs.

Claude also corrected one of its own claims in that round: the proxy test fails against the old
code on the call count, not on an exception.

## [HISTORICAL] Build record

Built in plan order on 2026-09-16: commit 1 (dead-map deletion with its TODO closure),
commit 2 (characterization tests, no production change), commit 3 (four new
behaviour-pinning tests shown failing against the old code, then the batched rewrite,
then the dead `embedding_dimension` removal, then this archive).

Departures from the plan text, in the order they were found:

- The measurement step names a `git worktree` for the old implementation. With nothing
  committed there was no old commit to check out, so the build extracted HEAD's
  `result_combiner.py` to a temp path and loaded both classes by file path instead. The
  workload is otherwise as specified: 50 seeded queries, 80 semantic + 80 lexical ids
  each, 200 timed rounds alternating old and new.
- The mutation table's two wrong rows were corrected during the build (see the
  reversals above); all five corrected mutations were then re-proven against the final
  test file, and each fails exactly the named test(s).
- The `embedding_dimension` removal was a review-found addition to the plan itself:
  only the deleted per-index helper read it.
- Test-file simplifications, review-directed, with the plan's test names and assertions
  intact: the expected table is a header tuple plus one tuple per row; the rows
  comprehension carries a `# fmt: off` / `# fmt: on` pair (a trailing `# fmt: skip`
  inside the comprehension is rejected by RUF028, and the long row tops 100 columns)
  and `strict=True` on the `zip` (bare `zip` trips B905 under the py310 target) — both
  first-of-their-kind in this repo. The batch proxy reuses the fixture's builder
  (`_build_index` / `_build_combiner`) instead of poking `_faiss_index`.

Measured on the real index (4,545 chunks x 768 dimensions, 160 candidates per query):
build run, seed 20260916, old median 11,804.8us per combine against new 9,886.3us
(-1,918.5us, about -16%), equivalence 50/50 same order with scores within 1.8e-7;
reviewer re-run with its own seed and workload, old median 9,967us against new 8,211us
(-1,756us, about -18%), 0 mismatches over 50 queries. The throwaway scripts were kept
outside the repo and deleted afterwards.

Gates on the finished tree: the full non-browser/non-integration suite green
(1,084 passed, 1 skipped), `ruff check` and `ruff format --check` clean,
`mypy web` clean, `npm run lint:md` clean. No JS or CSS changed, so `ASSET_VERSION`
was not bumped. Net production code for commit 3: 23 insertions, 31 deletions
(-8 lines).

## [HISTORICAL] Open questions

None blocking. If the real-index measurement shows no speed gain, commit 3 still stands on the
bug fix, the deleted helper and the earlier bounds check.
