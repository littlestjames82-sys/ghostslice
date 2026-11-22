# GhostPacks v0.1 - Implementation A (core builder)

Built Oct 14, 2026 from ~/workspace/ghostpacks/PLAN.md. Agent A scope:
src/**, pyproject.toml, packs/**, this file. tests/** and README.md
untouched (Agent B). Zero-dependency Python stdlib only. No network or
download code anywhere (source scan in the smoke suite asserted no
urllib / http.client / requests / socket / urlopen / subprocess tokens
under src/). No push, publish, or spend.

## What was built

Package `ghostpacks` 0.1.0 under src/ghostpacks/:

- pack.py - the pack format and lint.
  - pack.json manifest (id, version, kind, stack_tags, ghostslice
    version range, author, date, reference_projects, bench_report,
    score) + profile.json fragment validated against the live
    GhostSlice profile schema read from ghostslice/profile.py and
    slicer.py: top-level keys (ignore, modes, model, budget_tokens,
    entry_points, preset, auto_shrink, redact, plugins, lint,
    duplicates, ci), mode names (full, signatures, interfaces,
    structure, strip-tests, exclude, headings), presets, lint rule
    ids L001-L010 with their per-rule options, and the duplicates/ci
    floor sections. Unknown keys fail loudly, by name.
  - kind enforcement: kind must be exactly "context"; a policy or
    permission pack fails lint with the reason stated.
  - Data-only rule: any executable/script suffix, any non-data suffix
    (only .json/.md/.txt allowed), any executable permission bit, or
    any shebang anywhere in the pack folder fails lint.
  - No absolute paths anywhere in manifest or fragment.
  - Score honesty: claiming a score without a Bench report file in
    the pack fails lint. No score means score_status "unscored",
    printed in list, show, doctor, and lockfile entries.
  - load_pack, lint_pack, find_packs, default_library_dirs
    (--library, $GHOSTPACKS_LIBRARY, ~/.ghostpacks, bundled packs/),
    resolve_pack by folder or id.

- manager.py - list/show support data plus merge/remove.
  - Merge semantics: list sections union, modes union, nested
    sections merge per key; a key set differently by both sides is a
    named conflict, aborts without --force (pack wins with --force).
  - Every merge prints a full unified diff of .ghostslice.json before
    any write and requires an explicit yes (interactive prompt or
    --yes). Declined or conflicted merges write nothing (verified).
  - Lockfile .ghostslice-packs.json: pack id, version, kind, source,
    date merged, profile sha256 before/after, backup path, score
    status. Backup of the pre-merge profile is kept under
    .ghostslice-packs-backup/ in the project.
  - remove restores the backup only when the current profile hash
    equals the recorded after-merge hash and the pack is the latest
    merge; otherwise it refuses with the exact reason (hash values,
    later packs, backup path) unless --force. Restoring a no-prior-
    profile merge deletes the profile the merge created.

- doctor.py - `ghostpacks doctor` for a pack (lint, GhostSlice range
  check with the range printed, pack-date freshness >365 days, Bench
  staleness >180 days, plugin references checked for presence only,
  never loaded) and for a project (profile parses, lockfile parses,
  recorded pack sources still lint, post-merge drift warning).

- authoring.py - `ghostpacks init-pack <project> -o <out>`: turns the
  project's .ghostslice.json into a draft pack (manifest skeleton
  stamped unscored, profile fragment, NOTES.md). Absolute paths are
  stripped from list sections and mode patterns and listed in the
  output; project profiles are loaded non-strictly so stripping, not
  rejection, is what happens to a real user profile.

- cli.py - subcommands: lint, list, show, merge (either argument
  order), remove, doctor, init-pack. Exit codes: 0 ok, 1 lint fail /
  merge conflict / declined, 2 usage or config errors. --version.

pyproject.toml: setuptools, requires-python >=3.10, no dependencies,
console script `ghostpacks`.

## Starter packs (packs/, all unscored and labelled that way)

- python-library: src signatures, tests strip-tests, docs/notebooks
  headings, interpreter/tooling caches ignored, L009 raised to error,
  suggested budget 60000.
- nextjs-typescript: app/src/components signatures, tests strip-tests,
  stories excluded, .next/out/.vercel/.turbo output ignored, docs
  headings, suggested budget 80000.
- monorepo: packages/*/src and apps/*/src signatures, per-depth build
  output ignored, tests stripped, changelogs/docs headings, suggested
  budget 100000.

Each ships NOTES.md with the tuning rationale and an explicit
"unscored, savings unmeasured" statement. PLAN's rule holds: a pack
whose Bench result is missing ships labelled unscored, never with an
invented number.

## Smoke test (run, recorded)

Environment: PYTHONPATH=src, python3 -m ghostpacks, plus the real
GhostSlice loader for cross-validation.

1. lint on all three starter packs: OK, each summary line shows
   "kind: context, unscored". list shows the same labels and the
   library paths; show on python-library prints the unscored notice.
2. Merge round trip on a fixture project with a pre-existing profile
   ({"ignore":["custom/**"], "modes":{"src/**":"full"},
   "budget_tokens":12345}):
   - Plain merge: preview diff printed, conflicts named
     (modes['src/**'] full vs signatures; budget_tokens 12345 vs
     60000), exit 1, profile byte-unchanged.
   - --force with an interactive "n": declined, profile unchanged.
   - --force --yes: merged. Union of ignores kept custom/** plus all
     pack entries, pack modes/budget won on conflicts, lockfile entry
     recorded with profile_hash_before matching the original file's
     sha256 and profile_hash_after bed786f812bb..., backup file
     created.
   - The merged profile loads under the real ghostslice
     load_profile (budget 60000, src/** signatures).
   - Appending a byte to the profile makes remove refuse (exit 2)
     with the edited-since-merge reason and both hashes.
   - Restoring the merged bytes makes remove succeed; the profile
     after remove is byte-identical to the pre-merge original
     (sha256 a112fbe9eaf1a46d687bfb216624126424f84acda80fb435d5ff27704bc868a7).
     ROUND TRIP OK.
   - Fresh-project merge (no prior profile) also verified in a
     separate run: merge created the profile plus lockfile, remove
     then deleted the merge-created profile and left the (now empty)
     lockfile as the record, as designed.
   - pip install of the checkout (with --no-build-isolation against
     the system setuptools; the sandbox cannot fetch a build backend)
     succeeds, and the installed module runs: `ghostpacks --version`
     prints 0.1.0. Note the installed package does not carry the
     repo-level packs/ folder; from an install, packs come from
     ~/.ghostpacks or --library, while a source checkout finds the
     bundled starter packs automatically.
3. Negative pack cases, each lint exit 1 with the reason named:
   a pack containing run.py (data-only), a fragment with unknown key
   'surprise', a claimed score 42 with a missing Bench report, a
   kind:"policy" manifest, an absolute path in entry_points.
4. doctor on a starter pack: OK with one honest WARN (bench:
   unscored). doctor on a project: OK, lists available packs.
5. init-pack on a project whose entry_points mixed an absolute path
   with a relative one: the absolute path was stripped and reported,
   the draft lints OK and shows as unscored.

Not done, by design: no GhostBench run was executed, so no pack
claims a score. The Next.js-vs-init Bench comparison in the PLAN
verification bar needs GhostBench (companion #4) and remains a
follow-up for parent verification, recorded here rather than
estimated around.

## Integration fix after Agent B's round-trip test (same day)

Agent B's real-exporter round-trip test caught GhostPacks
bookkeeping being scanned as project content by GhostSlice (the
lockfile and the kept backup inflated the merged export by
216 tokens on the fixture). Fixed in the core, no test changed:

- Every merge now adds two housekeeping entries to the merged
  profile's ignore list, visible in the previewed diff:
  `.ghostslice-packs.json` and `.ghostslice-packs-backup/**`.
  GhostPacks artifacts are bookkeeping, not context.
- remove now consumes the bookkeeping: it deletes the removed
  entries' backup files, drops an emptied backup directory, and
  deletes the lockfile itself when no packs remain recorded.

Verified on the B fixture shape with the real GhostSlice exporter:
baseline 249 original / 179 sliced; post-remove export is now
249 / 179, exactly the pre-merge totals, which is the PLAN.md
verification bar ("export again must match the pre-merge totals
exactly"). Full suite after the fix: 22 passed, 1 failed.

The one remaining failure is B's *merged-state* assertions
(merged sliced <= baseline, merged original == baseline). Their
residual delta after this fix is exactly the token growth of
.ghostslice.json itself (16 -> 53 estimated tokens on the fixture):
GhostSlice counts the project profile as a full-mode file, and any
merge that changes the profile necessarily changes that file's own
count. That delta is the user's real configuration, not GhostPacks
bookkeeping, and no core-side change within this tool's ownership
removes it; eliminating it would require GhostSlice to stop counting
its own profile (parent call, in the GhostSlice repo). Recorded
here and left visible in the test rather than worked around.
