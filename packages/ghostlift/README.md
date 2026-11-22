# GhostLift
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/littlestjames82-sys/ghostlift/actions/workflows/ci.yml/badge.svg)](https://github.com/littlestjames82-sys/ghostlift/actions/workflows/ci.yml/actions)

**Get readable source back from compiled artifacts, so GhostSlice can work on it.**

GhostSlice governs what an agent reads, but it can only read source.
Plenty of real projects have no source left to slice: a production
JavaScript bundle with no repo behind it, a Python deployment that
only ships `.pyc` files, a vendor artifact, a build output that no
longer matches any checkout. GhostLift is the front door for those
projects. It lifts a compiled or minified artifact back into
readable text, labels exactly how it did it, and hands GhostSlice a
project it can scan, heat-map, and slice like any other.

By Ghost Developer Studio. Zero dependencies (Python standard
library only), local-first: no network calls, no telemetry, and
GhostLift never runs the artifacts it lifts. Static analysis only.

Position in the Ghost stack: GhostSlice governs what an agent
*reads*. GhostLift recovers something readable *to* read, when all
that survives is the compiled form. Agent Seatbelt still governs
what an agent *does*.

## Quick start

Requirements: Python 3.11 or newer. There is nothing to install
beyond the checkout itself: no dependencies, no build step, and no
network access at any point.

Run the CLI straight from the checkout:

```bash
# 1. Inspect first: what is this artifact, which tier, can it lift?
PYTHONPATH=src python3 -m ghostlift inspect path/to/bundle.js.map

# Same report as JSON, for scripts and other tools:
PYTHONPATH=src python3 -m ghostlift inspect path/to/module.pyc --json

# 2. Lift a single artifact, or a whole folder of artifacts:
PYTHONPATH=src python3 -m ghostlift lift path/to/bundle.js.map -o lifted/
PYTHONPATH=src python3 -m ghostlift lift path/to/build-output/ -o lifted/
```

If the package is installed, the same commands spell
`ghostlift inspect ...` and `ghostlift lift ...`.

A lift writes two things into the output folder:

```text
lifted/
  manifest.json   # watermark: every file, its tier, its source artifact
  files/          # the recovered (Tier 1) or lifted (Tier 2) source tree
```

The `files/` tree is an ordinary project folder: hand it to
GhostSlice to scan, heat-map, and slice like any other source tree.

Exit codes tell scripts what happened: `inspect` exits `0` when the
artifact is liftable and `1` when it is not (detected but not
liftable, or unrecognised); `lift` exits `0` when at least one file
was lifted and `1` when none was; both exit `2` for a missing path
or another usage error. In a folder lift, artifacts that cannot be
lifted are listed in the manifest's `failures` list, by name, never
silently skipped.

### What the core CLI lifts today

| Artifact | Tier | Core lift? |
| --- | --- | --- |
| Source map (`.js.map` / `.css.map`, version 3) with `sourcesContent` | 1, exact | Yes, byte for byte |
| Python bytecode (`.pyc`, CPython 3.11 / 3.12 / 3.13 layouts only) | 2, structured | Yes, structure and signatures |
| Minified JavaScript (`.js`) | 2, structured | Yes: beautified, with function boundaries recovered. A tested example beautifier also ships in `examples/js_lift_demo.py`. |
| Other bytecode (`.class`, `.dex`, `.dll`, `.wasm`, native binaries) | 3, outline | No: detected and reported by `inspect` only in v0.1 |
| Anything else | none | Reported as unrecognised |

An artifact outside the supported `.pyc` layouts is refused by
name, not guessed at. See "Honest limits" below.

## The three tiers

Not all recovery is equal, and GhostLift never pretends it is.
Every lifted file is labelled with one of three tiers.

### Tier 1: exact recovery

The original source comes back byte for byte, because the artifact
carries it. The main case is a JavaScript source map
(`bundle.js.map`) whose `sourcesContent` holds the original files.

- What you get: the original files, unchanged.
- How to trust it: the recovered text can be compared exactly
  against the source map content, and the tests do exactly that.
- Limit: if a source map has no `sourcesContent`, there is nothing
  exact to recover from it, and GhostLift says so instead of
  guessing.

### Tier 2: structured lift

The artifact is rebuilt into readable, structured source, but it is
a reconstruction, not the original. Two cases in v0.1:

- Python `.pyc` files, lifted back toward Python source structure
  using the bytecode's own code objects (names, arguments, nesting).
- Minified JavaScript, beautified back into indented, line-broken
  form with its function boundaries recovered. Variable names that
  minification destroyed stay destroyed: a one-letter name in the
  bundle is a one-letter name in the lift. The core CLI lifts `.js`
  artifacts directly (`src/ghostlift/jslift.py`: regex-literal aware
  beautify, function boundaries read from code with strings and
  comments masked out); the tested example implementation under
  `examples/` (`js_lift_demo.py`) remains as a standalone reference.

What you get is faithful to what the artifact contains, and nothing
more. Comments the compiler dropped do not come back. Names the
minifier renamed do not come back.

### Tier 3: labelled pseudo-source outline

For artifacts where a full reconstruction is not realistic, GhostLift
produces an outline instead: the names, signatures, and structure of
what is inside, rendered as pseudo-source and labelled as an
outline. An agent reading an outline knows the shape of the code,
not its behaviour in detail.

An outline is useful for orientation and for GhostSlice signatures
mode. It must never be passed off as recovered source, and the
watermark (below) is what stops that from happening by accident.

## The watermark

Every lifted file is watermarked as lifted, with its tier. The
watermark lives in the output manifest (`manifest.json`), which is
part of every lift: each file entry records `lifted`, its `tier`
and tier name, the source artifact it came from and that artifact's
sha256, and how it was reconstructed (`exact`, `structured`, or
`outline`). The manifest also carries a plain-words note that lifted
files are not original source.

Lifted text also labels itself. A reconstructed Python file says it
is a lifted reconstruction in its own header, and the example
lifters under `examples/` stamp their standalone output with an
in-file comment of this shape:

```text
# ghostlift: lifted tier=2 source=pyc reconstruction=structured
/* ghostlift: lifted tier=1 source=sourcemap reconstruction=exact */
```

The watermark is a hard rule, not a decoration:

- A lifted file with no watermark is a bug.
- Do not strip watermarks from lifted files you share onward. The
  next reader, human or agent, deserves to know they are reading a
  reconstruction.
- Downstream tools in the suite read the watermark to treat lifted
  context differently from original source.

## Right to inspect: whose code you may lift

GhostLift is for code you own or have the right to inspect:

- Your own projects, including ones where you lost the source and
  only the build survives.
- Code you are licensed or contracted to review, audit, migrate, or
  interoperate with.
- Open-source artifacts, within their licence terms.

It is not a tool for getting around a licence, a paywall, DRM, or
someone else's ownership of their code. Lifting an artifact does
not change who owns it or what licence applies to it: the recovered
text inherits the rights and limits of the original. If you would
not have the right to read the source, you do not have the right to
lift the artifact. That call is yours, and this README states it in
plain words so there is no confusion about what the tool is for.

## Safety rules

- **Static only.** GhostLift reads artifacts as data. It never
  imports, executes, or installs the code it lifts.
- **Untrusted bytecode is untrusted.** Python `.pyc` payloads are
  parsed as data by a limited, defensive reader, never by blindly
  unmarshalling and never by importing them: a parser problem must
  produce a refused lift, never code execution. The example outline
  code under `examples/` follows the same rule with its own small
  reader, and still says, where it matters, to only lift bytecode
  you produced yourself or have the right to inspect.
- **Local only.** Your artifacts never leave the machine. There is
  no upload, no cloud decompiler, no telemetry.

## What is in this checkout

- `src/ghostlift/` - the core (tiers, lifting, watermarking, CLI).
- `examples/` - runnable examples per tier: a source-map demo with
  its originals, a minified-JS lift demo, and a `.pyc` outline demo
  that compiles its sample module at run time.
- `tests/` - fixture tests plus tier tests: source-map exact
  recovery, `.pyc` round-trip signatures (fixtures generated at
  test time, because a `.pyc` only matches one Python version),
  minified-JS beautify and function boundaries, and watermark
  presence on lifted output.

## Worked example

Recover the originals bundled in the example source map:

```bash
PYTHONPATH=src python3 -m ghostlift inspect examples/sourcemap_demo/bundle.js.map
PYTHONPATH=src python3 -m ghostlift lift examples/sourcemap_demo/bundle.js.map -o /tmp/lifted
cat /tmp/lifted/manifest.json
ls /tmp/lifted/files/src/   # greeting.js and math.js, byte-exact originals
```

More runnable demos, one per tier, live in `examples/`; see
`examples/README.md` for what each one shows and its limits.

## Run the tests

```bash
PYTHONPATH=src python3 -m pytest tests -q
```

## Honest limits

- A general-purpose decompiler for arbitrary native binaries is
  out of scope. GhostLift covers the artifact kinds named above.
- Tier 2 and Tier 3 output is a reconstruction and an outline.
  Both are labelled, both can be wrong in details the artifact no
  longer contains, and neither should be treated as the original
  source for legal or archival purposes.
- Recovery quality depends on the artifact. A stripped, obfuscated
  bundle with no source map gives GhostLift very little to work
  with, and the output will show it.

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
