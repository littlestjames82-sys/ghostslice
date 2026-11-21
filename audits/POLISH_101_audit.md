# Polish Audit — v1.0.1: the tool run on itself, its findings fixed

Round: post-marathon polish (Ryan: "Polish polish polish").
Baseline v1.0.0, local HEAD e676341, 784 tests. No new headline
features; every item below came from GhostSlice's own output on
this repo (lint, calls --dead) or from queued audit tails (G17's
dashboard item). Zero-dependency stdlib only; no PyPI publish,
no announcements — those gates were never opened.

## Before / after (this repo, estimated tokens)

| Probe | Before (v1.0.0) | After (v1.0.1 work) |
|---|---|---|
| `lint .` | 0 errors, 7 warnings | 0 errors, 5 warnings (see F1) |
| `calls . --dead` | 10 candidates, ~1,801 est. tokens, all false positives | 0 candidates |
| `scan .` | 124 files, 476,250 est. tokens | 125 files, 480,815 est. tokens |
| `ci . --budget 180000` | PASS; 476,250 -> 154,117 | PASS; 480,815 -> 155,715 (87% of budget) |
| `doctor .` | healthy (1 known ledger warning) | healthy, same warning; version 1.0.1 agrees with pyproject |
| `secrets .` | exit 0 | exit 0 |
| GhostBus demo export | 129,555 -> 45,770 | 129,555 -> 45,770 (unchanged) |
| Full test suite | 784 passed | 795 passed (11 new), 1 existing pin updated (version, see below) |

Scan totals grew because this round added code and docs (the
call-graph roots, the new test file, this audit, changelog and
README notes) and removed one 379-token duplicate; the sliced
total moved 154,117 -> 155,715 for the same reason. These are
the only user-visible number changes, and both are growth from
added material, not estimator drift: the GhostBus reference
export is byte-identical in its totals.

## Item 1 — self-lint cleanup (L004 / L006 / L007 / L003)

Investigation: `pricing.find_prices_file` searched explicit path,
then cwd `prices.json`, then the checkout root (`parents[2]`),
then the packaged copy — so in a checkout both duplicates were
live (the root one shadowed the package one). The packaged copy
is the one pyproject ships as package data; the root copy existed
only for the checkout-root search step, and no workflow or
MANIFEST referenced it. Resolution (real dedupe):
- root `prices.json` deleted; the `parents[2]` loader candidate
  removed; the cwd `prices.json` override is unchanged (a user's
  own table still wins per run, pinned by an existing doctor
  test).
- `src/ghostslice/prices.json` pretty-printed (parsed data
  verified identical before/after): the file's stated purpose is
  hand-editing, and pretty-printing removes its L006 giant-lines
  shape honestly — the warning described a real readability
  property of the one remaining table.
- ci.py's duplicate-floor comment and README's price/layout
  text updated to the single-table story.
- Remaining warnings are documented, not silenced: L003 on the
  Lua example (loaded by the plugin system, not imported —
  reachability cannot see the loader), L007 x2 on the generated
  completion examples (their content is the example), L006 on
  the calibration fixture (giant lines are its job). README
  gained a "Known warnings on this repo" note under
  Troubleshooting, one line each, plus a cross-reference from
  the completions docs.

## Item 2 — call-graph roots for the plugin contract + public API

All 10 dead candidates were false positives. The rule added is
the loader's own contract (`plugins.load_plugin_module`): a
module is a plugin module when it defines a top-level `register`
function, OR assigns both LANGUAGE and EXTENSIONS at module
level and defines a top-level `slice_text`. Its contract-named
functions (register / slice_text / outline) become roots —
exactly the functions the loader invokes — and everything they
call or reference becomes reachable through ordinary edges. No
other symbol in the file is rooted: a dead helper in a plugin
file still flags (pinned both directions by fixtures).
Public-API classes: the direct methods of a class whose name
appears in its module's `__all__` are roots. This is the general
form of the PluginAPI case (plugins.py already declares
`__all__ = ["PluginAPI", ...]`); no class or module is named in
the rule. textio.read_text_with_encoding: genuinely uncalled
inside src/ (its neighbours decode_bytes/read_text are the used
seams), but it is the documented one-call form of the decoding
policy, so it was declared public via a new textio `__all__`
(and is now exercised by a direct test) rather than deleted or
wired artificially. Result: `calls . --dead` = 0 candidates,
and a dogfood test pins the repo at zero.

## Item 3 — dashboard XSS tail (from G17 audit)

The pre-existing surfaces rendered untrusted strings through
innerHTML: file-table rows interpolated `${f.path}` (the true
vector), the totals block interpolated numbers, init()'s
recommendations interpolated `${r.path}` and `${r.reason}`, and
the treemap created its label spans via innerHTML. All converted
to createElement + textContent (same DOM structure, classes, and
listeners; the row checkbox/select/tokens cells rebuilt node by
node). The last clearing assignment also moved to
replaceChildren(), so the served page now contains no
`.innerHTML` at all — pinned by a test that fetches the page
from a live server and asserts the property is absent and the
textContent assignments are present. Extracted page JS passes
`node --check`. No visual change (identical element/class
structure).

## Item 4 — consistency sweep (checked, no changes needed)

- All 25 subcommand help one-liners: verb phrases, lowercase
  start, no trailing periods. Two label-style helps (`ci`,
  `doctor`) use the same "name: phrase" shape as each other.
- Programmatic check of all 80 help strings in cli.py: 0 end
  with a period; 79 start lowercase; the single capital start
  is the acronym "CI".
- README feature map re-verified against `--help --all`: 25
  rows, one per subcommand, one line each. (Table order differs
  from argparse order in two adjacent rows — editorial grouping,
  not drift; left alone.)
- Error-message probes: unknown model id (carries the
  `ghostslice prices` remedy on every command), nonexistent
  project path, `--budget -5`, cache on a missing project — all
  exit 2 naming the problem plainly.
- examples/github-action pins `@v1.0.0` as an illustrative tag;
  still a true example after 1.0.1 ships. Left.

## Item 5 — version and docs

`__init__.py` and `pyproject.toml` both 1.0.1 (doctor's version
check cross-pins them; the MCP server and completions read the
live values, so no other spot exists). CHANGELOG gained the
[1.0.1] "Polish" entry; ROADMAP_20.md gained the one-line
post-marathon note.

## Audit #1 — self-diagnostics re-run + regression probes

Environment: this sandbox, Python 3.12.3. All baseline probes
re-run on the finished work tree (table above). Regression
probes: full suite 792 passed / 1 pre-existing skip; GhostBus
export totals identical; dashboard page JS syntax-checked and
served by the live-server test; `ghostslice prices` resolves to
the packaged copy; doctor healthy.

### F1 [LOW] This round's own docs pushed README.md over L001
The known-warnings note and single-table updates grew README.md
to 20,198 estimated tokens, crossing the 20,000 L001 oversize
threshold — so standalone lint reads 5 warnings, not the 4 the
round's notes first claimed, and ci's lint line agrees (5).
The finding is true (the README is genuinely large; it documents
25 commands in one file). Improve #1: add the L001 line to the
README known-warnings note and correct the counts in README,
CHANGELOG, and ROADMAP_20.md to 7 -> 5 with the new warning
named. Not fixing by trimming: the note itself is the fix the
task specifies for explained warnings, and cutting reference
documentation to duck a threshold would be gaming the linter.

## Audit #2 — fresh eyes (done)

**Plugin-root reach, scratch probes (all correct):**
- Nested def named `slice_text` inside another function: NOT
  rooted (flags with its parent). Only top-level defs present
  the contract.
- A class method named `slice_text` inside a plugin module: NOT
  rooted (flags) — the root check matches the qualified name, so
  only the module-level contract functions root, never methods.
- `register` assigned, not defined (`register = _reg`): the
  loader accepts this shape, and the assignment reference keeps
  `_reg` reachable through the module root — no under-reach in
  effect, and a dead function beside it still flags.
- Per-file scoping: an unrelated module's `outline` still flags
  while a plugin module sits in the same project.
Improve #2: the three non-obvious probes (method-named-like-
contract, per-file scoping, assigned register) were converted
from scratch checks into shipped pins in
tests/test_v26_polish.py, so the precision properties are
regression-tested, not just audited once.

**Dedupe fallout:** fresh venv `pip install .`, run from a
clean cwd: `ghostslice 1.0.1`; `prices` resolves to the
installed package copy; `doctor` on this repo healthy with the
price table read from site-packages. The packaged copy ships
and loads exactly as before; no fallout.

**Dashboard equivalence:** every id the page JS queries exists
in the markup; every class the new createElement code assigns
(bar, path, tag, muted, tokens, accent, tm-path, tm-tok,
excluded) has the same CSS rule the old templates relied on;
the served page contains no `.innerHTML` (4 remaining mentions
are comments). No defects found.

**Version pin:** the full-suite run after the bump failed
exactly one test — test_v25_release.py's version pin, which
names the release it shipped with (1.0.0). That pin exists to
catch drift, and the bump is the change it legitimately tracks:
updated to 1.0.1 (name and assertion), the ONLY existing test
this round modifies. Final suite: 795 passed, 1 pre-existing
skip, 9 subtests passed.
