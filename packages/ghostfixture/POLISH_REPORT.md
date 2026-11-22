# GhostFixture v0.1 - Polish Report (Oct 14, 2026)

Sole-owner polish round at Ryan's "Polishing". House loop: audit
first, then improve only what is provably better, each change
demonstrated by the suite or a fixture. No version bump (still
0.1.0 in pyproject.toml), no push, no publish, no announcements,
no spend. Stdlib only; no new imports outside the standard
library (the Go support uses `re`-free hand tokenising plus the
already-used `pathlib`).

## Test counts

- Before: 32 passed, 0 failed (`python3 -m pytest tests -q`,
  parent-verified baseline, re-run at audit: 32 passed).
- After: **39 passed, 0 failed**, two consecutive full runs
  (20.29s and 10.35s). 7 tests added, 0 existing tests edited,
  weakened, or deleted.

## Audit summary

Read PLAN.md, IMPLEMENTATION_A.md, REPORT_B.md, and the full
core (bundle.py, build.py, closure.py, secrets.py, reports.py,
cli.py, mcp_server.py). The v0.1 core was in good shape: safety
rule order (bundle-exclusion bar, existence, root containment,
secret scan, size cap) is sound, check is honest, and the two
design decisions (binding bundle exclusions, originals not
sliced text) are correctly implemented. The documented limits
named two polish candidates, and both were taken because both
admit exact, fixture-provable implementations.

## Change 1: Go import closure (was: no closure for Go)

Seed candidate, taken because Go module mode makes resolution
exact rather than heuristic. An import path is resolved through
the `module` directive in the project's `go.mod`: a module-local
path names exactly one package directory (that is how the Go
toolchain resolves it), so the closure is every non-test `.go`
file in that directory.

- `src/ghostfixture/closure.py`: new Go section. A small
  tokeniser (comments dropped, interpreted and raw strings
  decoded, rune literals consumed so a quoted character cannot
  fake a string) feeds an import-spec parser implementing the
  Go spec grammar: single specs, aliased specs, and grouped
  `import ( ... )` blocks; every string inside an import
  declaration is an import path.
- Rules, all pinned by tests: stdlib and third-party paths are
  external references; a directory carrying its own `go.mod`
  is a nested module and imports of it by main-module path do
  NOT resolve (recorded as external/unresolved); `*_test.go`
  files are excluded; without a `go.mod` no local resolution
  is attempted at all.
- `language_of` now returns "go" for `.go`; a new
  `closure_note()` gives the manifest an accurate per-language
  note (Go: package level, non-test files, test files
  excluded). Python/JS notes keep their previous wording.
- Demonstration: new `tests/fixtures/go_project/` plus
  `tests/test_go_closure.py` (4 tests). Manual CLI run: the
  bundled `cmd/server/main.go` produced a 3-file fixture
  (main.go + internal/util/util.go via main.go +
  internal/shared/shared.go via util.go); fmt and the nested
  module were recorded as external references; the nested
  package, `util_test.go`, and the unreferenced stray package
  were all absent.
- README honest limits updated to describe Go resolution and
  its rules.

Honest edges kept as limits, not silently papered over: files
in an imported package directory are included regardless of
build tags (the file set of a package directory is exact;
which subset compiles under a given GOOS/tag set is a build
question, and Fixture builds nothing). Vendored dependencies
are external: module-local imports never resolve through
`vendor/`, and external imports are never resolved locally.

## Change 2: drift warning for bundle-vs-project state

Seed candidate ("a clearer drift warning in FIXTURE.md is a
safe win"). Before this round, if the project changed after
the bundle was exported, the fixture silently held newer
bytes; the only record was the bundle manifest hash.

Verified first that an exact comparison exists: GhostSlice's
manifest `sha256` is taken over the text the bundle stored,
which for mode `full` is the file itself at export time
(confirmed in the GhostSlice exporter and against the demo
bundle, where manifest hash == bundle copy == project
original). So for copied files at mode `full` with a recorded
sha256 and UTF-8 content, byte comparison is exact, and the
implementation claims nothing for any other case:

- `src/ghostfixture/build.py`: each copied bundle-referenced
  entry records `bundle_sha256`; comparable entries also
  record `matches_bundle_content`. Mismatches are collected
  into a top-level manifest `drift` list (path + both hashes),
  `totals.files_drifted`, and a `drift_check` record stating
  the comparability rule in words. The manifest `limits` text
  now points at the drift list.
- `src/ghostfixture/reports.py`: FIXTURE.md header states the
  drift check result either way ("all N comparable files
  match..." or "K of N differ..."); on any drift a
  `## Drift warning` section names each file with both hash
  prefixes and states plainly that the fixture holds the
  current project state, not the bundle's captured context.
  The wording is exact about what a mismatch proves: the
  copied bytes are not the bytes the bundle captured (project
  changed after export, or the bundle text was transformed).
- `src/ghostfixture/cli.py`: build prints a one-line drift
  warning with the count when drift exists.
- Non-`full` modes store sliced text, not the file: they are
  never compared and never claimed, pinned by a test where a
  signatures-mode file edited after export produces no drift
  entry and no `matches_bundle_content` key.
- Demonstration: `tests/test_drift.py` (3 tests: fresh bundle
  no drift with hashes recorded; post-export edit produces
  exactly one drift entry, the warning section, the CLI line,
  and a fixture that still passes `check`; signatures-mode
  edit produces no claim). Manual CLI run reproduced the
  warning output and the FIXTURE.md section verbatim.

Deliberately not done: drift is not checked by `check`
(a fixture is internally consistent even when drifted; drift
is a build-time fact about the bundle pairing, recorded in
the manifest the fixture carries).

## Deliberately left alone

- **Rust closure**: `mod` resolution is exact for plain
  declarations, but `#[path]` attributes and `crate::` paths
  through re-exports make a partial implementation easy to
  overclaim. One exact language (Go) beat two shaky ones.
- **Closure for other languages** (Java/C#/Ruby/etc.): import
  syntax is pattern-grade, not resolution-grade; they stay
  labelled "not computed in v0.1".
- **Reading files into memory one at a time** (documented
  limit): the size cap bounds totals; streaming copies would
  complicate the secret scan and hash bookkeeping for no
  verified need at fixture scale.
- **`build/lib/` and `src/ghostfixture.egg-info/`**: stale
  packaging byproducts sitting in the tree from the v0.1
  install check. Cosmetic only; removing them is housekeeping
  for a release pass, not a polish fix, and the suite does not
  depend on them either way.
- **Version, PLAN.md, pricing, gates**: untouched. Release
  decisions stay Ryan's.
- **No existing test was modified.** New coverage lives in
  `tests/test_go_closure.py`, `tests/test_drift.py`, and
  `tests/fixtures/go_project/`.

## Files changed

- `src/ghostfixture/closure.py` (Go closure, `closure_note`)
- `src/ghostfixture/build.py` (drift tracking, notes, limits text)
- `src/ghostfixture/reports.py` (drift line + warning section)
- `src/ghostfixture/cli.py` (drift warning line in build output)
- `README.md` (honest limits: Go resolution, drift naming)
- Added: `tests/test_go_closure.py`, `tests/test_drift.py`,
  `tests/fixtures/go_project/` (8 files), this report.
