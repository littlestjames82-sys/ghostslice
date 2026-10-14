# Polish Round 6 Audit — v1.0.6

Baseline: v1.0.5, local HEAD `f14d263`, 925 tests passed
(parent-verified), remote `0e5876f`. Target: completeness +
developer-experience polish. Standing gates held throughout:
zero-dependency stdlib only, no PyPI publish, no announcements,
`.ghostslice-history.jsonl` unstaged, no `.ghostslice-cache`
committed, no push (local commit only).

Result: **948 tests passed, 1 skipped, 9 subtests** (23 new in
`tests/test_v31_polish6.py`). Token counts below are estimates,
labelled as such.

---

## Item A — Kotlin primary-constructor properties are symbols

Demonstration first (fixture: single-line and multi-line data
classes, a plain class with `private val`, an annotated
parameter). Before this round:

- Single-line heads: constructor properties appeared NOWHERE in
  the outline. `slice --symbols User.name` matched nothing.
- Multi-line heads were actively broken: the class span
  truncated to the declaration line (the block brace sits past
  the 3-line lookahead), the parameters leaked into the outline
  as parentless top-level `constant`s, the `@Deprecated`
  parameter vanished entirely (annotation prefix defeats the
  top-level property pattern), the class's own methods lost
  their parent (`total`, not `Order.total`), and signatures
  mode dropped the declaration line while floating the
  parameter lines as orphans. Interfaces mode dropped the class.
- Task selection already saw most property NAMES textually (it
  reads the signatures output), except the annotated one —
  which was invisible to every surface.

Fix: shared constructor-head machinery in `slicer.py`
(`_kt_ctor_span`, `_kt_head_brace`, `_kt_ctor_head`,
`_kt_ctor_params`): locate the primary constructor's parameter
list (the `(` after the type name and an optional generic list;
a `:` first means supertypes, not a constructor), split it at
top-level commas over quote-masked text (paren/bracket/brace
depth plus a heuristic angle depth for generic types), and take
each segment's first depth-0 `val`/`var` as a property —
Kotlin's own rule, applied to data classes and plain classes
alike (decision: identical treatment; a parameter without
`val`/`var` is not a member in either and stays unlisted,
pinned). The outline emits them as `attribute` symbols of the
class with spans inside the head; member walking starts after
the head. Signatures mode renders multi-line heads whole
(header = every head line) and body-less constructor classes
render their head instead of leaking parameter lines.

Rendering safety (the double-render question): a constructor
property's span sits inside its class's head span, and
`_render_symbol`'s container path skips children that start
before the head's end — so the property ships exactly once, via
the head, exactly like the always-context a body property gets.
Pinned: selecting `Order.note`, or a sibling method, puts each
parameter line in the output exactly once.

After (same fixtures): `User.name`, `User.age`, `Repo.db`,
`Repo.cacheSize`, `Order.id/note/legacy/secret` all outline as
attributes of their classes; `Order` spans its whole body with
`head_end` at the `) {` line and `Order.total` parented.
Adversaries verified by fixture or probe: defaults with commas
and parens in strings, a wrapped string-template default
containing `${fmt(1, 2)}` (span covers both lines), a lambda
default, `Map<String, List<Int>>` generic types, annotations
including use-site targets (`@param:` / `@field:`), enum-class
properties, classes with supertype lists (same-line and
wrapped), bounded generics (`<T : Comparable<T>>`), nested
classes, body-less classes, escaped quotes and char-literal
commas in defaults.

## Item B — `GET /api/calls`: per-symbol call lists

The bulk `/api/graph` payload caps edges at 2,000; this repo's
graph now has 4,746 edges, so most relationships never reach
the panel (POLISH_102's recorded remainder). New endpoint,
served from the SAME memoised build: `_State` keeps the
uncapped `build_call_graph` result next to the capped payload
(`_calls_full`), and `symbol_calls()` runs `calls_payload()`
first — the single build trigger — so the warm-up/lazy
interplay and the stored-failure semantics are exactly
`/api/graph`'s (a request during the build waits on the lock;
a failure raises on the endpoint path and other endpoints keep
serving; both pinned).

Contract: `GET /api/calls?symbol=<id|qualified>`.
- A symbol id (`util.py:helper`, what the panel holds) always
  wins; a bare qualified name resolves when unique.
- A qualified name matching several files answers 200 with
  `{"ambiguous": true, "matches": [...]}` — never a silent pick.
- Unknown symbol: 404 `{"error": "no such symbol: ..."}`,
  matching the content endpoints' error style; missing
  parameter: 400.
- Response: the symbol row; `callers` / `callees` /
  `referenced_by` rows (`id`, `qualified`, `path`, `kind`,
  `sites`; module-level callers render as `<module>`), each
  list capped at `CALL_LIST_CAP = 500` with a true total and a
  truncated flag beside it; `dead` read from the uncapped dead
  list; the Python-only scope line and an honesty note.

Panel wiring: when the bulk payload is truncated, each symbol
grows a "complete lists" button; fetching swaps that symbol's
lists for the endpoint's, tags `possibly dead` from the
uncapped data too, and prints whether the fetched lists are
complete or themselves capped (with totals). All rendering
stays createElement + textContent — the served page still
contains no `.innerHTML` (pinned). The bulk note now says the
lists may be incomplete and points at the button.

Evidence on this repo: the bulk payload is byte-identical to
the v1.0.5 construction (verified by rebuilding it from a
fresh `build_call_graph` and comparing dicts). The repo's
highest fan-in symbol has 134 distinct callers; the endpoint
returns all 134 (22,794 bytes) where the bulk payload can only
carry whichever of its edges fall inside the first 2,000.

## Item C — test-suite speed

Baseline measured in this environment with
`pytest --durations`: **84.29s** wall for the 925-test suite
(the ~150s figure in the round brief is the same suite under
heavier machine load; all numbers below are single-machine,
same-session comparisons). Per-file sums pointed at three
places: `test_v20_perf.py` (two tests run six full exports over
a 2,000-file synthetic tree), the dashboard family (~35 tests
at ~0.58s each), and repo-self tests that pay full product runs
(intrinsic; left alone, see below).

Two changes, both test-infrastructure only:

1. **Serve poll interval.** Every HTTP-server test booted
   `serve_forever` with the default 0.5s poll interval, so each
   `shutdown()` waited out up to half a second of pure sleep.
   Measured directly: one boot+shutdown costs 0.506s at the
   default vs 0.025s at `poll_interval=0.02`. All 18 serve sites
   across 13 test files now pass `poll_interval=0.02`. The poll
   interval only bounds shutdown latency; request handling is
   untouched (the server is threaded).
2. **Big tree halved.** `_gen_tree`'s synthetic tree goes from
   2,000 to 1,000 files. The tests pin a warm/cold CPU ratio
   (>= 3x) and byte identity across worker counts — both
   size-independent; the ratio was re-measured at the new size
   at 4.7x (cold-off 1.04s CPU vs warm 0.22s), the same margin
   class as the ~5x recorded at 2,000.

Result, like for like at 925 tests: **84.29s -> 50.65s
(-39.9%)**; the round's 23 new tests then bring the suite to
948 tests running in 56–61s on final verification (two runs:
61.16s, 56.10s) — still well under the old suite's time at
fewer tests. Top offenders, before -> after (call phase):

| test | before | after |
|---|---|---|
| v28 graph cache parity (this repo) | 7.75s | 8.24s (repo grew; intrinsic) |
| v20 warm >= 3x faster | 7.37s | 4.39s |
| v20 workers identical (big tree) | 5.53s | 4.75s |
| v26 repo has no dead candidates | 3.75s | 3.82s (intrinsic) |
| v24 dogfood budget (this repo) | 3.24s | 3.40s (intrinsic) |
| v22 dashboard tests (max single) | 1.20s | ~0.6s, most now < 0.1s |

The after-list's head is now entirely tests whose cost IS the
product running over this repo (graph parity = 2 full graph
pipelines; dogfood CI; dead-candidates) — recorded as the
deliberate remainder rather than hollowed out. No genuinely
slow product path was exposed by the profiling: the two fixes
were test-harness artefacts (a sleep and an oversized fixture).

**Assertion-identity proof**: `git diff` over `tests/` for the
whole round was reviewed line by line. Changed lines are
exactly: 18 `serve_forever` target lines (poll interval), the
big-tree default + its comment in `test_v20_perf.py`, the
version pin + its comment in `test_v25_release.py`, and nothing
else. Exactly ONE changed line in the diff contains `assert`:
the version pin itself (`"1.0.5"` -> `"1.0.6"`), the pin this
round is allowed to move. No test was skipped, xfailed,
deleted, or re-asserted; the count is 925 + 23 new = 948 with
the same 1 pre-existing skip. No dependency was added; the
suite runs under plain `python3 -m pytest tests -q`.

## Audit #1 findings -> Improve #1

- **F1 — nested generics split wrongly.** `Map<String,
  List<Int>>`: the closing `>>` run was not counted (the
  angle-close rule required an alphanumeric before `>`, and
  the second `>` follows a `>`), so the parameter after the
  generic-typed one merged into its segment and was lost
  (`Cfg.plain` missing). Fixed: `>` joins the accepted
  predecessors. Pinned by `test_awkward_forms`.
- **F2 — the author's own test expectations were wrong, not
  the code** (Order span arithmetic; edge sort order puts the
  module pair elsewhere than assumed). Tests corrected; the
  bulk-truncation pin was rebuilt on a pair provably last in
  sorted order.
- Bulk-payload identity probe (above) run and clean; the
  endpoint's module-level caller rows probed (`<module>` ids
  resolve to qualified `<module>` + path).

## Audit #2 findings -> Improve #2

- **F-A2 — body-less Kotlin heads stole the next class's
  brace (pre-existing, fixed).** `data class Marker` followed
  by another class: the outline's 3-line brace search crossed
  into the following declaration and reported the second
  class as a nested child, span covering both (reproduced on
  the stashed v1.0.5 baseline). Kotlin is where body-less
  classes are idiomatic (marker data classes, `interface
  Callback`, sealed hierarchies), so the search now takes a
  declaration-stop predicate (`_find_block_brace(stop=...)`,
  `_declaration_stop`) at the Kotlin call sites — outline,
  signatures gate, and nested-member checks. Signatures mode
  additionally renders a body-less Kotlin declaration line
  verbatim instead of dropping it. Allman classes, wrapped
  supertype heads, and braced neighbours verified unaffected;
  pinned by `TestKotlinBodylessHeads`.
- **Adversaries re-run**: string templates with `${}` braces
  in defaults (pinned in the Cfg fixture), char-literal and
  escaped-quote commas (probed clean), use-site annotation
  targets (probed clean), the gated-build `/api/calls`
  request pinned waiting-then-served, the high-degree hub
  pinned against a forced per-list cap of 2.
- **Test-diff review** (Item C's proof, above): clean.
- Incident, recorded for honesty: the stash-based baseline
  check for F-A2 left a stale `__pycache__` whose timestamps
  let Python load the pre-bump `__version__`; four tests
  failed on the version-agreement checks — the machinery
  working as designed. Cache cleared; suite green since.

## Dogfood self-checks (final tree)

- `ghostslice secrets .` → exit 0, no likely secrets.
- `ghostslice lint .` → exactly the 4 documented warnings.
- `ghostslice calls . --dead` → 0 candidates.
- `ghostslice doctor .` → healthy (9 ok, 1 pre-existing
  ledger-size warning; version 1.0.6 agrees with pyproject).
- `ghostslice ci .` → PASS (186,240 of the 230,000 budget).
- GhostBus demo export unchanged (129,555 → 45,770 estimated
  tokens; suite-pinned).
- Dashboard page: zero `.innerHTML` (suite-pinned), new panel
  JS passes `node --check`.

## Existing pins changed (complete list)

1. `tests/test_v25_release.py` — release version pin
   1.0.5 → 1.0.6 (function renamed to match), the standing
   per-round pin.
2. Item C test infrastructure (no assertion touched; proof
   above): `poll_interval=0.02` at 18 serve sites across
   test_server_cli, test_v04, test_v05, test_v11_lint,
   test_v12_detect, test_v13_monorepo, test_v14_history,
   test_v22_dashboard (5), test_v23_plugins, test_v26_polish,
   test_v27_polish2, test_v28_polish3 (2), test_v29_polish4;
   big-tree default 2,000 → 1,000 files in test_v20_perf.py.

No other existing test was modified; none was weakened. No
CLI flags changed, so the completions examples are untouched
and the drift test passes as-is.

## Limitations carried forward

- PHP 8 constructor property promotion (`__construct(private
  string $name)`) is not symbolised — the promoted properties
  ride the `__construct` method symbol, as before. The Kotlin
  machinery does not transfer directly (promotion lives in a
  method head, not a type head); recorded, not attempted.
- Kotlin's `constructor` keyword form (`class Foo @Inject
  constructor(...)`) and a same-line leading annotation before
  the `class` keyword (`@Foo(1) class Bar(...)`, not
  type-matched at all) remain unrecognised — both pre-existing
  lite limits, unchanged.
- Angle-depth tracking for generic types is a heuristic: an
  unspaced, unparenthesised comparison in a default
  (`val ok = a<b, val y = 1`) can still merge the following
  parameter into the segment (the parameter is then missing
  from the outline; its text still ships with the head).
  Spaced comparisons and parenthesised defaults are exact.
- Per-symbol endpoint lists are capped at 500 per list
  (flagged, with totals); the CLI `calls` output remains the
  uncapped surface.
- Suite remainder: the slowest tests are now the repo-self
  pins (graph parity, dogfood CI, dead candidates), whose cost
  is the product's own work over this repo and grows with it.
