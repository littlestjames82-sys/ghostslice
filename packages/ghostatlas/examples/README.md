# GhostAtlas examples

Runnable demos against the fixture repos in `tests/`, all fully
local: no network, no writes to the fixture projects. Each script
builds into a fresh temp folder and prints where the output landed.

## Prerequisites

- Python 3.10 or newer.
- Run the scripts from this directory (`examples/`). Each script
  sets `PYTHONPATH` to the repo's `src/` itself, so no install is
  needed.
- GhostSlice is used when it is importable (for example, a sibling
  checkout); otherwise the run uses GhostAtlas's labelled fallback
  engine and stamps the output `engine: fallback`. Either way the
  demos run; only the engine stamp differs.

## 1. Fixture map (`demo.sh`)

```bash
./demo.sh
```

Builds an onboarding Atlas for the ground-truth fixture
(`tests/fixtures/ground_truth/project`) and prints two paths:

```text
HTML map:  /tmp/.../atlas.html
Brief:     /tmp/.../ATLAS.md  (or next to the HTML output)
```

Open the HTML file in any browser. It is a single self-contained
file and works offline; try the Tokens / Callers / Change activity
heat toggles above the map.

What to look for in the output:

- Reading order starts with `main.py` (the fixture's entry point,
  `__main__` guard).
- The map shows `main.py -> engine.py -> util.py`.
- `dead.py` appears under dead zones ("worth asking about"),
  nowhere else.
- Every token number in `ATLAS.md` matches a
  `ghostslice scan` of the same fixture.

The equivalent by hand:

```bash
PYTHONPATH=../src python3 -m ghostatlas build \
  ../tests/fixtures/ground_truth/project -o /tmp/atlas.html
```

## 2. Diligence brief (`diligence.sh`)

```bash
./diligence.sh
```

Same fixture, `--audience diligence`. The HTML is the same map;
the brief is what changes:

- `ATLAS.md` leads with size and shape, test presence, the secrets
  guard result (counts and types only, never values), the
  dependency surface, licence files found, and git history span.
- It includes the checked / not-checked box near the top.
- It is an orientation aid, not an audit opinion, and the brief
  says so.

## 3. Scan only (no artifacts)

To see the assembled run data without writing any files:

```bash
PYTHONPATH=../src python3 -m ghostatlas scan \
  ../tests/fixtures/ground_truth/project
```

This prints the atlas data as JSON to stdout (files, packages,
import graph, entry points, dead-zone candidates, totals), which
is convenient for piping into `python3 -m json.tool` or a script.

## Not included yet

A demo on a real repo (GhostBus, and one parked project, per
`PLAN.md`) belongs with the parent verification step once the
core lands; the fixture demos above are what the test suite can
reproduce byte-for-byte in totals today.
