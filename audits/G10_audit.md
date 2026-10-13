# G10 Audit — `ghostslice init` wizard (v0.15.0)

Goal: analyse a project (scan / graph / entries / detect / lint) and
generate a tuned .ghostslice.json where every section is justified
by printed evidence. Baseline 427 tests; build brought the suite to
455 (28 new in tests/test_v15_init.py).

## Audit #1 (after build)

### F1 [MEDIUM] Python `__main__` guard detection is a raw regex over the whole file
entries.py searches the full text for `if __name__ == "__main__"`,
so a comment, docstring, or string literal mentioning the guard
earns the +35 signal, and a guard nested anywhere counts. The rest
of this codebase parses Python with the real `ast` (slicer, graph);
init's flagship signal should meet the house standard. Fix: parse
with ast and accept only a module-level `if` whose test compares
`__name__` to `"__main__"`; fall back to the regex only when the
file does not parse (a broken file can still be an entry point).

### F2 [MEDIUM] A config dir nested under an all-generated dir can resurrect excluded files
analyze_project excludes config candidates under *ignored* dirs but
not under *generated* dirs. If `gen/` is all-generated (modes:
`gen/** -> exclude`) and `gen/sub/` is config-heavy, init also emits
`gen/sub/** -> structure`. profile.mode_for is last-match-wins over
dict order, so the structure glob can win for those files — the
profile would claim "generated excluded" while exports slice them
as structure. Fix: config candidates under a generated dir (or
under a generated file glob's directory) are dropped.

### F3 [LOW] The interactive budget prompt can override an explicit --budget
run_init passes the --budget value into the analysis as the
proposal, and _interactive_trim then offers to change it. A flag
the user typed explicitly should pre-answer its section (the spec's
rule for --budget/--model). Fix: mark the budget locked when it
came from --budget; the prompt is skipped.

### F4 [LOW] A generated file whose name contains fnmatch metacharacters gets a mode glob that does not match it
Per-file generated suggestions use the file's path as the glob. A
file named e.g. `gen[1].py` produces a pattern fnmatch reads as a
character class, so Profile.mode_for(path) would NOT return
"exclude": the written profile claims an exclusion the exporter
never applies — exactly the summary-vs-effect mismatch this goal
must not ship. Fix: verify every suggested glob against its
intended targets through Profile.mode_for before writing; drop
non-matching suggestions and say so in the justification lines.

### F5 [LOW] entries reads every code file in full to find a first line
_head_and_text reads whole files for all shebang-eligible
languages, though only Python needs the text (for the guard). On a
large tree init pays a full extra read per file. Fix: read the
first line only, plus the full text for Python files.

### F6 [LOW] Dead code in the wins computation
analyze_project builds an `applied` set it never uses. Remove.

### Categories audited with no findings
- Dry-run writes nothing: pinned by a byte-for-byte filesystem
  snapshot test (file set + contents), not just "profile absent".
- Refusal: existing profile blocks without --force even when the
  existing file is corrupt (summary falls back to the parse error);
  the file's bytes are untouched (asserted).
- Round-trip: the written profile is loaded through load_profile
  inside run_init and its sections compared field by field; the
  round-trip export test shows vendor files vanish (profile ignore
  is applied by the scan matcher) and the generated dir resolves to
  exclude in the manifest.
- Budget math: round_budget pinned at three magnitudes; the basis
  test compares against the analysis' own sliced total via the
  documented formula rather than a magic number; --budget is NOT
  rounded (asserted).
- Entry false positives: test files are excluded even with a
  __main__ guard (pinned), vendored files even with an entry name
  (pinned), banner-only vendored files do NOT trigger an ignore
  glob (path evidence required — vendored_path counter).
- Manifest parsing safety: npm signals are filtered through the
  scanned path set, so package.json files under node_modules
  (reached by the manifest globs, which do not respect ignores)
  cannot nominate unscanned files; pyproject script targets are
  existence-checked the same way.
- Interactive defaults equal --yes: pinned both ways (accept-all
  answers vs the --yes dry-run payload; trimming answers change
  exactly the trimmed section).
- Shebang-only nominations are weak (GhostBus's
  deploy/docker/vps-setup.sh makes the top 5 at score 35): the
  signals are printed verbatim, the ranking is honest, and the cap
  note discloses the 7 further candidates. Accepted, deliberate —
  a setup script IS a runnable entry of a sort, and the user
  confirms interactively or edits the file.

## Improve #1 (fixes applied)
- F1: entries._main_guard now parses Python with ast and accepts
  only a module-level `if __name__ == "__main__":` (either quote
  style, == only); the regex remains as a fallback for files that
  fail to parse. New tests: a guard mentioned in a comment/string
  does not nominate; a guard nested in a function does not
  nominate; an unparseable file with a textual guard still does.
- F2: config-dir candidates under a generated directory are
  dropped. New test: generated parent + config child yields only
  the exclude glob.
- F3: analysis records budget_locked; the interactive trim skips
  the budget prompt when --budget supplied it. New test.
- F4: suggested mode globs are verified through Profile.mode_for
  (file globs against their file, dir globs against a probe path
  inside the dir); failures are dropped and a justification line
  records the drop. New test with a `gen[1].py` generated file.
- F5: entries reads the first line via readline; full text only
  for Python files.
- F6: dead `applied` set removed.

## Audit #2 (of the build + Improve #1 fixes)

### G1 [MEDIUM] A `.ghostslice.json` that is a directory (or an unwritable target) crashes init
The refusal check tests `target.is_file()`, so a *directory* named
.ghostslice.json slips past it; with --force (or no existing file
check hit) the run does the full analysis and then dies in
write_text with an uncaught IsADirectoryError traceback. The same
applies to any OSError on write (read-only directory). init is a
first-run experience; it must fail with a message and exit 2, never
a traceback. Fix: an upfront exists-but-not-a-file guard, and the
write wrapped in OSError -> message + exit 2.

### G2 [REVIEWED, SOUND] F1's ast guard scope
_is_main_compare accepts a bare `__name__ == "__main__"` comparison
only: a BoolOp-wrapped guard (`if __name__ == "__main__" and DEBUG:`)
is missed. That is a false NEGATIVE on an unusual shape — the safe
direction for a nomination signal — and the name/shebang signals
usually still catch such a file. Accepted, documented here.

### G3 [REVIEWED, SOUND] Interactive count above the cap
Typing a count larger than ENTRY_CAP at the entry-points prompt
includes that many candidates. The cap is the *default* selection,
not a hard limit against an explicit user number; the prompt shows
what is being accepted. Accepted, deliberate.

### G4 [REVIEWED, SOUND] Wins after an interactive drop
Wins are computed from the analysis before trimming; if the user
drops the file-rules section interactively, the printed wins list
still names those savings — as *available* wins under a header that
says exactly that ("guidance only — init applied nothing beyond
the profile above"). True in both readings. No change.

### G5 [REVIEWED, NO FINDINGS] Re-checks after Improve #1
- GhostBus dry-run unchanged in substance after the entries
  rework (it is a JS project; its three bin commands still top the
  ranking with identical scores 135/95/95).
- Determinism: candidates sort by (-score, path); directory
  suggestions are outermost-first by (depth, name); mode entries
  by (-tokens, glob). Two runs over the same fixture produce
  byte-identical profiles (the write test's key-order assertion
  plus the analysis' sorted structures).
- F4's probe uses a synthetic `__probe__` path — mode_for is pure
  pattern matching, so no filesystem existence is implied.
- The full suite after Improve #1: 461 passed (455 + 6 new), and
  `ghostslice secrets .` still exits 0.

## Improve #2 (fixes applied)

- G1: run_init refuses up front when the target path exists but is
  not a file (exit 2, message), and wraps the profile write in
  OSError -> "init: could not write ..." + exit 2. New test: a
  directory named .ghostslice.json is refused and left untouched.

Final state: see the ROADMAP_20.md G10 progress entry for the
closing test count.
