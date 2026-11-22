# GhostEnv — merge of harden + polish + deepen (2026-10-18)

- Tool: ghostenv
- Merged tree: `~/workspace/.improve-2026-10-18/ghostenv/merged/`
  (fresh copy of pristine `~/workspace/ghostenv/`, caches excluded;
  pristine was never edited — its source files still carry their
  Oct 14 mtimes. Nothing pushed anywhere.)
- Lane order applied: harden, then polish, then deepen.
- Method: `diff -rq` per lane vs pristine, then per-file unified
  diffs; single-lane files copied verbatim, multi-lane files
  hand-merged and re-diffed against every lane to prove the merged
  file differs from each lane by exactly the other lanes' changes
  (plus the two wording corrections noted under Conflicts).

## Test counts (all `python3 -m pytest -q`, run by the merger)

| Tree | Result |
|---|---|
| pristine (baseline) | 41 passed |
| harden lane | 51 passed (41 + 10 new in tests/test_harden.py) |
| polish lane | 44 passed (41 + 3 new in tests/test_help_polish.py) |
| deepen lane | 51 passed (41 + 10 new in tests/test_deepen_ruby_java.py) |
| **merged** | **64 passed, 0 failed** (41 + 10 + 3 + 10) |

Per-file in merged: test_harden.py 10 passed,
test_help_polish.py 3 passed, test_deepen_ruby_java.py 10 passed.

**Polish requirement, explicitly:** the polish lane ended at 44
passing, above the pristine baseline of 41, because it added tests
for documented behavior. The merged tree passes **64**, which is
>= 44, includes all 3 polish help-text tests passing, and has
**zero new failures versus every lane** (merged passes the union
of all three lanes' suites: 64 = the arithmetic sum of every
lane's added tests over the shared baseline).

## File provenance

Copied verbatim from one lane (changed by that lane only):

- polish: `examples/README.md`, `src/ghostenv/__main__.py`,
  `src/ghostenv/doctor.py`, `src/ghostenv/examplegen.py`,
  `src/ghostenv/reports.py`, `tests/test_help_polish.py` (new)
- harden: `tests/test_harden.py` (new)
- deepen: `tests/test_deepen_ruby_java.py` (new)

Hand-merged (changed by more than one lane):

- `src/ghostenv/scanner.py` — harden + polish + deepen (see
  Conflict 1)
- `src/ghostenv/cli.py` — harden + polish (see Conflict 2)
- `src/ghostenv/envparse.py` — harden + polish (see Conflict 3)
- `README.md` — polish + deepen (see Conflict 4)

Everything else is pristine, untouched. No lane's IMPROVE.md was
carried into the merged tree.

## Conflicts and resolutions

### 1. scanner.py — harden x deepen x polish (the substantive one)

Harden restructured the scanner: per-language pattern filtering
(`_EXT_LANG` / `_KIND_LANG`), `_DYNAMIC_RES` changed from a plain
list of regexes to `(regex, lang)` tuples, stateful `/* ... */`
block-comment stripping, and symlink containment in `_iter_files`.
Deepen was written against the pristine structure: it appends
plain (untagged) dynamic regexes, adds Ruby/Java patterns, extends
`CODE_EXTS` and `_DEFAULT_MARKERS`, and adds `.java`/`.kt`/`.kts`
to the `//`-comment set. Polish adds only the `_iter_files`
docstring. Resolution, keeping BOTH lanes' behavior:

- Base: harden's file (no harden fix altered or dropped).
- Deepen's static patterns, `CODE_EXTS` additions, module-docstring
  paragraph, and `_DEFAULT_MARKERS` additions (`":"`, `"{"`,
  `"?:"`) inserted verbatim.
- Deepen's four dynamic regexes re-expressed in harden's tuple
  form, tagged `"ruby"` (ENV subscript / ENV.fetch / interpolated
  name) and `"java"` (System.getenv with a variable). The regexes
  themselves are byte-identical to deepen's.
- `_EXT_LANG` extended: `.rb`/`.rake` -> `"ruby"`,
  `.java`/`.kt`/`.kts` -> `"java"`; `_KIND_LANG` extended with
  `"ruby"` and `"java"`, so deepen's kinds (`ruby-*`, `java-*`)
  pass harden's filter in exactly their own files.
- `.java`/`.kt`/`.kts` added to the `slash_comments` set, where
  harden's richer handling now applies: `//` full-line comments
  skipped (deepen's requirement) and `/* ... */` interiors also
  stripped (harden's rule, extended to the new languages).
- Polish's `_iter_files` docstring kept, on top of harden's
  symlink-contained body.

Behavioral note (a refinement, not a loss): deepen's IMPROVE.md
records that its patterns "run as a union over all scanned files",
so e.g. `ENV["X"]` inside a Python file would count as a Ruby
read. Under the merge, harden's per-language filtering wins:
Ruby/Java patterns fire only in Ruby/Java files. That is strictly
narrower, matches harden's stated design (PLAN lists patterns per
language), and all 10 deepen tests still pass because they plant
each language in its own file type.

### 2. cli.py — harden x polish (behavior vs its own description)

Different regions, one real contradiction: polish's `cmd_example`
docstring said the command "refuses to overwrite an existing
example file without --force **or an explicit -o path**", but
harden deliberately *removed* that `-o` exemption (it was bug #1:
`-o` silently clobbered any existing file, including the real
`.env`). Harden's behavior wins, unconditionally. Resolution:

- Harden's `_report_or_error` try/except (OSError/ValueError ->
  exit 2) and harden's `cmd_example` guards (`.env` refusal even
  with `--force`, resolved-path/symlink check, overwrite refusal
  for ANY existing target without `--force`) applied verbatim.
- Polish's help text, epilog, metavars, and docstrings all kept.
- Two wording corrections so the surviving polish text describes
  the hardened behavior instead of the old one:
  (a) `cmd_example` docstring now reads "refuses to overwrite any
  existing file without --force, and refuses a real .env target
  even with --force (exit 2)";
  (b) `--force` help changed from "an existing **default** target
  is refused" to "an existing target is refused".
  Polish's `_report_or_error` docstring was also widened by one
  clause ("or the scan itself fails") to cover harden's new path.
- Polish's help tests only pin substrings (exit codes, names-only,
  subcommand names, "project directory", `--json`, `--stdout`,
  `--force`); all still present, all 3 pass.

### 3. envparse.py — harden x polish (no true conflict)

Harden added `_bomless()` and applied it in `parse_env_text`,
`malformed_lines`, and `load_config`. Polish added docstrings
only, in different regions. Clean union: harden's file plus
polish's five docstrings (`names`, `duplicates`,
`is_valid_name`, `parse_env_file`, `find_example_file`). Verified
by diffing merged against each lane: vs harden it differs only by
the docstrings; vs polish only by the BOM changes.

### 4. README.md — polish x deepen (no true conflict)

Polish rewrote the Quickstart area and added the "Which command",
`.ghostenv.json`, and exit-code sections; deepen edited the intro
name-source list and added one Limits bullet. Different regions;
clean union (polish base + deepen's two hunks, verbatim). Verified
by diffing merged against each lane.

## Cross-lane sanity check (beyond the suites)

No single lane's suite exercises harden-filtering x deepen-patterns
together, so the merger ran a direct probe against the merged
scanner on a synthetic project. All five assertions passed:

- Ruby read in a `.rb` file fires; Java read in a `.java` file
  fires (deepen intact).
- `ENV["..."]` text inside a `.py` file does NOT fire;
  `ENV[...]` text inside a `.java` file does NOT fire (harden
  cross-language filtering intact over the new patterns).
- A `System.getenv(...)` on the interior line of a `/* ... */`
  block comment in a `.java` file does NOT fire (harden's block
  comment stripping now covers the deepen-added languages).

## Anything suspicious

- Nothing unresolved; no harden fix was dropped, weakened, or
  left in conflict. No conflict required stopping the merge.
- Polish's `examples/README.md` generated-example snippet was
  byte-checked during the merge: the `DATABASE_URL=` and
  `DEMO_API_KEY=` lines end exactly at the `=` (13 chars each,
  empty values), as polish's IMPROVE.md claims — names only.
- Deepen's "patterns run as a union" caveat (its IMPROVE.md
  Risks section) is superseded by the merge as described in
  Conflict 1; that is the one place where merged behavior
  intentionally differs from a lane's standalone behavior,
  in the stricter direction.
- Test caches (`__pycache__`, `.pytest_cache`) created by the
  verification runs were removed from the merged tree afterward;
  the counts above are from the runs before that cleanup.
