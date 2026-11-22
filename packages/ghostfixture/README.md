# GhostFixture
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/littlestjames82-sys/ghostfixture/actions/workflows/ci.yml/badge.svg)](https://github.com/littlestjames82-sys/ghostfixture/actions/workflows/ci.yml/actions)

Minimal repro project generator for GhostSlice bundles.

A GhostSlice bundle is reading material: sliced text, a
manifest, a prompt file. It is not a project you can open, hand
to a teammate, or attach to a bug report. GhostFixture turns a
bundle back into a small, real directory tree: the files the
bundle references, copied from the original project at full
fidelity, plus the local files those files import, and nothing
else. Flagged secrets are excluded by default, and everything
left out is named with a reason.

## Install

Requirements: Python 3.10 or newer. GhostFixture uses only the
Python standard library, so there is nothing else to install.

```sh
pip install .
ghostfixture --version
```

Without installing, run it from a checkout with
`PYTHONPATH=src python3 -m ghostfixture ...`, exactly as the
walkthrough in `examples/` does.

## Quick start

```sh
# 1. Build a fixture from a project and the bundle cut from it.
ghostfixture build <project> <bundle> -o <out-dir> [--task "..."]

# 2. Later, or on another machine, verify the tree is unchanged.
ghostfixture check <fixture-dir>
```

- `build` reads the bundle's manifest, takes every file listed
  at a mode other than `exclude` as the seed set, resolves the
  static local import closure of those files inside the
  project, and copies the originals into a brand-new output
  tree.
- `check` re-verifies a fixture tree against its manifest:
  every included file present with a matching sha256, no
  unexplained extra files, no excluded file present.

Worked example with the bundled demo project and demo bundle:

```sh
ghostfixture build examples/demo_project examples/demo_bundle \
    -o /tmp/demo-fixture --task "Fix the tax rounding in pricing.py"
ghostfixture check /tmp/demo-fixture
```

See `examples/README.md` for what that build includes, what it
leaves out, and why.

## Command reference

`ghostfixture build <project> <bundle> -o <out-dir> [options]`

| Option | What it does |
| --- | --- |
| `-o`, `--out DIR` | Required. New output directory. It must not be inside the project, must not contain the project, and an existing non-empty directory is refused. |
| `--task "..."` | Task description recorded in the manifest and `FIXTURE.md`. |
| `--task-file FILE` | Read the task description from a file instead. Takes precedence over `--task` when both are given. |
| `--max-bytes N` | Cap on total copied content, in bytes (default 2097152, 2 MiB). |
| `--include-flagged` | Copy secret-flagged files anyway. The flag and the override stay on record in the manifest. |
| `--json` | Print the full fixture manifest as JSON instead of the human summary. |

`ghostfixture check <fixture-dir> [--json]`

Re-verifies the fixture against its `fixture-manifest.json`.
`--json` prints the check result as JSON instead of the human
summary.

`ghostfixture mcp`

Runs the stdio MCP server described under "What you get".

Exit codes:

| Command | 0 | 1 | 2 |
| --- | --- | --- | --- |
| `build` | fixture built | fixture would be empty | could not build |
| `check` | clean | mismatch | could not check |

Exclusions and left-out files during a build are normal,
reported outcomes, not failures: a build that copies at least
one file exits 0 and names everything it left out.

## The rules it keeps

- **The source project is never modified.** It is only read.
  The output directory must not be inside the project, the
  project must not be inside the output, and an existing
  non-empty output directory is refused.
- **Secret-flagged files are excluded by default.** Before
  copying, each candidate file is scanned for secret shapes
  (provider token shapes, private key headers, password-bearing
  URLs, sensitive-name assignments). A flagged file is left
  out and recorded in the manifest by path and pattern type
  only, never by value. `--include-flagged` overrides this,
  and the manifest still records that the file was flagged and
  included by override. There is no quiet path.
- **Guard findings recorded in the bundle are propagated.**
  When a bundle was exported with GhostSlice's redaction on,
  its manifest records the guard's findings per file (the
  `redactions` count and `redaction_kinds` fields). GhostFixture
  reads those records and never drops them silently. Where its
  own shape scan confirms the flag, the file is excluded as
  usual and the record names both verdicts. Where the shape
  scan does not confirm it, the file is copied, and the
  disagreement is recorded in the manifest (under
  `upstream_disagreements`) and in a named section of
  `FIXTURE.md`, with the kinds the guard reported and the
  reason the file was still copied. The two scanners disagree
  by design: the guard is name-based, this scan is
  shape-based, so a disagreement is information for the
  reader, not an error. A plain export records no findings
  in the manifest (its guard warning lives only on the
  export terminal), so there is nothing to propagate from
  such a bundle.
- **A size cap is enforced and stated.** Total copied content
  is capped (default 2 MiB, set with `--max-bytes N`). The cap
  is printed in the CLI output and recorded in the manifest.
  Bundle-referenced files are kept first, closure files after,
  in deterministic order; files that do not fit are left out
  with reason `size-cap`.
- **Nothing unreferenced comes along.** No `.git`, no scratch
  files, no bundle artifacts beyond the fixture's own manifest
  and summary.
- **Missing and escaping files are reported, not invented.**
  A referenced file that is absent from the project is left
  out with reason `missing-in-project`. Symlinks are never
  followed out of the project root; an escaping path is left
  out with its reason recorded.

## What you get

The output tree root holds two records next to the copied
files:

- `fixture-manifest.json` - the machine record: task, source
  project, source bundle path and manifest sha256, the size
  cap in force, totals, `included[]` (path, reason
  `bundle-referenced` or `import-closure`, importer where
  applicable, bytes, sha256), `excluded_flagged[]` (path and
  pattern types only), `left_out[]` (path and reason),
  `upstream_disagreements[]` (files copied despite a guard
  finding recorded in the bundle manifest, with the
  upstream kinds), and `external_references[]` for imports
  that point outside the project.
- `FIXTURE.md` - the same record in human form, plus how the
  fixture was made and its limits.

An MCP server (`ghostfixture mcp`, stdio, local only, no
network) exposes two tools with capped summary payloads and
no file bodies:

| Tool | Arguments | Returns |
| --- | --- | --- |
| `build_fixture` | `project`, `bundle`, `out` (required); `task`, `max_bytes` (optional) | Totals, the size cap, and the included, excluded-flagged, and left-out lists |
| `check_fixture` | `fixture` | The same result as `ghostfixture check` |

## Honest limits

- **A fixture is not guaranteed to run.** The closure is
  static and parse-level (Python via `ast`, JS/TS via import
  patterns, Go via package resolution, C/C++ via preprocessor
  `#include` directives, other languages not computed in v0.1
  and labelled as such in the manifest). For C/C++, only the
  quoted include form is resolved (against the including
  file's directory, then the project root); angle-bracket
  includes and macro includes are recorded as external
  references, since their search path is a build flag this
  tool never sees.
  Go resolution needs a `go.mod`: a module-local import path
  pulls in every non-test `.go` file of that package
  directory (`*_test.go` files stay out), and a directory
  with its own `go.mod` is a separate nested module whose
  imports do not resolve here. Dynamic imports, string-built
  module paths, reflection, and plugin loaders are invisible
  to it. A fixture may still need packages, data files, or
  services the bundle never referenced. GhostFixture installs
  nothing and runs nothing.
- **Flagged is a conservative net, not a proof.** An
  unflagged file can still contain a secret in a shape the
  scanner does not know. The correct reading of a clean run is
  "no flagged shapes found", never "secret-free".
- **Copies are originals, at the project's current state.**
  If the project changed after the bundle was exported, the
  fixture holds the newer bytes. The manifest records the
  bundle manifest hash so the pairing stays auditable, and
  drift is now named, not just implied: bundle entries at
  mode `full` are byte-compared against the bundle's
  recorded per-file hash, and any copied file that differs
  is listed under `drift` in the manifest and under a
  drift warning in `FIXTURE.md`. Other modes store sliced
  text rather than the file, so no drift claim is made for
  them either way.
- **Fixture proves nothing about behaviour.** It materialises
  the context a task ran against. Whether the slice was
  sufficient is GhostVerify's question; whether a bug
  reproduces is yours.

## Examples

See `examples/` for a walkthrough with a demo project and a
demo bundle: closure pulling an unreferenced module in, a
flagged file being excluded, and the check round trip.

## License

MIT. Part of the GhostSlice companion suite by Ghost Developer
Studio.

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
