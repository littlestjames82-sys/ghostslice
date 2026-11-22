# GhostConvert
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/littlestjames82-sys/ghostconvert/actions/workflows/ci.yml/badge.svg)](https://github.com/littlestjames82-sys/ghostconvert/actions/workflows/ci.yml/actions)

GhostConvert takes a finished [GhostSlice](https://github.com/littlestjames82-sys/ghostslice)
bundle and re-expresses it in the instruction formats other coding
agents actually read: an `AGENTS.md`, Cursor rules, GitHub Copilot
instructions, or one plain prompt file.

GhostSlice decides what an agent reads. GhostConvert only changes the
shape that reading arrives in. It makes no slicing decisions of its
own, never re-slices, and never edits the bundle. Anything a target
format cannot carry from the Slice manifest is named in a `LOSSES.md`
file shipped with the output, instead of being dropped silently.

Zero dependencies, Python standard library only, runs fully locally.

## Install

```sh
pip install .
```

That puts a `ghostconvert` command on your PATH. From a source
checkout without installing:

```sh
PYTHONPATH=src python3 -m ghostconvert --help
```

Requires Python 3.10 or newer.

## Quick start

A bundle is a directory (conventionally named `.claude_context`)
holding `manifest.json`, `PROMPT.md`, and a `files/` folder. That
directory is the only input GhostConvert takes.

```sh
# See what a bundle holds, writing nothing
ghostconvert inspect path/to/.claude_context

# Convert it for tools that read AGENTS.md
ghostconvert convert path/to/.claude_context --to agents -o out/agents

# Convert it to every target at once (one subdirectory per target)
ghostconvert convert path/to/.claude_context --to all -o out/all

# Audit a converted output against its bundle, writing nothing
ghostconvert verify path/to/.claude_context out/agents --to agents
```

No bundle of your own yet? Try the bundled sample (see
`examples/README.md` for the full walkthrough):

```sh
PYTHONPATH=src python3 -m ghostconvert inspect examples/sample_bundle
PYTHONPATH=src python3 -m ghostconvert convert \
  examples/sample_bundle --to agents -o /tmp/ghostconvert-demo
```

The first command prints the sample's census (`Files: 7 (5 with
bodies, 1 emptied by GhostSlice, 1 excluded)`). The second writes
`AGENTS.md` and `LOSSES.md` to the output directory and prints each
loss category it recorded, for example:

```text
[agents] 5 file(s) converted -> /tmp/ghostconvert-demo
  wrote AGENTS.md
  wrote LOSSES.md
  losses: 5 named in LOSSES.md (Excluded files (no body in any target), ...)
```

Then read the output's `LOSSES.md` before handing the artifact to an
agent: it is the list of what that agent will not see.

## The four targets

| Target | Artifact written | Notes |
|---|---|---|
| `agents` | `AGENTS.md` | One document, one section per file, body in a fenced block |
| `cursor` | `.cursor/rules/*.mdc` | One rule file per top-level directory, with frontmatter (description, globs, alwaysApply) |
| `copilot` | `.github/copilot-instructions.md` | Same section discipline as `agents` |
| `generic` | `prompt.md` | Plain concatenation with `# File:` headers, closest to Slice's own `PROMPT.md` |

`ghostconvert targets` lists the same table from the CLI.

Which one should you pick? Match the tool that will read the context:
`agents` for tools that follow the AGENTS.md convention, `cursor`
when the context will live in a Cursor project, `copilot` for GitHub
Copilot, and `generic` when you just need one plain file to paste or
attach anywhere else. When in doubt, convert `--to all`, compare the
four `LOSSES.md` notes, and keep the target whose losses you can
accept.

Every conversion also writes `LOSSES.md` into the output directory
(one per target subdirectory when converting `--to all`).

## How conversion works

- The bundle's `manifest.json` is the authority for file order, slice
  modes, language, token estimates, and hashes. Converted artifacts
  keep the manifest's file order exactly.
- File bodies come from the bundle's `files/` directory, byte for
  byte as Slice wrote them. If a `files/` entry is missing, the body
  is recovered from the bundle's `PROMPT.md` instead. If neither has
  it, the file is converted as absent and named in `LOSSES.md`.
- Each file's section header carries its slice mode, for example
  `## File: src/util.py (mode: signatures)`. A file marked signatures,
  symbols, interfaces, or strip-tests is not the full source, and the
  header is the warning.
- Manifest paths that would escape the bundle directory are skipped
  and named in `LOSSES.md`. They are never followed.

## Verifying a conversion

`ghostconvert verify <bundle> <output> --to <target>` (or `--to all`,
with one subdirectory per target under `<output>`) audits output that
has left the tool: copied, committed, or regenerated elsewhere. It
re-renders the expected artifacts in memory and compares them byte
for byte with what is on disk, writing nothing to either the bundle
or the output. On a mismatch it names the concrete divergence where
it can: a missing artifact, a missing or duplicated section, a body
that is no longer verbatim, sections out of manifest order, an
excluded file appearing as a section, a stale or edited `LOSSES.md`,
or a Cursor rule file no conversion of this bundle produced. Verify
judges conversion fidelity only; it makes no slicing decisions and
does not judge whether the bundle itself was sufficient.

## The losses note

Formats like `AGENTS.md` are single prose documents. They have nowhere
to put per-file sha256 hashes, per-file token counts, redaction
records, symbol lists, or the list of files Slice excluded. Hand
conversion drops all of that without a word. GhostConvert writes it
down instead: each `LOSSES.md` names, as applicable, the excluded
files, the hashes and token estimates that did not carry, redaction
metadata, mode reasons, package groupings, files whose bodies were not
found, skipped paths, and format-specific losses (for Cursor, the
regrouping into rule files is itself named as a loss). Two distinctions
are kept exact in the note: a file Slice emptied on purpose (an empty
slice in the manifest) is listed separately from a file whose body is
genuinely missing, and a slice mode GhostConvert does not recognize is
flagged as unrecognized while its label is still carried verbatim. A
conversion that lost nothing says so in the note rather than omitting
the file.

## Safety rules

- The source bundle is read only. Conversion hashes nothing into it
  and writes nothing into it; the test suite verifies byte for byte
  that a bundle is unchanged after every conversion.
- Output goes to a directory you name with `-o`. It must not be the
  bundle directory or inside it; the run refuses and exits 2.
- Existing files at the exact artifact paths are overwritten only
  with `--force`. Without it the run refuses, names the collision,
  and writes nothing.
- A malformed manifest, or a bundle with no readable file bodies at
  all, exits 2 (could not convert) rather than producing a partial
  silent success.
- Exit codes: 0 means converted (losses, if any, are listed in
  `LOSSES.md` and are not failures). 1 means `verify` found an output
  that does not match its bundle. 2 means a bad bundle or bad
  arguments.

## Troubleshooting

All of these exit 2 and write nothing (or nothing new); none of them
modifies the source bundle.

| Symptom | Cause and fix |
|---|---|
| `bundle directory not found` or `no manifest.json in bundle` | The path given is not a GhostSlice bundle. Pass the bundle directory itself (the folder containing `manifest.json`), not the project root or a file inside the bundle. |
| `manifest.json is unreadable or malformed` / `has no 'files' list` | The manifest is not the documented Slice shape. Re-export the bundle with GhostSlice instead of hand-editing the manifest. |
| `bundle has no readable file bodies` | Both `files/` and `PROMPT.md` are empty or missing, so there is nothing to convert. Re-export the bundle. |
| `output directory must not be the bundle directory or inside it` | Pick an `-o` path outside the bundle; the bundle is read-only by design. |
| `refusing to overwrite existing file(s)` | An artifact already exists at the output path. Move it, pick a different `-o`, or re-run with `--force` to replace exactly those artifact files. |
| A file you expected is missing from the artifact | Check the output's `LOSSES.md` first: the file was likely excluded by Slice, emptied by Slice on purpose, or had no readable body. All three are named there, and the fix (if any) is at Slice time, not convert time. |
| A slice mode is flagged `unrecognized` | The manifest carries a mode label this version of GhostConvert does not know. The label is still carried verbatim in the section headers; only the source bundle knows what the mode means. |

## Honest limits

- Converted context is still sliced context. GhostConvert re-expresses
  what Slice decided; it cannot restore code Slice cut. Verify the
  source bundle (for example with `ghostslice check`) when you need
  guarantees, because converted output carries no hashes to check
  against.
- Cursor grouping by top-level directory is a judgement call,
  recorded as a loss. The receiving tool sees rule files Slice never
  made.
- Target format shapes are pinned as written by this version (Cursor
  `.mdc` frontmatter and the Copilot instructions path as of October
  2026). If those tools change their conventions, that is a
  GhostConvert version bump, not a silent edit.
- No reverse conversion. There is no path from a converted artifact
  back to a bundle, and no round-trip guarantee.
- Out of scope for v0.1: re-slicing or rescanning the project, merging
  output into a live project's existing instruction files (that step
  is yours), targets beyond the four above, and any network, account,
  or telemetry features. There are none.

## Development

```sh
PYTHONPATH=src python3 -m pytest tests -q
```

Always name the `tests` directory: a bare `pytest` run also collects
`examples/sample_project/tests/`, which is a fixture project for the
examples, not part of this suite, and fails collection on purpose of
its layout.

The test suite is black-box: it drives the CLI as a subprocess
(discovered via `$GHOSTCONVERT_CMD`, PATH, or `python -m ghostconvert`
with `PYTHONPATH=src`) and builds its golden bundle with the real
GhostSlice. See `REPORT_B.md` for the latest run and findings, and
`PLAN.md` for the design.

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
