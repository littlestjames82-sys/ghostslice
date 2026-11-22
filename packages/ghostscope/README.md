# GhostScope
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/littlestjames82-sys/ghostscope/actions/workflows/ci.yml/badge.svg)](https://github.com/littlestjames82-sys/ghostscope/actions/workflows/ci.yml/actions)

**See what a change actually touches, before you review it.**

GhostSlice builds task-centred context bundles from a whole project.
GhostScope builds *change-centred* review packs from a diff: the changed
files in full, their callers and callees in proportion to risk, the tests
that cover them, and a riskiest-first reading order with the reasons
written out. For a human reviewer it is the reading order. For an agent
reviewer it is the prompt, at a fraction of the full-repo token cost.

By Ghost Developer Studio. Working name (see PLAN.md). MIT core,
same pattern as GhostSlice / Agent Seatbelt / Ghost Hands. Local only:
no hosting API, no network, no model calls in v0.1.

Position in the Ghost stack: GhostSlice governs what an agent *reads*
for a task, GhostScope governs what a reviewer *reads* for a change,
GhostVerify *checks* a patch, Agent Seatbelt governs what an agent
*does*.

## Status

v0.1. The CLI, pack export, `check`, and stdio MCP server described
below are implemented in `src/ghostscope/`. The tests in `tests/`
encode the contract in PLAN.md. Run them (see Tests, below) to see
the state of a checkout.

## Install (from a checkout)

```bash
cd ghostscope
pip install .
ghostscope --help
```

Or without installing, using the `src` layout directly:

```bash
PYTHONPATH=src python3 -m ghostscope --help
```

Requires Python 3.10+ and `git` on PATH. Zero dependencies (Python
standard library only), like the rest of the family.

## Quickstart

Run these from inside the project under review (a local git repo),
or pass that project's path instead of `.`. Pick exactly one input
for `pack`: a `--base`/`--head` range, `--staged`, or `--diff`.

```bash
# Pack the changes between two refs
ghostscope pack . --base main --head HEAD -o /tmp/review-pack

# Pack staged changes
ghostscope pack . --staged -o /tmp/review-pack

# Pack from a diff file
ghostscope pack . --diff changes.diff -o /tmp/review-pack

# Validate the pack you just wrote
ghostscope check /tmp/review-pack

# Why is this file in the pack, and at what mode?
# Signature: ghostscope explain <project> <file> --pack <pack-dir>
ghostscope explain . src/shared.py --pack /tmp/review-pack
```

Without `--pack`, `explain` re-analyses the project for the input
range you give it (the same `--base` / `--head` / `--staged` /
`--diff` options as `pack`) instead of reading an existing pack.
Add `--json` to `pack`, `explain`, or `check` for machine-readable
output instead of the human-readable summary.

Exit codes: `0` means success, `1` means a `--fit` budget was not
met (the pack is still written) or `check` failed, and `2` means a
usage or input error (for example, a diff that does not match the
working tree, index, or `head` blob it claims to describe).

A pack is a normal GhostSlice bundle plus two GhostScope files:

```
review-pack/
  manifest.json   GhostSlice manifest (per file: mode, tokens, sha256)
  scope.json      base, head, per-file graph distance, risk reasons
  REVIEW.md       change summary, risk list in order, reading order,
                  token totals (estimates) vs repo total and raw diff
  PROMPT.md       the pack as an agent-ready prompt (Slice presets)
  files/<rel>     the sliced file bodies (see the mode table below)
```

How much of each file is included depends on its graph distance
from the change:

| File | Mode in the pack |
| --- | --- |
| Changed file | `full` |
| Distance-1 neighbour (direct caller / callee) | `signatures` |
| Distance-2 neighbour | `interfaces` |
| Covering test for a changed symbol | `full` |
| Deleted file | `exclude` (listed in the manifest, no body) |

Validate a pack the same way as any Slice bundle:

```bash
ghostslice check /tmp/review-pack
```

## Risk, with reasons

GhostScope never prints a bare risk score. Every ranked item carries
its reasons, for example:

- `compute_total` in `shared.py`: exported API, 6 callers, covering test present
- `charge` in `billing.py`: no covering test (covering test deleted in this diff)

Reasons come from the import graph and the call graph. Python call
edges are exact (stdlib `ast`, via GhostSlice). Other languages are
import + outline level and are labelled `parser-lite` in the pack;
their covering-test mapping is heuristic and says so.

Cover that the diff itself removed is reported as lost, not just as
missing: if a test file the diff deleted (or a test function it
edited away) covered a changed symbol on the base side, the pack
links them, with the reason `covering test deleted in this diff
(<test path>)` (or `removed` for an edited test file), a factual
note citing file + symbol + test, and a `lost_covering_tests` entry
per changed file in `scope.json`. Symbol links are call-proven;
import-only base cover is reported at file level, not guessed onto
a symbol. A symbol that keeps other covering tests is not labelled
as having no covering test.

A profile can mark paths as sensitive so changes there always rank
higher. In `.ghostslice.json`:

```json
{
  "scope": {
    "sensitive_paths": ["src/auth/**", "src/payments/**"]
  }
}
```

There are no built-in sensitive-path guesses beyond what the profile
says.

## `--fit`

```bash
ghostscope pack . --base main --head HEAD --fit 40000 -o /tmp/review-pack
```

Uses GhostSlice's fit ladder, with one rule on top: changed files
(and covering tests) are never downgraded. Neighbours are downgraded
first. If the pack still cannot fit, the pack is still written and
the exit code is 1.

## What GhostScope does not do (v0.1)

- No GitHub/GitLab API, no PR fetching, no posting comments, no merge
  actions. Local git and diff files only.
- No approvals or review decisions. It states facts (a signature
  changed, a caller was not updated in this diff, a covering test was
  deleted in this diff), each citing file + symbol.
- No style review, no naming opinions, no LLM-written prose.
- It does not apply patches or run tests. It names the covering tests;
  GhostVerify runs them.

## MCP

Start the stdio MCP server with:

```bash
ghostscope mcp
```

It follows the GhostSlice pattern and exposes two tools:

- `scope_pack`: build a review pack for a project + git range.
  Requires `project` and `out`; `base`, `head`, `staged`, `diff`,
  and `fit` are optional.
- `scope_explain`: why a file is in a pack, at what mode, with its
  risk reasons. Requires `pack` (the pack directory) and `file`.

Payloads are capped summaries, no raw file bodies by default.

## Tests

```bash
PYTHONPATH=src:. python3 -m pytest tests -q
# or, with the stdlib runner only (name the modules: the fixture
# projects under tests/fixtures/ contain their own test_*.py files,
# which are data, and tests/conftest.py keeps pytest from
# collecting them):
PYTHONPATH=.:src python3 -m unittest tests.test_fixtures_static tests.test_pack_integration -v
```

The fixtures under `tests/fixtures/` are planted cases for the
Verification bar in PLAN.md:

- `high_blast_radius`: a one-line change to a function with 6 callers
  must outrank a 220-line change to an isolated file.
- `signature_change_stale_caller`: an exported function gains a
  required parameter and its callers are not updated.
- `deleted_covering_test`: a change whose only covering test is
  deleted in the same diff; the pack must say so in plain words.

`tests/test_fixtures_static.py` validates the fixtures themselves.
`tests/test_pack_integration.py` runs the real CLI and fails (rather
than skipping) if the core cannot be imported, so a broken checkout
cannot look green by accident. One integration test, the optional
`ghostslice check` cross-check, skips when `ghostslice` is not on
`PATH`.

## Examples

See `examples/`:

- `examples/run_demo.sh`: builds a git repo from the high-blast-radius
  fixture and packs it.
- `examples/sample_pack/`: the *shape* of a finished pack (`scope.json`
  + `REVIEW.md`), labelled as a sample, not captured run output.

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
