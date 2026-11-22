# GhostAtlas
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/littlestjames82-sys/ghostatlas/actions/workflows/ci.yml/badge.svg)](https://github.com/littlestjames82-sys/ghostatlas/actions/workflows/ci.yml/actions)

**See how a codebase fits together, and where to start reading it.**

GhostSlice answers an agent's question: what should I read for this
task. GhostAtlas answers a person's question: how does this project
fit together, what matters in it, and where do I start.

It is built entirely on GhostSlice data (scanner, import graph and
call graph, entry-point signals, token estimator). It adds no second
size metric, no runtime tracing, and no model-written prose: an
Atlas is a finished, shareable artifact a non-operator can read
without running anything.

By Ghost Developer Studio. MIT licensed (core). **Zero
dependencies** (Python standard library only), **local-first**: no
network calls, no telemetry, your code never leaves the machine.

Position in the Ghost stack: GhostSlice governs what an agent
*reads*, GhostAtlas orients the *human* joining, reviewing, or
evaluating the project. Agent Seatbelt governs what an agent *does*.

> Status: v0.1 (Oct 2026). The core described in `PLAN.md` has
> landed and the verification suite under `tests/` passes against
> it; see `REPORT_B.md` for the test breakdown and
> `IMPLEMENTATION_A.md` for the core notes. Nothing about pricing
> or publishing is decided by this README.

## What you get

One `build` run produces two artifacts from the same scan, so the
numbers in them can never disagree:

| Artifact | What it is |
|---|---|
| `atlas.html` | A single self-contained file: static SVG/HTML module map with heat toggles (estimated token cost, caller count, git change activity), the start-here reading order, package totals, dead zones, and a checked / not-checked box. No external assets; it opens offline. |
| `ATLAS.md` | The architecture brief in Markdown: layout, entry points, a start-here reading order with a factual reason per pick, main flows from the call graph (capped, labelled as sampled from static analysis), data/config hotspots, test layout, dead zones framed as "worth asking about", and the known GhostSlice lint warnings with their explanations. |

Optionally, `--json-out` also writes the assembled run data as JSON,
and the `scan` subcommand prints that same data to stdout without
writing any artifact (see [Commands](#commands)).

What GhostAtlas does **not** do: it never edits the project, never
executes the project to build the map (static analysis only), never
calls the network, and never writes module descriptions beyond
extracted facts (names, paths, and first docstring lines). See
[Honest labels](#honest-labels).

## Install

Requires Python 3.10 or newer. There are no dependencies to install.

No install is needed to try it from a checkout:

```bash
cd ghostatlas
PYTHONPATH=src python3 -m ghostatlas --help
```

Once the package is installed, the same commands are available as
the `ghostatlas` console script:

```bash
ghostatlas --help
ghostatlas --version
```

### GhostSlice: used when importable, labelled fallback otherwise

GhostAtlas reuses GhostSlice's scanner, graph, and estimator rather
than reimplementing them. It finds GhostSlice, in order:

1. as an installed / importable `ghostslice` package,
2. via the `GHOSTATLAS_GHOSTSLICE_SRC` or `GHOSTSLICE_SRC`
   environment variable (a path to GhostSlice's `src/` directory),
3. in a sibling `ghostslice/src` checkout (next to this repo, in the
   current directory, or under `~/workspace/ghostslice/src`).

When GhostSlice is not importable, a documented fallback engine in
the package supplies the same data shapes (scanner, estimator, and
import graph). A fallback run is never silent about it: the run is
stamped `engine: fallback` in the output, in `ATLAS.md`, and in the
brief's checked / not-checked box, instead of `engine: ghostslice`.

## Quickstart

From any project you want a map of:

```bash
ghostatlas build ~/my-project -o ~/my-project-atlas.html
```

That one run writes `~/my-project-atlas.html` and, next to it,
`ATLAS.md`. Open the HTML file in any browser; it works offline.

If you omit `-o`, the HTML defaults to `<project>/atlas.html` (and
the brief to `<project>/ATLAS.md`):

```bash
ghostatlas build ~/my-project
```

For a buyer, partner, or client hand-over, reorder the same
brief for diligence:

```bash
ghostatlas build ~/my-project -o ~/atlas.html --audience diligence
```

Diligence mode leads with size and shape, test presence, the
secrets guard result (counts and types only, never values),
the dependency surface from manifests, licence files found, and
history span from git, and it includes an explicit box stating
what was checked and what was not checked. It is an orientation
aid, not an audit opinion.

To inspect the run data without writing files, use `scan`:

```bash
ghostatlas scan ~/my-project
```

`scan` prints the assembled atlas data as JSON to stdout: files,
packages, import graph, entry points, call chains, dead-zone
candidates, git activity, secrets summary (counts and types only),
lint findings, dependencies, licences, and totals.

Runnable demos against the test fixtures live in `examples/`
(see `examples/README.md`):

```bash
cd examples
./demo.sh          # onboarding atlas for the ground-truth fixture
./diligence.sh     # same fixture, --audience diligence
```

## Commands

```text
ghostatlas build <project> [-o atlas.html] [--brief ATLAS.md]
                           [--audience onboarding|diligence]
                           [--top N] [--json-out atlas.json]
ghostatlas scan  <project> [--audience onboarding|diligence]
ghostatlas --version
```

### `build` options

| Option | Default | Meaning |
|---|---|---|
| `-o`, `--out PATH` | `<project>/atlas.html` | Where to write the HTML map. Parent directories are created. |
| `--brief PATH` | `ATLAS.md` next to the HTML | Where to write the brief. Use `--brief none` to skip the brief. |
| `--audience onboarding\|diligence` | `onboarding` | Ordering and framing of the brief (see Quickstart). `scan` accepts the same flag. |
| `--top N` | `10` | Length of the start-here reading order. Values below 1 are treated as 1. |
| `--json-out PATH` | (none) | Also write the assembled atlas data as JSON to `PATH`. |

On success, `build` prints the project title, file count, total
estimated tokens, engine (`ghostslice` or `fallback`), audience,
and the paths it wrote.

### Exit codes

| Code | Meaning |
|---|---|
| `0` | Success. |
| `1` | Runtime failure (for example, the output could not be written). The error is printed to stderr, without a traceback. |
| `2` | Usage or configuration error (for example, no subcommand, a project path that is not a directory, or a malformed `atlas` section in `.ghostslice.json`). The message names the problem; a bad config key is named explicitly. |

## Honest labels

- Token counts in an Atlas are GhostSlice **estimates**, printed
  with the same estimator version a `ghostslice scan` reports.
  A number in `ATLAS.md` must always equal the same-run scan
  number; the test suite checks exactly that.
- Graph edges for Python come from full analysis. Other languages
  are import-level (parser-lite) and the map labels them as such,
  on the map itself.
- Module descriptions are extractive only: names, paths, and
  first docstring lines. A module with no docstring is shown with
  no description rather than an invented one.
- Dead zones are observations for a human to judge ("worth
  asking about"), never delete directives.
- Call chains in the brief are sampled from static analysis,
  capped, and labelled as such. They are not runtime traces.
- Secrets information is counts and types only, never values.
  The test suite plants a fake secret-shaped canary in a fixture
  and checks that it appears in no build output.

## Configuration

Atlas reads the project's `.ghostslice.json` and adds an `atlas`
section. Every key is optional; a missing file or a missing
section means the defaults below.

```json
{
  "atlas": {
    "title": "My Project",
    "audience_notes": ["Hand-over for the new maintainer."],
    "hidden_paths": ["vendor/legacy", "generated/*"]
  }
}
```

| Key | Type | Default | Meaning |
|---|---|---|---|
| `title` | non-empty string | the project directory name | Title shown on the map and at the top of the brief. |
| `audience_notes` | list of strings | `[]` | Notes printed near the top of `ATLAS.md`, each prefixed with `Note:`. |
| `hidden_paths` | list of strings | `[]` | Paths removed from every surface (map, brief, reading order, dead zones). Each entry matches a path exactly, as a directory prefix, or as a simple `*` glob. |

Unknown keys in the `atlas` section fail loudly (exit code 2, the
offending key named), the same discipline as GhostSlice profiles,
rather than being silently ignored. Malformed JSON, a non-object
`atlas` section, and wrong value types fail the same way.

## Tests

```bash
PYTHONPATH=src python3 -m pytest tests -q
```

The suite pins a ground-truth fixture (known entry point, known
graph edges, known dead file), checks the consistency bar
(ATLAS.md numbers vs a same-run GhostSlice scan), and checks the
offline bar (the generated HTML has no network-capable
constructs and never contains a planted secret-shaped canary
from the fixture).

## Layout (v0.1)

```
PLAN.md        the v0.1 plan this build follows
src/ghostatlas/ the core (Agent A)
tests/         fixture repos + verification-bar tests (Agent B)
examples/      runnable demos against the fixture repos
```

See `PLAN.md` for scope, out-of-scope items, build estimate,
and the pricing draft (MIT core free; a studio-delivered
diligence/onboarding service is a separate, undecided gate).

---
<!-- ghost-studio-footer -->
## More from Ghost Developer Studio

Ghost Developer Studio builds developer tools, AI-agent safety software, and practical apps, and sells by showing working software, not slide decks.

- [Roadmap board](https://github.com/littlestjames82-sys/ghost-roadmaps): where every studio product stands
- [Agent Seatbelt](https://github.com/littlestjames82-sys/agent-seatbelt): deterministic guardrails for AI coding agents
- [Ghost Hands](https://github.com/littlestjames82-sys/ghost-hands): governed, recorded, replayable agent hands
- [GhostSlice](https://github.com/littlestjames82-sys/ghostslice): agent context and prompt optimizer
- [GhostIDE](https://github.com/littlestjames82-sys/ghostide-android): fully offline AI code editor for Android
- [All studio projects](https://github.com/littlestjames82-sys?tab=repositories)
