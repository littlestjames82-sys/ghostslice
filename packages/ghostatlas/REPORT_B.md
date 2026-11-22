# GhostAtlas - Agent B Report (tests / README / examples)

Date: Oct 14, 2026. Scope owned: `tests/**`, `README.md`,
`examples/**`, this report. No edits to `src/**` or
`pyproject.toml`. No network, no push, no publish, no spend.

## Result: PASS, 21/21 tests

Final run (after Agent A's core landed in full):

```
$ python3 -m pytest tests -q
21 passed in 19.19s
```

Both example scripts also run green against the landed core:
`examples/demo.sh` and `examples/diligence.sh` each build an
Atlas for the fixture and print the HTML + ATLAS.md paths.

## What was built

- `tests/fixtures/ground_truth/` - ground-truth fixture repo with
  a machine-readable `TRUTH.json`:
  - entry point `main.py` (`__main__` guard, imports `engine`),
  - known edges `main.py -> engine.py`, `engine.py -> util.py`,
    `test_engine.py -> engine.py`,
  - most depended-on module `engine.py`,
  - known dead file `dead.py` (imported by nothing),
  - plus `settings.json` (config) and a prose `README.md`.
  - The fixture's own totals, judged by GhostSlice itself:
    7 files, 280 estimated tokens total.
- `tests/fixtures/secret_project/` - two-module app whose
  `vault.py` body holds a planted, fake secret-shaped canary
  (`ATLASPLANTEDSECRET...`, a test value, not a credential).
- `tests/test_fixture_truth.py` (6 tests) - pins the fixture
  against GhostSlice scanner/graph/entry-points directly, so an
  Atlas failure can never be a fixture lie.
- `tests/test_cli_contract.py` (5 tests) - `--help` lists build;
  build creates the HTML + ATLAS.md and does not modify project
  sources; an unknown key in the profile's `atlas` section fails
  loudly; `--audience diligence` states its limits.
- `tests/test_ground_truth.py` (4 tests) - PLAN verification bar:
  map edges match truth, reading order starts with `main.py`,
  dead zones list `dead.py` (and it is not a start-here pick),
  most depended-on module is named with a factual reason.
- `tests/test_consistency.py` (2 tests) - PLAN verification bar:
  numbers in ATLAS.md equal a same-run GhostSlice scan (total on
  a line saying "total", plus per-file token numbers).
- `tests/test_offline.py` (3 tests) - PLAN verification bar:
  generated HTML contains no network-capable construct (no
  http(s) references, external script/link/img, CSS @import/url,
  fetch, XHR, WebSocket, EventSource, sendBeacon), is a single
  self-contained file, and the planted canary appears in no
  build output.
- `README.md` - product README in the GhostSlice README pattern,
  with an explicit "v0.1 in build" status note and the plan's
  honest labels (estimates, parser-lite, extractive only).
- `examples/` - `demo.sh`, `diligence.sh`, `README.md`
  (fixture demos; a real-repo demo is left to parent
  verification, and the examples README says so).

## Assumptions made (core was not ready when work started)

Agent A's core did not exist when this assignment began (repo
held only `PLAN.md`); it landed in stages during the session.
The tests were written against the PLAN's contract, in
`tests/conftest.py` as the single adjustment point:

1. Invocation is the GhostSlice pattern:
   `PYTHONPATH=src python3 -m ghostatlas build <project> -o
   <atlas.html>`, console script as fallback. The landed core
   matches this exactly.
2. `ATLAS.md` is produced by the same build run; the harness
   looks next to the HTML first, then the CWD, then the project.
   The landed core writes it next to the HTML.
3. Structured data may come from an `atlas.json` file or, as the
   landed core actually does, a JSON run-data block embedded in
   the HTML, including the GhostSlice-shaped `graph`
   (`{file: {"imports": [...]}}`). The harness parses both.
4. Unknown `atlas` profile keys fail loudly. The landed core
   does this and the test passes against it.
5. One adjustment cycle was needed mid-session, all in the
   harness, none in the core: section parsing now stops at the
   next heading, the "total" line match is case-insensitive,
   and edges are also read from the embedded graph dict. The
   first full-core run was 18/21 for exactly those three
   harness reasons; the three patterns the tests now accept are
   the core's genuine, documented output formats.

## Honest limits

- Offline test method: this environment has no browser, so
  "zero network requests when opened" is enforced as the absence
  of every network-capable construct in the static file, which
  is what makes requests impossible, rather than observed live
  browser traffic. A browser-level check remains a
  parent-verification option.
- The dead-zone and reading-order assertions parse Markdown
  headings; if the core's brief format changes section titles,
  `section_after` in `conftest.py` is where to update needles.
- Real-repo demos (GhostBus; one parked project, per PLAN.md)
  were not run by Agent B; fixture demos only.
- Early in the session, before the core landed, the suite
  honestly reported 14 integration failures / 7 passes (the 6
  fixture-truth tests plus 1). That state is superseded by the
  final 21/21 above.

## Gates held

Stdlib/pytest only, local only, no network calls made, nothing
pushed, published, or announced, no spend. The planted secret
is a labelled fake fixture value used only as a leak canary.
