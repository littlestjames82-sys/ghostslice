# G08 Audit — Monorepo / workspace support (v0.13.0)

Goal: workspace detection (npm/pnpm/Cargo/go.work/uv declared
sources + manifest fallback), scanner `package` assignment, and
per-package subtotals on scan (text + JSON), the export manifest,
/api/scan and the HTML report. Baseline 370 tests; build brought
the suite to 391 (21 new in tests/test_v13_monorepo.py).

## Audit #1 (after build)

### F1 [MEDIUM] Detection warnings and missing members are invisible on every surface
detect_workspaces carefully records `missing` (declared members
not on disk) and `warnings` (root-escaping members clamped,
unparseable package.json) — and nothing displays either. The scan
JSON carries only the packages summary; the scan text prints the
summary only. The spec says missing members are "reported": a
report nobody can see is not a report. Fix: ScanResult.to_dict
gains a "workspace" subset {declared, is_monorepo, missing,
warnings} when detection ran, and the scan text prints
missing/warning lines whenever the lists are non-empty (independent
of whether a Packages section printed).

### F2 [MEDIUM] pnpm list items at column 0 end the packages list early
YAML allows a block sequence under a mapping key at the SAME
indentation as the key (`packages:` then `- 'libs/*'` at column
0). _pnpm_packages requires `^\s+-` (at least one space) for items,
so a column-0 item fails the item match, hits the "next top-level
key" break, and every member is silently lost. Fix: try the item
match with `^\s*-` first; only a non-item, non-empty, column-0
line ends the list. Pin with a fixture using column-0 items
followed by another top-level section (whose indented items must
NOT be collected).

### F3 [LOW] Cargo `exclude` also removes explicitly listed members
Cargo semantics: exclude prevents inclusion only for members
pulled in by globs; an explicitly listed member stays even if it
also appears in exclude. The build subtracts the exclude set from
every expanded dir of the Cargo set, literal members included.
Fix: within the Cargo set, dirs produced by any literal (non-glob)
member pattern are immune to exclusion. npm/pnpm "!" negations
keep subtract-all behaviour (npm processes patterns in order and
a later negation removes earlier literal matches too — the sets
here lose order, documented as the simplification).

### F4 [LOW] Root package evidence ignores go.work / pnpm-workspace.yaml
_root_package only recognises MANIFEST_NAMES, so the root of a
pure Go workspace (go.work, no root go.mod — a normal layout)
reports source "project root" with manifest None, as if there
were no evidence at all. Fix: after the manifest names, treat
go.work and pnpm-workspace.yaml as root evidence too (they are
workspace-root files; they are NOT added to MANIFEST_NAMES, so
the fallback still cannot mistake a stray go.work in a subdir
for a package manifest).

### F5 [LOW] The `**` simplification is documented but untested
`**` behaving as a single-segment `*` is a spec'd simplification;
no test pins it, so a future "improvement" to real recursive
globbing would silently change assignment semantics. Pin it:
pattern "libs/**" packages libs/foo (with manifest) but a file
two levels down still belongs to libs/foo by prefix, and
libs/foo/bar (a dir with its own manifest) is NOT its own
package (outermost/one-level expansion only).

### Categories audited with no findings
- Prefix-sibling confusion: package_for and the outermost-wins
  pass both compare with a trailing "/" boundary, so package
  "packages/a" never claims "packages/abc/x" (construction-safe;
  the nested test exercises the boundary logic).
- Symlinked package dirs: the scanner's os.walk does not follow
  directory symlinks, so a symlinked member is never descended
  and cannot double-count; pinned by the symlink test (paths
  unique, nothing under packages/link).
- Old-bundle validator: validate_bundle reads only files/totals;
  the additive "package"/"packages" keys are ignored, and the
  stripped-manifest round-trip test proves pre-v0.13 bundles
  still validate.
- Detection runs once per scan (in scan(), before the walk),
  not per directory; glob expansion only touches member dirs.
  The added cost per scan is a handful of root reads — noted
  for G15 (caching) rather than fixed here.
- TOML-lite limits (accepted, documented in the module as a
  "lite" reader): quoted section segments ([tool."uv".workspace]),
  a header-shaped line inside a multi-line string, and
  [[array-of-tables]] bodies are not modelled; the shapes the
  fixtures pin (comments inside arrays, # inside quoted names,
  single quotes, section bleed) all parse correctly.
- A literal directory name containing "[" would be read as a
  glob segment by _expand_pattern (fnmatch semantics, same as
  the ecosystems' own globbers). Accepted.
- Share rounding: per-package shares are rounded to 2dp and can
  sum to 99.99/100.01; counts are labelled estimates everywhere
  the summary appears.
- graph/lint: untouched by design this goal; both consume scan
  entries whose new field defaults to "" for hand-built results,
  and the full suite (which covers both) passes unchanged.
- summarize_packages on hand-built ScanResults (workspaces=None)
  derives kinds as root/detected — the manifest and JSON paths
  always carry real detection, so the fallback labelling only
  ever appears in synthetic test data.

## Improve #1 (fixes applied, suite 391 -> 396)

- F1: ScanResult.to_dict gains a "workspace" subset {declared,
  is_monorepo, missing, warnings} whenever detection ran; the
  scan text prints "Workspace members declared but missing on
  disk" and "Workspace warnings" blocks whenever the lists are
  non-empty, independent of the Packages section. Pinned by a
  JSON + text test.
- F2: _pnpm_packages tries the item match (now `^\s*-`, any
  indentation) before the top-level-key break. Pinned by a
  column-0-items fixture whose following section's indented
  items are not collected.
- F3: declared_sets carry an exclude-globs-only flag (Cargo
  only); dirs produced by literal member patterns of the Cargo
  set are computed as an immune set and exclusion cannot remove
  them. Pinned: a crate that is glob-matched, excluded AND
  literally listed stays a package.
- F4: _root_package treats go.work / pnpm-workspace.yaml as root
  evidence after MANIFEST_NAMES (deliberately not added to
  MANIFEST_NAMES, so the fallback cannot promote a subdirectory
  for carrying one). Pinned by a go.work-only root fixture.
- F5: `**` one-segment behaviour pinned by a dedicated test
  (libs/** packages libs/foo; libs/foo/bar is not its own
  package and its files belong to libs/foo).

## Audit #2 (of the build + Improve #1 fixes)

### G1 [LOW] A column-0 comment inside the pnpm packages list ends it early
The F2 reorder still breaks on a non-item, non-empty, column-0
line — and a `# comment` at column 0 between two list items is
exactly that shape, even though YAML comments never terminate a
sequence. Blank lines are safe (strip() is empty), comments are
not. Fix: skip blank and comment lines before the break test.
Pin: a list with an intervening column-0 comment still collects
the items after it, and the following section still terminates.

### G2 [LOW] pnpm flow-style `packages: [...]` on the key line is not parsed
`packages: ['libs/*']` is legal YAML; the key regex requires
end-of-line after the colon, so in_list never engages and the
members are lost (detection then falls back to "detected",
mislabeling declared evidence). pnpm's own files use block
style, but the fix is small: when the key line carries an
inline [...] list, extract its quoted strings via the existing
_scan_strings and do not enter block mode. Pin with a fixture.

### G3 [REVIEWED, ACCEPTED] TOML-lite remaining limits
Array opening on the line after `members =` (legal TOML,
never produced by cargo/rustfmt conventions) and quoted
section segments ([tool."uv".workspace]) stay unsupported;
both were already noted in Audit #1. The shapes real
Cargo/pyproject files use are pinned by the fixtures.

### G4 [REVIEWED, SOUND] Fallback stays all-or-nothing
When any declared source yields patterns, directories that no
source names belong to the root package even if they carry
manifests (they are not promoted to "detected"). That is the
spec's fallback rule ("if none of the above match") and the
npm-negation fixture pins the same shape (packages/skip files
land in the root package). The Packages summary therefore never
mixes evidence kinds from two strategies in one scan.

### G5 [REVIEWED, SOUND] Improve #1 interactions
- Per-set scope: `removed` and `immune` are rebuilt per
  declared set, so Cargo's exclusion cannot remove an npm
  member and vice versa; a dir found by an earlier source is
  skipped by later sets before exclusion is even consulted.
- The to_dict "workspace" subset is plain JSON types and the
  key is absent for single-file scans and hand-built results,
  keeping the payload additive-only; MCP /api consumers take
  the extra key in stride (full suite green).
- F4's root evidence order (manifests before workspace files)
  means a polyglot root with both package.json and go.work
  reports package.json — the root package's own manifest is
  the stronger evidence for the root bucket either way.

## Improve #2 (fixes applied, suite 396 -> 398)

- G1: blank and comment lines are skipped before the item /
  break logic in _pnpm_packages, so a column-0 comment between
  items no longer ends the list; the following top-level key
  still terminates it. Pinned by a dedicated fixture.
- G2: a single-line flow list on the `packages:` line
  (`packages: ['libs/*', "apps/*"]`) is parsed via
  _scan_strings; multi-line flow lists remain a documented
  lite limit (block style is what pnpm writes). Pinned.
- G3/G4/G5 were reviewed-sound and needed no changes.

Final state: 398 tests passed (370 baseline + 28 new), version
0.13.0, `ghostslice secrets .` exits 0, GhostBus demo unchanged
(129,555 -> 45,770 estimated tokens, all 42 files in the root
package). Committed locally; push/release is the parent's step.
