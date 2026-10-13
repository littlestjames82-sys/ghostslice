# G02 Audit — Task selection v2 (v0.7.0)

Goal: symbol-name matching + one-hop import-graph boosting layered on
the v0.5 TF-IDF task selection, with the per-file score breakdown
exposed on the CLI and in bundle manifests. Baseline 173 tests
(v0.6.0); the build (recovered after the first G2 agent died in a
daemon restart, diff adopted and reviewed file by file by the parent)
brought the suite to 190 (17 new in tests/test_v07_task2.py).

Build adoption review (before Audit #1): every spec point verified
present in the diff — SYMBOL_EXACT_BONUS 15.0 / SYMBOL_PART_BONUS
10.0 / SYMBOL_CAP 25.0 per file; GRAPH_BOOST_FRACTION 0.25 of the
strongest adjacent seed, GRAPH_BOOST_CAP 6.0, max-not-sum; Python
symbols via `ast` with the slicer fallback for unparseable files,
other languages via the slicer's own signatures output (no second
parser); `select_for_task_breakdown` additive next to the legacy
`select_for_task` shape; manifest `score` / `score_components`
additive and only when task_scores are passed. All four golden
outcomes are tested (symbol-only beats body-mentions, boost pulls in
a direct dependency AND an importer, hub not dragged in by
popularity, v0.5 rare-word A/B unchanged).

## Audit #1 (after build)

### F1 [MEDIUM] Python module/class constants are not symbols
`_py_symbols` walks only FunctionDef/AsyncFunctionDef/ClassDef
names. `INVOICE_LIMIT = 5` or a class attribute defines a symbol a
task word should match exactly like a def name — arguably a stronger
one, since the TF-IDF body counter tokenises `invoice_limit` as one
word and a keyword "invoice" earns nothing from the text either. Fix:
also collect simple Name targets of Assign/AnnAssign (module level,
class body, anywhere `ast.walk` reaches), including names inside
tuple/list targets.

### F2 [LOW] Symbol extraction runs the slicer on every file, match or not
For every non-lockfile file, selection slices the source to
signatures (parser-lite) just to harvest names, even when no keyword
could possibly match any symbol in that file. A symbol bonus implies
a textual trace: exact tier means the (lowercased) symbol name
appears in the source; part tier means a camelCase/snake_case part
of it appears; the subset tier means every part of the keyword
appears. So if no part of any keyword (split_symbol_name of the
keyword, which includes the keyword itself) appears in the
lowercased file content, the symbol component is provably 0 and the
extraction can be skipped. Fix: gate the extraction on that
substring prefilter; unit-test the gate and rely on the golden
tests to prove matches still fire with it on.

### F3 [REVIEWED, SOUND] Budget cannot be exceeded by boosts
Stage A takes seeds with the v0.5 rule (skip when spent + sliced >
budget, best file always in). Stage B re-checks `spent + stoks >
effective_budget` before every take, boosts only reorder stage B,
and boosted files never displace a seed. Zero-sliced-token boosted
candidates are skipped. test_boost_respects_budget_exactly pins all
three budget shapes (full / full-1 / seed-only). No overflow path
found.

### F4 [REVIEWED, SOUND] Boost source is CHOSEN seeds only
seed_base is built from rows actually taken in stage A, so a file
that scored well but was budget-skipped lends no boost to its
neighbours. This is the right semantics — boosting from unselected
content would let excluded files pull in still more content and
muddy what "within budget" means — and the module docstring says
seeds are the selected set. The README wording added in this goal's
docs pass states it explicitly ("neighbours of the files actually
selected").

### F5 [REVIEWED, SOUND] Tie-breaks and determinism
Both stages sort by (-score, -entry.tokens, scan index), matching
the v0.5 tie-break (larger file first, then scan order; the v0.5
code relied on sort stability for the last key, the index makes it
explicit). Graph adjacency comes from build_graph over the scan
result (deterministic order). test_deterministic_across_runs
compares full chosen lists and breakdown dicts across two runs.

### F6 [REVIEWED, SOUND] One signal swamping the others
Symbol component capped per file at 25.0 (tested with 4 part
matches = 40 uncapped). Graph boost capped at 6.0 AND max-based, so
a hub imported by three seeds earns the same as one imported by one
(tested: graph < sum-based − 0.5). TF-IDF itself keeps the v0.5
caps (tf ≤ 20, path boost weighted by idf). A symbol exact match
(15) can outrank ~9 capped rare-word body mentions — deliberate,
documented in the weights comment: a definition IS the strongest
relevance signal this tool has.

### F7 [REVIEWED, SOUND] Malformed files cannot crash extraction
`_py_symbols` catches Exception around ast.parse (RecursionError
and MemoryError are Exception subclasses) and falls back to the
slicer's def-line extraction; `_lite_symbols` catches Exception
around slice_source and returns an empty set. The never-raises test
feeds truncated declarations in all 10 slicable languages.

### F8 [REVIEWED, SOUND] Manifest / API compatibility
Manifest fields are additive and opt-in (build_bundle without
task_scores produces byte-identical entry shapes — tested). The
legacy select_for_task scores dict now also contains boosted
zero-base files (additive; values are the same totals the breakdown
reports — consistency tested). MCP and the dashboard do not call
select_for_task; the only caller is the CLI, which now prints the
component breakdown per chosen file (tested, incl. manifest
round-trip through validate_bundle).

### F9 [TEST QUALITY, ACCEPTED] One golden test pins the boost formula
test_boost_pulls_in_dependency_and_importer asserts the boost
equals min(GRAPH_BOOST_CAP, GRAPH_BOOST_FRACTION × seed total).
That is implementation-shaped, but the weights ARE the documented
contract of this goal (they are what the README publishes), and the
same test plus the hub tests assert the outcome-level properties
(inclusion, max-not-sum, popularity alone insufficient). Accepted;
no change.

### F10 [LOW] `_lite_symbols` harvests const/let/var/val names
Signatures output has bodies stripped, so harvested names are
declarations in practice; keyword-shaped names are filtered via
_NOT_SYMBOLS and 1-char names dropped. A kept initialiser line in
some lite language could in principle contribute a variable name —
that is still a defined symbol in that file, so a match is
defensible. No change.

## Improve #1 (fixes applied, suite 190 -> 195)

- F1: `_py_symbols` now also collects simple assignment targets at
  module level and in class bodies (Assign and AnnAssign; tuple /
  list / starred targets unwrapped; Attribute/Subscript targets bind
  nothing). Function-local variables are deliberately NOT symbols —
  a local named like the task is a body mention, and the TF-IDF
  layer already scores it. Tests: module + class constants extracted
  and earn the part bonus end-to-end with tfidf 0; a function-local
  `invoice = ...` earns symbol 0.0 while its TF-IDF stays positive;
  `obj.invoice = 1` / `store['invoice'] = 2` bind no names.
- F2: symbol extraction is gated by `_any_keyword_part_in`: if no
  part of any keyword (split_symbol_name, which includes the keyword
  itself) appears in the file's lowercased content, the symbol
  component is provably 0 and the slicer/ast extraction is skipped.
  The file's lowered text is now computed once and shared between
  the TF counter and the gate. Gate unit tests cover the snake,
  camel-hiding, and no-match cases; all golden symbol tests still
  pass with the gate on, which is the no-false-negative evidence.
- The module docstring's symbol paragraph now names module/class
  assignment targets as part of the Python symbol set.

## Audit #2 (of the build + Improve #1 fixes)

### G1 [LOW] The F2 gate recomputes keyword parts for every file
`_any_keyword_part_in(keywords, text)` rebuilds the parts set from
the keywords on each call, and selection calls it once per file —
the perf fix has a (small, keywords-sized) per-file wart. Fix in
Improve #2: split the helper into `_keyword_parts(keywords)` +
`_keyword_parts_in(parts, text)`; selection computes the parts once
and reuses them. The public-ish wrapper keeps its signature for the
round-1 tests.

### G2 [REVIEWED, SOUND] F1 collection scope edges
- A ClassDef nested inside a function is found by ast.walk, so its
  attributes count as symbols. Consistent: its methods already
  counted in the build (defs at any depth), and a class attribute
  is a definition regardless of where the class is built.
- Bare annotations (`LIMIT: int` with no value) count: the name IS
  declared at module level. AugAssign (`x += 1`) does not count:
  it binds nothing new. Walrus targets inside module-level
  expressions are not collected — a vanishingly rare way to define
  a module constant; noted, not worth a second walk.
- No regressions from F1 elsewhere in the suite (all pre-existing
  selection/export tests pass unchanged at 195): constants named
  like task words in unrelated fixture files did not reorder any
  existing expectation.

### G3 [REVIEWED, SOUND] F2 gate has no false-negative channel
Symbols are extracted from the file's own text (ast over it, or the
slicer's signatures of it), so every matchable name — whole or
part — textually appears in that text, lowercased for comparison on
both sides. The gate checks content only, not the path: correct,
because filename relevance is already scored by the TF-IDF path
boost and a symbol cannot live in a path. Files the gate closes
skip BOTH the lite slicer and the Python ast parse.

### G4 [REVIEWED, SOUND] Empty project and budget 0 under v2
No entries: weights compute with N=0 (idf stays finite via the
smoothing), no seeds, no graph stage, empty selection — same shape
as v0.5. Budget 0: the stage-A best-file rule still takes the top
seed (chosen is empty at that check), stage B then adds nothing
since spent > 0 — pinned by the budget=1 hub test's shape.

### G5 [REVIEWED, SOUND] Breakdown totals for untaken candidates
A stage-B candidate that does not fit reports a total including its
graph component even though it was not taken. The breakdown is a
candidate report (docstring says chosen or not; the CLI prints only
chosen files), and the legacy scores dict mirrors the same totals
for consistency. Deliberate; no change.

## Improve #2 (fixes applied, suite 195 -> 196)

- G1: gate split into `_keyword_parts(keywords)` (computed once per
  select_for_task call) and `_keyword_parts_in(parts, text)`;
  `_any_keyword_part_in` remains as a wrapper so the round-1 gate
  tests keep pinning the public behaviour. A new test asserts the
  precomputed-parts path and the wrapper agree on matching and
  non-matching text.
- Docs precision (README, this goal): the task-v2 section states
  that graph boosts flow from the files actually selected, and that
  Python constants/class attributes count as symbols while
  function-local variables do not.

Final state: 196 tests passed (173 baseline + 23 new across the
build and both improve rounds), version 0.7.0, `ghostslice
secrets .` exits 0. Committed locally; push/release is the parent's
step.
