# Polish Round 5 Audit — v1.0.5

Baseline: v1.0.4, local HEAD `30acf74`, 892 tests passed
(parent-verified), remote `362dac1`. Target: depth, parity, and
documentation structure. Standing gates held throughout:
zero-dependency stdlib only, no PyPI publish, no announcements,
`.ghostslice-history.jsonl` unstaged, no `.ghostslice-cache`
committed, no push (local commit only).

Result: **925 tests passed, 1 skipped, 9 subtests** (33 new in
`tests/test_v30_polish5.py`). Token counts below are estimates,
labelled as such, and paired numbers always use one method
(`ghostslice.tokens.estimate_tokens` on raw text) per pair.

---

## Item A — Lite-language depth, pass 2

Discipline as in round 4: fixture first, behaviour demonstrated
broken (outline / symbol selection / signatures evidence),
fix only proven gaps, cases that already work dropped with
evidence.

### A1. Rust TYPE declarations with multi-line `where` clauses — FIXED

Before (fixture: trait `Greeter` with a multi-line `where`,
struct `Pair<T>` with one): the trait's span ended at the first
method's `;` line, its methods never enumerated, and `greet`
leaked into the outline as a parentless free function; the
struct's span was one line. This was the recorded POLISH_104
remainder (impl-side `where` was fixed in v1.0.4; type-side was
not).

Fix: `symslice._rust_region`'s type branch now locates the
block brace with the same `_find_block_brace` lookahead the
impl branch uses and ends the span with `_brace_end`;
`slicer._lite_signatures` gained a `_block_span` helper and a
`;`-terminated-declaration branch so such types render whole
instead of dropping the header (traits) or the type (structs).

After: `Greeter` spans its body; `Greeter.name` /
`Greeter.greet` enumerate and resolve for selection; unit and
tuple structs keep their statement spans (pinned).

### A2. C# `record` / `record struct` as containers — FIXED (3 bugs)

Before (fixtures: K&R and Allman records, a control class):
1. `record struct` / `record class` were outlined under the
   names "struct" / "class" — the name capture took the second
   kind word.
2. Record bodies never recursed, so no member of any record
   ever enumerated.
3. Allman braces (the C# default style) truncated EVERY
   Java/C# container span at its first member's `;` — methods
   of Allman classes and interfaces were equally invisible,
   and signatures mode dropped such types whole.

Fixes: the JV name pattern accepts the two-word record kinds;
the recursion condition includes records; type and method-head
spans locate the block brace before judging a declaration a
statement (`_find_block_brace`, plus a method-head branch in
signatures mode). A fourth gap fell out of the fixtures:
**expression-bodied methods** (`public double Total() => ...;`)
matched no method pattern anywhere; the pattern now accepts
the `=> ...;` ending, with arrow-first guards so braces inside
an expression (interpolation, lambdas) are never treated as a
body brace.

After: `Person.Rename`, `Point` (real name, statement span),
`Order.Total`, `Control.Work`, `Shapes.Perimeter/Describe`
all enumerate with correct parents and spans; constructors
remain non-symbols (control-pinned, unchanged).

### A3. PHP 8 enums (the chosen third case) — FIXED

Before (fixture: backed enum with cases + a method, a class
with a `switch`): the enum was kind "class", its cases — the
enum's whole value surface — could not be named for selection,
and signatures/interfaces modes DROPPED every `case` line
(the enum was members-reduced like a class).

Fixes: `enum` joins PHP's declaration kinds (rendered whole,
like interfaces and traits); enum `case` lines become named
`constant` symbols, gated on an enum parent so `switch` labels
never become symbols; the extra-language signatures/members
gates use `_find_block_brace` so PSR-12 Allman declarations
keep their bodies.

After: `Suit` is kind "type"; `Suit.Hearts` / `Suit.Diamonds`
resolve and select; signatures and interfaces modes render
the enum whole, cases included.

### Dropped with evidence (not fixed)

- **Swift extensions**: demonstrated working end to end on the
  fixture (outline, selection, signatures). No change.
- **Kotlin data classes**: work, EXCEPT primary-constructor
  properties (`val name` on the declaration line) are not
  nameable symbols. Recorded as a known limitation; signatures
  mode keeps them on the declaration line, so no content is
  lost. Smaller and lower-value than the three fixed cases.
- **C# expression-bodied properties** remain unenumerated —
  consistent with ALL Java/C# properties in the lite parsers
  (properties are not symbols in this layer, by design).

---

## Item B — MCP parity for read-only insights

Parity audit (CLI read-only insights vs MCP tools at v1.0.4):

| CLI insight | MCP before | MCP after |
|---|---|---|
| scan | `scan_project` | — |
| slice / outline | `slice_file` | — |
| cost estimate | `estimate_cost` | — |
| export | `export_bundle` | — |
| secrets | `check_secrets` | — |
| lint | `lint_project` | — |
| graph (import/entry) | — | **`project_graph`** |
| history (ledger analytics) | — | **`project_history`** |
| doctor | — | **`doctor`** |

New tools follow the existing envelope: same JSON result
shape, path containment, and error style; summaries + caps,
never raw dumps. Caps are module constants:
`GRAPH_FILE_CAP = 100` files of adjacency (with project totals
and truncation flags), `GRAPH_LIST_CAP = 100`,
`HISTORY_RUN_CAP = 50` most-recent runs in the per-run detail
(aggregates and percentiles always cover the full filtered
set; the raw ledger `records` are never returned).
`project_history` accepts the v1.0.3 `since` / `top` filters
and returns p50/p90 with the same semantics as the CLI; a bad
`since` is a clean tool error.

**Doctor decision**: `run_doctor` is read-only by contract —
it never writes; its remedies are text. It therefore fits the
read-only surface and is included as the `doctor` tool. Its
plugin-load check runs under the same standing profile opt-in
as the other tools.

**Stays CLI-only, with reasoning**: watch and serve (long-lived
stateful processes), init / redact / cache clear (writes),
report-file generation (writes), and the aggregate gates
`ci` / `check-budget` (their value is the exit code in a
pipeline, which the tool envelope does not carry).

Payload sizes measured on this repo (Audit #2):
`project_graph` 36,469 bytes (cap engaged: 100 of 140 files,
totals + truncation flags present), `project_history` 12,165
bytes, `doctor` 1,990 bytes. All are summaries an agent can
hold; none is a raw dump.

Tool surface: 6 → **9 tools**. Parity surfaces updated: README
MCP mentions + feature map, `docs/operations.md` tool list,
`docs/reference.md`, module docstring (now states the parity
rule), and the two tool-surface pins in `tests/test_v03.py`.

---

## Item C — README extraction into `docs/`

Before: no `docs/` directory; README 75,491 bytes, 25,279
estimated tokens, tripping the tool's own L001 oversize
warning (one of five documented self-lint warnings).

After: README is a landing page — pitch, Install, Quickstart,
"What's in 1.0" feature map, the flagship Usage dives (Scan /
Slice / Export), Documentation index, Troubleshooting, Tests,
Layout — at **15,638 bytes, 308 lines, 5,328 estimated
tokens**. The deep reference moved into eight files:
`docs/commands.md` (8,389 est. tokens), `docs/profiles.md`,
`docs/history.md`, `docs/operations.md`, `docs/dashboard.md`,
`docs/languages.md`, `docs/plugins.md`, `docs/reference.md`
(21,309 estimated tokens in total; README + docs therefore
exceed the old single-file estimate only by the new index,
titles, and cross-reference glue — nothing shrank).

**No-content-lost proof** (mechanical, fence-aware split +
independent verifier): 0 heading texts from the old README
are missing across README + `docs/`; the only added headings
are the eight declared docs titles; 26 internal links checked
with the GitHub anchor algorithm, 0 broken. 29 old body lines
do not appear verbatim — every one is a deliberate, listed
edit: heading-level promotion in moved files, cross-reference
pointers replacing in-line text (feature-map intro, modes-table
cells, calibration and secret-guard pointers), the MCP tool
list updated for item B, the symbol-limits paragraph updated
for item A, three code-docstring pointers (`plugins.py`,
`doctor.py`, `exporter.py`) repointed at `docs/`, and the
known-warnings note rewritten (five warnings → four; the L001
entry removed because it is fixed, with a v1.0.5 note).

Self-lint: **5 → 4 warnings**; the remaining four are the
documented ones (L002/L003/L006/L007 classes on known files).
Repo scan: 140 files, 548,766 estimated tokens. Dogfood CI:
PASS, sliced context 179,785 estimated tokens — see F2.

---

## Audit #1 findings → Improve #1

- **F1 — presets fell off the landing page.** All seven preset
  names (`claude-code`, `aider`, `generic`, `cursor`,
  `copilot`, `anthropic-xml`, `json`) lived only in the moved
  Profiles text; `test_preset_consistency` requires them in
  README.md. Fixed: the flagship Export section now names all
  presets in backticks with a pointer to `docs/profiles.md`
  (new landing glue; no old content duplicated or lost).
- **F2 — dogfood CI budget at 99.9%.** The docs tree is real
  scanned content, and the sliced total reached 179,785 of the
  workflow's 180,000 budget — one ordinary commit from a red
  gate. Handled by the workflow file's OWN documented rule
  (~30% headroom over the measured total, re-measurement notes
  appended in place, as at v1.0.0): budget re-measured to
  230,000 with the note recorded in
  `.github/workflows/ghostslice-ci.yml`; the two pins in
  `tests/test_v24_ci.py` moved with it. CI still exits 0.

## Audit #2 findings → Improve #2

Fresh eyes on the moved sections and the new parser paths:

- **Link rot**: beyond the 26 markdown links, every
  repo-relative path referenced from `docs/` was checked —
  `examples/completions/`, `examples/plugins/lua_slicer.py`,
  `examples/plugins/README.md`, `examples/github-action/` all
  exist; `docs/` contains no image references; README badges
  are absolute URLs (unchanged).
- **MCP payload sizes on this repo**: measured above; caps
  engage honestly with totals + truncation flags.
- **Comment/string adversaries in the new fixtures**: Rust
  where-trait with `}` in a comment and `"{"` in a string —
  spans exact. C# Allman record with the same adversaries —
  spans exact. PHP: a `;` inside a case value string is fine.
- **F3 — PHP enum case with a trailing comment was
  invisible** (`case Plain = 'n'; // note`): the case pattern
  demanded end-of-line at the `;`. Fixed: the pattern allows
  a trailing `//` or `#` comment; pinned in
  `test_v30_polish5.py`.

## Dogfood self-checks (final tree)

- `ghostslice secrets .` → exit 0, no likely secrets.
- `ghostslice lint .` → exactly the 4 documented warnings.
- `ghostslice calls . --dead` → 0 candidates.
- `ghostslice doctor .` → healthy (9 ok, 1 pre-existing
  ledger-size warning).
- `ghostslice ci .` → PASS (budget per F2 re-measurement).
- GhostBus demo export unchanged (129,555 → 45,770 estimated
  tokens; suite-pinned).
- Dashboard page: zero `.innerHTML` (suite-pinned).

## Existing pins changed (complete list)

1. `tests/test_v03.py` — MCP tools/list name set (6 → 9 tools,
   item B) and the stdio `len(tools)` count 6 → 9.
2. `tests/test_v25_release.py` — release version pin
   1.0.4 → 1.0.5 (and its comment), the standing per-round pin.
3. `tests/test_v24_ci.py` — dogfood budget 180000 → 230000 and
   the workflow structure string, per F2's re-measurement.

No other existing test was modified; none was weakened.

## Limitations carried forward

- Kotlin data-class primary-constructor properties are not
  nameable symbols (A3 notes); declaration-type rendering
  keeps them visible in signatures mode.
- Java/C# properties (including expression-bodied ones) are
  not symbols in the lite layer — unchanged, by design.
- Watch and dashboard behaviour unchanged this round.
- The dogfood sliced total (179,785 estimated tokens) will
  keep growing with the repo; the budget rule in the workflow
  file governs future re-measurement.
