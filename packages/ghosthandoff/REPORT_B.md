# GhostHandoff v0.1 - Agent B report (tests, README, examples)

Date: Oct 14, 2026. Scope owned: `tests/**`, `README.md`,
`examples/**`, this report. No edits to `src/**`, `pyproject.toml`,
or `PLAN.md`.

## Final result

```text
python3 -m pytest tests -q   ->   29 passed, 0 failed
```

Run twice against the final core, same result both times
(26.35s and 33.16s). CLI discovered via `python -m ghosthandoff`
with `PYTHONPATH=src` (no installed console script in the sandbox).

## What the suite contains

- `tests/helpers.py` - CLI discovery (env `GHOSTHANDOFF_CMD`, then
  PATH, then `python -m ghosthandoff` with `PYTHONPATH=src`, then
  repo root; CLI tests skip cleanly if none responds), plus git
  fixture builders. Fixtures are real git repositories built with
  the git CLI in tmp dirs, so ground truth is whatever git itself
  reports.
- `tests/test_fixtures.py` (8 tests) - the PLAN verification-bar
  repo really is in its stated state: branch
  `feature/handoff-fixture`, 3 commits (one dated 2026-10-11, two
  fresh), porcelain codes `M ` for CHANGELOG.md, ` M` for
  README.md, `??` for scratch.py plus the two verify artifacts,
  exactly 1 stash entry, exactly 3 markers found by an independent
  scan, verify-report.json parsing with verdict `failed`. Also a
  clean repo and a non-git folder fixture.
- `tests/test_cli_pack.py` (13 tests) - pack writes HANDOFF.md and
  handoff.json; branch and short HEAD named in both; session
  commits are exactly the two fresh subjects (the old subject is
  absent from the JSON commit list); staged / unstaged / untracked
  file lists match porcelain ground truth; stash reported; all 3
  markers listed in both outputs; failing verdict quoted;
  `--since 4d` pulls the old commit into the window; a secret-shaped
  string inside a marker line never reaches either pack file;
  default output lands in the caller's CWD, not the project;
  missing project exits 2.
- `tests/test_no_invention.py` (6 tests) - clean repo produces
  empty open-loop, next-step, and marker lists and says so in
  words; the fixture pack's loops fall into exactly the 5 planted
  fact categories (uncommitted, untracked, stash, markers,
  verification), 5 loops, each naming its source; next steps are
  labelled as proposals on the face of the pack; non-git folder
  packs with exit 0, git section marked unavailable, marker
  section still working, tree untouched.
- `tests/test_cli_show.py` (1 test) - `show` prints exactly the
  HANDOFF.md on disk.
- `tests/test_mcp.py` (1 test) - stdio handshake; once tools/list
  answers, asserts the plan tool names `build_handoff` and
  `read_handoff`. Skips conservatively if the server never answers.

## Hard-rule pins

- **Byte-identical tree:** `test_pack_leaves_project_byte_identical`
  hashes every file under the fixture repo, `.git` included, plus
  porcelain output and HEAD, before and after a pack run. All
  equal. (Index settling: the fixture builder runs one
  `git status` at build time so a stat-refresh cannot masquerade
  as a tool write; the core's own runs then change nothing, which
  matches the plan's optional-locks-disabled claim.)
- **Git state accuracy:** asserted against porcelain / log / stash
  output produced by git itself, not against hand-written
  expectations.
- **No invented loops:** loops must categorise into exactly the
  planted fact categories, count exactly 5, and each must carry a
  source. Clean repo must produce zero loops and zero steps.
- **Propose-only:** the pack labels itself propose-only on its
  face, HEAD is unchanged after a run, and output appears only in
  the chosen directory (default-output test).

## Triage record (first full run: 23 passed, 4 failed)

All four failures were test-side over-strictness, found by reading
real pack output; no core code was changed by Agent B and no
assertion was weakened in substance:

1. Marker format: the core renders a marker as
   `file:line [KIND]: <text after the marker word>`, e.g.
   `notes.txt:2 [TODO]: water the plants on Friday.` Tests had
   asserted the raw source line (`TODO: water the plants...`).
   Fixed to assert file + kind + marker body text, which is the
   plan-level contract (quoted, truncated, redacted).
2. Open-loop anchoring: loops carry counts and a named source, not
   per-file names (e.g. "1 staged and 1 unstaged file(s) are not
   committed", source "git status"). The plan requires each loop
   to name its source, which it does. Test rewritten to the
   category check described above, which is stricter about
   invention (exact category set, exact count) than the original.
3. Clean-repo markers: the JSON markers section is a dict
   (`{total, by_kind, items, ...}`), and the test helper treated a
   dict value as one entry. Helper now reads a section dict's
   `items` list. The core's clean output was correct (total 0).
4. Non-git marker assertion: same marker-rendering point as (1).

One near-miss worth recording: `--since 3d` initially looked like
it dropped the old commit wrongly. It did not: the old commit is
dated 2026-10-11T10:00 and the run was 2026-10-14T13:32 UTC, so it
is just over 3 days old and correctly outside a strict 3d window.
`--since 4d` includes it, verified by hand and pinned by a test.

## Defects found in the core

None. Behaviours verified by hand beyond the suite: redaction of
an AKIA-shaped canary in a marker line (replaced with
`[redacted-secret-shape]` in both outputs), non-git note on
stdout, window label printed on the pack
("last 4d (from --since 4d) plus all uncommitted changes").

## Observations (not defects)

- The untracked count in a fixture pack is 3, not 1: scratch.py
  plus verify-report.json and VERIFY.md, which are untracked too.
  Correct per porcelain; a reader should expect report artifacts
  left in a project root to count as untracked.
- Session "files touched" (7 on the fixture) unions commit-touched
  files with working-tree files, including the untracked verify
  artifacts. Reasonable reading of the plan, stated here so the
  parent is not surprised by the number.

## Assumptions

- CLI verbs and outputs are taken from PLAN.md as written by
  Agent A (`pack` / `show` / `mcp`, HANDOFF.md + handoff.json).
  Once the core landed, the suite was aligned to its real JSON
  shape (top-level `git`, `markers`, `reports`, `open_loops`,
  `next_steps`) while keeping key-name-lenient diggers where the
  plan fixes facts rather than key names.
- Git 2.43 is present in the sandbox; fixtures use `git init -b`
  and per-repo user config, no global git state is touched.
