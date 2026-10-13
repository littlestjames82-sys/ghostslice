# G01 Audit — Watch mode (v0.6.0)

Goal: `ghostslice watch` polling watcher with debounced rescan and
optional auto re-export. Baseline 149 tests; build brought the suite
to 167 (18 new in tests/test_v06_watch.py).

## Audit #1 (after build)

### F1 [CRITICAL, fixed during build verification] Bundle==project-root guard never fired
`_bundle_rel` returned `"."` (Path.as_posix of the empty relative
path) for out == root, but the guard compared against `""`. The
rejection test caught it live: watch exported the bundle into the
project root, every export ingested the previous bundle
(files/files/... nesting, PROMPT.md doubling), the disk filled, and
the test run died on ENOSPC after 151s. Fixed by returning `""` when
`rel.parts` is empty; the same test then passes in milliseconds and
the whole watch file runs in 2.4s. Lesson recorded: any guard that
compares path strings must be tested against the actual value Path
produces.

### F2 [MEDIUM] A failed export crashes the watcher
`do_export` let build_bundle/validate exceptions (OSError on an
unwritable bundle dir, ValueError on a bad mode, disk full)
propagate, killing the watch session with a traceback and no
summary. A watcher should report the failed export and keep
watching; the delta reporting is still useful and the next settled
change retries the export.

### F3 [MEDIUM] Watch exports with a custom in-project bundle name ingest the previous bundle
The watcher's own snapshot/reporting excludes the bundle dir, but
build_bundle re-scans the project with only the user's profile, so
with e.g. `-o proj/bundle-out` the bundle contents include the
previous bundle's files (one nesting level per settled export), and
manifest totals disagree with the watcher's reported totals.
One-shot `export` has the same behaviour and it is warned about, but
watch multiplies it on every change. Fix inside watch only: pass
build_bundle an augmented profile whose ignore list adds
`<bundle_rel>/**`, leaving one-shot export untouched.

### F4 [LOW] In-project bundle warning over-fires for nested ignored names
The warning tested only the first path segment against
DEFAULT_IGNORE_DIRS, so `-o proj/sub/.claude_context` (scanner-
ignored at any depth) would warn unnecessarily. Test all segments.

### F5 [LOW] CLI accepts NaN interval/debounce
`--interval nan` passes the `<= 0` check (NaN comparisons are
False) and then time.sleep raises. Validate with math.isfinite.

### F6 [TEST QUALITY] Debounce burst test depended on wall-clock timing
It used a real clock with real 0.02s sleeps and a 0.3s window:
sound margins, but timing-shaped. The watcher already accepts an
injected clock, so drive the burst test with a fake clock advanced
by the fake sleep: fully deterministic, zero real sleeping.

### F7 [TEST QUALITY] No test covers the secrets warning for changed files
The settle path re-scans added/changed files for secrets; nothing
exercised it. Add a test that adds a file containing a fake token
assembled from string fragments at runtime (so the repo's own
secret guard stays clean) and asserts the redacted warning.

### F8 [DOCS] README overstates the ledger guarantee
README said each settled export "appends exactly one ledger
record"; build_bundle actually appends at most one (it swallows
OSError). Align wording with the module docstring ("at most one").

### Categories audited with no findings
- Symlink loops: the scanner uses os.walk (followlinks=False by
  default); a test with a directory symlink pointing at the project
  root proves no descent and no hang.
- Empty project / project deleted mid-watch / file deleted mid-scan:
  covered by tests; scan failures are caught per-poll and the last
  snapshot is kept (a poll outage does not clear a pending change).
- Race scan-vs-write inside build_bundle: the bundle can capture a
  half-written file, exactly as one-shot export can; validate_bundle
  re-reads what was written, so the bundle stays self-consistent.
  Accepted, inherent to the tool's design.
- Pure `touch` (mtime-only) changes report as changed files with a
  zero token delta: standard mtime-watcher semantics. Dropping them
  would require ignoring mtime when size+tokens match, which could
  hide a real edit whose estimate collides. Accepted, deliberate.
- Dashboard tie-in: intentionally skipped (spec: optional only if
  trivial); server.py untouched.
- `--once` ignores debounce by design (single compare poll);
  documented in the module docstring and README.

## Improve #1 (fixes applied, suite 167 -> 170)
- F1: already fixed during build (see above); regression test is
  test_cli_watch_rejects_bad_arguments (-o == project root -> exit 2,
  and the whole watch test file now runs in ~2.4s instead of 151s).
- F2: do_export now catches OSError/ValueError from build_bundle,
  prints "[watch] export failed (...); continuing to watch", and only
  counts successful exports; validate_bundle errors are reported in
  the bundle line instead of raising. New test: bundle path under a
  regular file -> exports 0, the change event still reports, session
  exits cleanly.
- F3: when the bundle dir is inside the project, watch passes
  build_bundle a copy of the profile (dataclasses.replace) whose
  ignore list adds "<bundle_rel>/**" (and a synthetic path marker
  when the user has no profile, since the exporter only applies a
  profile matcher when it has a path). One-shot export untouched.
  New test: three watch exports with a custom in-project bundle name
  -> manifest contains no bundle-out/* paths and no nested
  files/bundle-out directory exists.
- F4: warning now fires only when NO segment of the bundle rel path
  is a scanner-ignored directory name.
- F5: CLI validates --interval/--debounce with math.isfinite
  ("nan" interval and "-1" debounce now exit 2; tests added).
- F6: burst test rewritten on an injected FakeClock advanced by the
  fake sleep (interval 1.0 fake s, debounce 2.5 fake s, writes at
  t=1,2,3, settle at t=6): fully deterministic, no real sleeping.
- F7: new test adds a file mid-watch containing a GitHub-token shape
  assembled from string fragments; asserts the stderr warning names
  the file and the full token never appears in the output.
- F8: README now says "at most one ledger record" and notes that
  watch-written bundles exclude the in-project bundle directory.

## Audit #2 (of the build + Improve #1 fixes)

### G1 [LOW] Watching a nonexistent path exits 0
The soft per-poll failure handling also swallows the INITIAL scan:
`ghostslice watch /typo` prints "scan failed" / "initial scan
failed; nothing to watch" and the CLI returns 0. One-shot commands
fail loudly on a bad path, and a typo'd watch should too. Mid-watch
deletion must stay soft (it does; the soft path is per-poll), but a
root that does not exist at startup is a usage error. Fix: upfront
existence check in run_watch raises FileNotFoundError; the CLI maps
it to exit 2. Add CLI + API tests.

### G2 [REVIEWED, SOUND] F3's ignore pattern vs glob-special directory names
match_glob's "dir/**" branch compares the prefix literally before
any fnmatch work, so a bundle dir named e.g. "my[proj]" is excluded
by literal prefix comparison; the augmented "<bundle_rel>/**"
pattern therefore works for bracket-named dirs too. No change.

### G3 [REVIEWED, SOUND] F2 catch scope
build_bundle's realistic failures are OSError (writes, mkdir) and
ValueError (unknown mode/profile); slicer parse failures are
handled inside the slicers (they fall back instead of raising), so
parity with one-shot export holds. KeyboardInterrupt during an
export still propagates to the session summary handler, as it
should. No widening to blanket Exception: that would hide real bugs
from every other caller-visible surface. No change.

### G4 [PINNED BEHAVIOUR] Revert-to-original still settles as a change
Because the snapshot keys on (mtime_ns, size, tokens), editing a
file and reverting its content before the debounce elapses still
produces one settled "~ file" event with a +0 token delta (mtime
moved). This is the Audit #1 accepted mtime semantics; pin it with
a deterministic fake-clock test so the behaviour is a documented
choice, not an accident.

### G5 [REVIEWED, NO FINDINGS] Areas re-checked after the fixes
- exports counter: increments only after a successful build_bundle;
  a bundle that builds but fails validation still counts (it WAS
  written) and its line says VALIDATION FAILED. Correct.
- Pending-change state survives a failed poll and a failed export:
  settle advances the snapshot exactly once per settled snapshot,
  so a failed export does not re-report the same change on the next
  poll, and the next real change retries the export. Correct.
- --once + --export with a change on the compare poll: startup
  export + one settled export = 2, matching the ledger count.
- Profile augmentation preserves modes/preset/entry_points
  (dataclasses.replace copies all other fields); fit still receives
  the entry points. Covered indirectly by the fit passthrough test
  plus the existing v0.5 fit tests against build_bundle.
- No other callers of run_watch exist; cli.py's `math` import does
  not collide with anything in that module.

## Improve #2 (fixes applied, suite 170 -> 173)

- G1: upfront root existence check in run_watch raises
  FileNotFoundError; the CLI maps it to exit 2 with "watch: no such
  project: <path>". Tests: API raises, CLI exits 2, and the mid-watch
  deletion test still passes (soft per-poll handling unchanged).
- G4: fake-clock test pins the revert semantics: edit + revert
  inside the debounce window settles as exactly one "~" event with
  a (+0) token delta.
- CHANGELOG [0.6.0] notes the nonexistent-path exit 2 and the
  mid-watch deletion behaviour.

Final state: 173 tests passed (149 baseline + 24 new), version
0.6.0, `ghostslice secrets .` exits 0, real-terminal smoke of
`watch --once` and `watch --export --once` on this repo passes and
the produced bundle validates. Committed locally; push/release is
the parent's step.
