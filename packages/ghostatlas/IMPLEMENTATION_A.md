# GhostAtlas v0.1 - Agent A (core builder) implementation report

Built Oct 14, 2026 from ~/workspace/ghostatlas/PLAN.md. Python stdlib
only, zero dependencies, zero network. No push, no publish, no spend.

## Files owned and written (Agent A only)
- `pyproject.toml` - ghostatlas 0.1.0, `ghostatlas` console script, src layout.
- `src/ghostatlas/__init__.py` - version 0.1.0, exports build_atlas_data / AtlasData.
- `src/ghostatlas/__main__.py` - `python -m ghostatlas` entry.
- `src/ghostatlas/config.py` - reads `.ghostslice.json`, validates the
  `atlas` section (title, audience_notes, hidden_paths). Unknown atlas
  keys fail loudly with a ValueError naming the key, CLI exit 2.
- `src/ghostatlas/engine.py` - GhostSlice discovery (import, env
  GHOSTATLAS_GHOSTSLICE_SRC / GHOSTSLICE_SRC, sibling
  workspace/ghostslice/src) + documented fallback engine with the same
  shapes: .gitignore-lite scanner, same BPE-like calibrated token
  estimator method, Python ast / TS-JS regex import graph, entry
  candidates with evidence signals. Engine used is stamped in output.
- `src/ghostatlas/data.py` - single-run data assembly (AtlasData):
  GhostSlice scan, import graph, entry candidates, summarize_packages,
  find_duplicates, secrets scan (aggregated to counts + types only),
  lint findings, prune/dead recommendations, Python call graph sampled
  chains (capped at 10, labelled sampled), git activity + history span
  (window labelled "last 200 commits"), dependency surface from
  manifests (names only), licence files, per-file docstring first line
  + top symbols extracted, hidden_paths filtering across all surfaces.
- `src/ghostatlas/reading.py` - start-here reading order (entries with
  evidence first, then most-depended-on, then docs; estimated tokens +
  reading minutes per item) and dead zones (dead candidates,
  unreferenced docs, duplicate clusters) framed as "worth asking
  about", never as delete instructions.
- `src/ghostatlas/render.py` - self-contained offline atlas.html:
  inline CSS, inline SVG module map (columns = package/top directory,
  nodes sized by estimated tokens, import edges, package labels),
  heat toggles (tokens / caller count / git change activity) driven by
  an embedded JSON block parsed with JSON.parse and rendered via
  textContent (no project strings via innerHTML), zoom buttons.
  Zero external assets or URLs.
- `src/ghostatlas/brief.py` - ATLAS.md from the same AtlasData:
  layout, reading order, sampled call chains labelled, module list of
  extracted docstring first lines ("No docstring first line found."
  when none - no invented descriptions), config/data hotspots, test
  layout, dead zones, carried GhostSlice lint findings, and a
  checked / not checked box. `--audience diligence` reorders
  (size/shape first, test presence, secrets counts/types only,
  dependency surface, licence files, git history span) and states
  "orientation aid, not an audit opinion".
- `src/ghostatlas/cli.py` - `ghostatlas build <project> [-o out.html]
  [--brief ATLAS.md|none] [--audience onboarding|diligence]
  [--top N] [--json-out file]` and `ghostatlas scan <project>`
  (JSON summary). Exit codes: 0 ok, 1 runtime, 2 usage/config.

Not touched (other agents' surfaces): tests/**, README.md, examples.

## Smoke test (fixture repo, recorded)
Fixture built at /tmp/atlas-fixture: Python package pkg/ (core.py,
util.py, an exact-duplicate util_copy.py, dead.py imported by nobody),
main.py entry (package.json "bin" + __main__ guard), tests/test_core.py,
vendor/lib, README.md, LICENSE, package.json (left-pad dep),
config.py holding a fake sensitive assignment, .ghostslice.json with
atlas title, and a git repo (1 commit).

Commands:
- `PYTHONPATH=src python3 -m ghostatlas build /tmp/atlas-fixture -o /tmp/atlas-out/atlas.html` -> exit 0.
- Same with `--audience diligence` -> exit 0, brief reordered.
- Fresh venv `pip install .` -> console script `ghostatlas build` OK.

Results, all matching ground truth / GhostSlice:
- 13 files, 338 estimated tokens; GhostSlice `scan` on the same tree
  also reports 13 files / 338 tokens (consistency bar met).
- Reading order #1 = main.py with entry evidence
  (package.json "bin" signal first), then pkg/core.py
  ("Depended on by 2 file(s)"), pkg/util.py, README.md.
- Sampled call chain found: `<module> -> grand_total -> total`,
  labelled sampled from static analysis.
- Dead zones include pkg/dead.py and pkg/util_copy.py; duplicate
  cluster exact: pkg/util.py + pkg/util_copy.py.
- Docstring first lines extracted verbatim (e.g. "Core pricing engine
  for the fixture project."); files without one say so explicitly.
- Diligence brief: secrets guard 1 finding, type sensitive-assignment
  only; dependency surface: left-pad; licences: LICENSE; git span
  2026-10-14 to 2026-10-14, 1 commit.
- Planted secret value appears 0 times in atlas.html,
  atlas-diligence.html, ATLAS.md, ATLAS-diligence.md (grep verified).
- HTML contains no http/https external references (grep verified).
- Unknown atlas key (`{"atlas": {"bogus": 1}}`) -> exit 2 with the
  key named. hidden_paths ["pkg/dead.py","vendor"] -> 11 files, both
  hidden targets absent from every surface.
- Fallback engine direct check: fallback_scan / fallback_graph /
  fallback_entries on the fixture give 13 files, main.py imports
  pkg/core.py + pkg/util.py, main.py as top entry candidate.

- Agent B's parallel test suite (tests/**, 21 tests: ground truth,
  consistency vs same-run GhostSlice scan/graph, offline, secret
  absence, CLI contract): run after completion - 21 passed.

## Honest limits (from PLAN.md, carried into output)
- Non-Python import edges are parser-lite and labelled as such on the
  artifact itself, not in a footnote.
- Reading minutes are a stated estimate (0.5 min per 1k estimated
  tokens) applied uniformly.
- Layout is a deterministic column layout, not a force-directed
  graph; on very large repos it will be long rather than tangled.
- Secrets summary depends on GhostSlice's guard; its placeholder
  rules apply (canonical EXAMPLE keys are not flagged, by design).
