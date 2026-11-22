# GhostDeps v0.1 - Agent B report (tests, README, examples)

Ownership respected: only `tests/**`, `README.md`, `examples/**`, and
this file were written. Nothing under `src/**`, `pyproject.toml`, or
`PLAN.md` was edited.

## Final result against the real core

```
PYTHONPATH=src python3 -m pytest tests -q
19 passed, 0 failed, 0 skipped   (two consecutive full runs)
```

Discovery route used by the suite: `GHOSTDEPS_CMD` env override, then
`ghostdeps` on PATH, then `python -m ghostdeps` with `PYTHONPATH=src`.
The final runs used the third route against Agent A's landed core
(`pack` and `doctor` subcommands, version 0.1.0). Suite breakdown:

- `test_fixtures.py` (4): fixture validity, no CLI needed. The planted
  gaps are verified by direct file reads so fixture drift fails here,
  not downstream.
- `test_pack_python.py` (4): gap placement, exact pins, wording scan,
  clean project.
- `test_pack_node.py` (4): gap placement, exact lockfile pins, pack
  smaller than the raw lockfile, wording scan.
- `test_doctor_and_edges.py` (5): doctor exit codes (1 on findings,
  0 clean, 2 no manifests), no-manifest reporting, read-only tree
  hash check, parser labels.
- `test_examples.py` (2): the shipped example projects pack with the
  planted gaps in the right sections.

## Hard rules pinned by tests

- Python fixture: `colorama` (declared, never imported) lands in the
  declared-not-imported section with "no import found" phrasing;
  `numpy` (imported, never declared) lands in imported-not-declared
  with `app.py` named as evidence; `Pillow` is matched via its `PIL`
  import; stdlib (`os`) and the local `helper` module are flagged
  nowhere.
- Node fixture: `lodash` declared-not-imported; `axios`
  imported-not-declared with `index.js` named; the local `./util`
  require is not a gap.
- Pins exact: `2.31.0` / `10.2.0` / `0.4.6` from the fixture
  `requirements.txt` and `4.18.2` / `4.17.21` from the fixture
  `package-lock.json` appear verbatim in the pins section and in
  `deps-manifest.json`.
- Wording scan over DEPS.md, the manifest JSON, and CLI output for
  every generated pack: none of "safe to remove", "vulnerable",
  "vulnerability", "outdated", "latest version", "dead code",
  "security risk", "critical severity" appears.
- No-manifest project: pack exits 2 with "no manifest or lockfile
  could be parsed" on stderr and writes no pack; doctor exits 2 and
  prints "no manifests or lockfiles found". No tracebacks anywhere.
- Read-only: the project tree's file hashes are identical before and
  after a pack run.
- Exit contract (aligned to the shipped core, which applies the
  plan's doctor codes to `pack` as well): 0 clean, 1 findings
  (imported-not-declared), 2 nothing parseable.

## Contract alignments made while Agent A landed

- The plan names the DEPS.md sections declared-and-used /
  declared-not-imported / imported-not-declared; the shipped core
  titles them "Declared and imported", "Declared, no import found in
  scanned code", "Imported, no declaration found", and "Version pins
  as recorded". The test section slicer keys on markdown headings and
  accepts both namings. The core's titles are arguably better (they
  carry the evidence wording in the heading itself).
- During A's landing, an early core build crashed on any project
  (`TypeError` in `manifests.py: discover_sources`, str path joined
  with `/`). A fixed it in-flight; the final tree shows no trace of
  it. Recorded here only because B's first smoke hit it.

## Findings for the parent / Agent A (not fixed by B)

**F1 - `setuptools` from `[build-system]` is counted as a declared
dependency.** The plan scopes pyproject parsing to project
dependencies, optional-dependencies, and dependency-groups. The core
also reads `[build-system] requires`, so the example Python project
reports "Declared dependencies: 4" and lists `setuptools`
(python, build) under "Declared, no import found in scanned code".
Evidence: `examples/python_project` pack output, summary counts and
the declared-not-imported section. Nearly every real pyproject
project will show its build backend in that section, which adds
noise to an information-only section. It may be a deliberate choice
(build deps are real declarations), but it is outside the plan's
stated scope; parent adjudication.

**F2 - Lockfile pins are listed for every package entry, and the
pack can exceed the raw lockfile on small projects.** The plan says
`package-lock.json` is read at summary level (lockfile version, root
package pins) and its JS verification bar says the pack output must
be "dramatically smaller than the raw lockfile". The core lists one
pin line per lockfile package entry (43 pins for the small example,
transitive entries included) in DEPS.md and carries per-pin records
in `deps-manifest.json`. Measured on `examples/node_project`:
lockfile 8,158 bytes; pack 14,889 bytes (DEPS.md 5,745 +
deps-manifest.json 9,144). The pack is larger than the file it
summarises. On the fatter synthetic fixture in `test_pack_node.py`
(80 transitive entries with full resolved/integrity payload) the
pack is smaller and the size test passes, so the bar holds when
lockfile entries carry their usual weight, but not in general.
The core's own wording ("43 top-level pin(s)") suggests "top-level"
was the intent; whether transitive entries count as top-level pins
is a parent call. B's size test pins the fixture case only and does
not assert the example case, so this finding is not hidden by a
green suite.

## Examples delivered

- `examples/python_project/`: pyproject + requirements pins,
  `app.py` importing requests, PIL, and undeclared numpy, local
  `helper` module. Same planted gaps as the test fixture.
- `examples/node_project/`: package.json + lockfileVersion 3
  lockfile (express 4.18.2, lodash 4.17.21, 40 padded transitive
  entries), `index.js` requiring express and undeclared axios, local
  `util.js`.
- `examples/README.md`: walkthrough of both, with the exact sections
  and exit codes to expect.

## Gates held

Stdlib only (tests included), local only, no network at any point,
no GitHub push, no PyPI/publish, no announcements, no spend. No em
dashes in README or examples copy (the only em dash characters in
B's files are inside a regex character class in
`tests/helpers.py` that tolerates heading separators).
