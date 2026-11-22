# GhostLift - Agent B Report (tests / docs / examples / JS lift)
Prepared Oct 14, 2026. Agent B owned: tests/**, README.md, examples/**, REPORT_B.md.
Agent A owned (not edited by B): PLAN.md, pyproject.toml, src/**.

## Result

Full suite on the combined tree (Agent A core was landing in
parallel and was present for the final run):

```
PYTHONPATH=src python3 -m pytest tests -q
31 passed, 1 skipped

PYTHONPATH=src:. python3 -m unittest discover -t . -s tests
Ran 32 tests, OK (skipped=1)
```

The 1 skip is by design, not a gap: `test_js_lift.JsCoreLiftTest`
skips because the core (per PLAN.md) reports minified JS as Tier 2 /
not liftable in the core build, and the JS lift is Agent B's example
implementation, which is fully tested (see below). Both demo scripts
were also run by hand and produce the expected watermarked output.

## What was built

### tests/ (32 tests: 31 pass, 1 by-design skip)
- `test_fixtures_static.py` (8): pins the fixtures themselves.
  Source map `sourcesContent` equals the stored originals byte for
  byte; bundle references its map; the examples copy matches the
  fixture; minified JS is a single line naming the same functions as
  its readable counterpart; the .pyc sample module has exactly the
  expected signatures; and no `.pyc` fixture is shipped (they are
  interpreter-specific).
- `test_sourcemap_recovery.py` (3): Tier 1. Reference recovery from
  the map is exact, recovered sources name greeting/farewell/add/
  average, and the core - exercised through API discovery - recovers
  both originals exactly (PASSED against Agent A's `sourcemap.py`).
- `test_pyc_roundtrip.py` (5): the .pyc is generated at test time
  with this interpreter's `py_compile` (magic checked). The example
  outline lifter recovers the full ground-truth signature table
  {greet: [name, punctuation], add: [a, b], Pair: [],
  Pair.__init__: [self, left, right], Pair.swap: [self]} and
  refuses foreign magic. The core round-trip through discovery
  PASSED against Agent A's core.
- `test_js_lift.py` (6): Tier 2 JS lift against the example lifter:
  tokens preserved (whitespace-stripped output == input), braces
  balanced, multi-line output with no wall-of-text line, boundaries
  in order [clamp, describeScore, doubleIt], each function starts
  its own line, and braces/semicolons inside string literals do not
  break beautify. Plus the by-design core skip above.
- `test_watermark.py` (6): watermark token helpers; JS example
  output is watermarked tier=2; .pyc outline example output is
  watermarked tier=3; README documents the watermark and all three
  tiers; and the core manifest - via the real CLI - marks every
  file `lifted` with a tier (PASSED).
- `test_cli_contract.py` (4): real subprocess tests of Agent A's
  CLI per PLAN.md. inspect on the source map returns kind
  sourcemap / tier 1 / 2 recoverable / none missing; inspect on
  minified JS returns tier 2 / liftable false; `lift` on the map
  recovers both originals byte-exact with tier 1 manifest entries
  carrying `source_sha256`; `lift` on a generated .pyc produces a
  tier 2 manifest and lifted text naming greet/add/Pair/__init__/
  swap and labelling itself a reconstruction.
- `helpers.py` / `conftest.py`: sys.path bootstrap (src + examples),
  core API discovery across the package's submodules with tolerant
  call shapes and strict result checks, watermark/tier matchers
  covering both the in-file form (`tier=2`) and the manifest form
  (`"tier": 2`).

### examples/
- `sourcemap_demo/`: originals (greeting.js, math.js), bundle.js,
  bundle.js.map with embedded sourcesContent (Tier 1 demo).
- `minified_demo/`: app.min.js + readable app.js with the same
  three functions.
- `js_lift_demo.py`: the JS lift (Tier 2 reference implementation):
  string/comment-aware beautifier plus function-boundary finder.
  Limits stated in its docstring (regex literals, nested template
  expressions).
- `pyc_outline_demo.py`: the .pyc outline (Tier 3 reference):
  parses the marshal stream with its own small limited reader
  (CPython 3.11+ code layout, five raw counters + objects). It does
  not use the stdlib marshal loader, does not import or execute the
  artifact, and refuses unknown magic / unsupported types.
- `pyc_demo/sample_module.py`: source for at-test-time .pyc
  generation (no .pyc is committed).
- `examples/README.md`: how to run each demo.

### README.md
Explains the three tiers in plain words (Tier 1 exact, Tier 2
structured reconstruction with what does NOT come back, Tier 3
labelled outline), the watermark (manifest-first: every entry
`lifted` + tier + source artifact + sha256 + recovery kind, the
manifest note, and in-file labels where a format carries them), the
right-to-inspect rule (own code / licensed to inspect / open source
within licence; not for licence, paywall, or DRM bypass; lifted
text inherits the original's rights), safety rules (static only,
never execute an artifact, untrusted bytecode parsed as data), the
checkout layout, how to run the tests, and honest limits. It also
states plainly that core JS lifting is the follow-on target and
the JS lift in this checkout is the examples implementation.

## Assumptions and alignment notes
- A1: When B started, Agent A's core was not yet on disk. Tests
  were therefore written fixture-first, with core access through a
  discovery layer. By the final run A's PLAN.md and core
  (cli.py, core.py, sourcemap.py, pyc.py, reconstruct.py,
  marshal_safe.py) had landed, the discovery tests passed against
  them unchanged, and dedicated CLI contract tests were added
  against the now-concrete CLI (`inspect` / `lift -o`, files/ +
  manifest.json).
- A2: Watermark form. The parent brief said every lifted file is
  watermarked as lifted + tier. A's core implements that in the
  manifest (per-file `lifted`/`tier`/source/sha256 plus a global
  note), and reconstructed Python labels itself in its header.
  README.md describes that actual scheme; B's example lifters use
  the in-file comment form. No conflict found, but the parent may
  want one sentence in PLAN.md blessing both forms.
- A3: B's `pyc_outline_demo.py` first version used the stdlib
  marshal loader for trusted fixtures. That was replaced with a
  safe byte reader after A's PLAN.md made the no-blind-unmarshal
  rule explicit, so nothing in B's files can trip A's safety grep
  for the package. The demo's outline matches A's own layout
  findings (localsplus names, 3.11+ field order).
- A4: JS Tier 2 scope split is real in the combined tree: core
  `inspect` on JS returns tier 2 / liftable false with a note
  naming Agent A's build as not containing JS. B's tested JS lift
  lives only under examples/. If the parent wants JS in the core,
  that is a small port of `examples/js_lift_demo.py`, not yet done.

## Gates respected
Stdlib only (tests/examples use ast, json, marshal-free parsing,
py_compile, re, struct, subprocess, tempfile, unittest/pytest),
no network, no execution of lifted artifacts (the sample module is
only ever compiled to bytes and parsed), no push, no publish, no
spend. No files outside tests/**, README.md, examples/**, and
REPORT_B.md were created or edited by Agent B.
