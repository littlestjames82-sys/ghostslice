# GhostDeps
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/littlestjames82-sys/ghostdeps/actions/workflows/ci.yml/badge.svg)](https://github.com/littlestjames82-sys/ghostdeps/actions/workflows/ci.yml/actions)

GhostDeps packs what a project depends on into a short brief an agent
(or a person) can read before touching the code: what the project
declares, what the code actually imports, where those two lists
disagree, and which versions the local files record.

It is the dependency companion to GhostSlice. Slice packs the code;
Deps packs the dependency facts around the code; the agent starts a
session knowing both.

## Quick start

Requires Python 3.11 or newer. GhostDeps has no dependencies of its
own: it uses only the Python standard library.

Install it as a command:

```
pip install .
ghostdeps --help
```

Or run it from a source checkout without installing:

```
PYTHONPATH=src python3 -m ghostdeps --help
```

Then, from anywhere:

```
ghostdeps pack path/to/project -o out
ghostdeps doctor path/to/project
```

Both commands take the project directory as their one required
argument. Start with the bundled examples in `examples/` if you want
to see a pack before running it on a real project: they are small
projects with gaps planted on purpose, and `examples/README.md` walks
through what to look for in the output.

## Which command do I want?

| Command | What it does | Writes files? |
| --- | --- | --- |
| `ghostdeps pack PROJECT [-o OUT] [--json]` | Builds the full pack (see below). With `--json`, also prints the manifest JSON to stdout. | Yes: `DEPS.md` and `deps-manifest.json` in `OUT` (default: `PROJECT/deps-pack`) |
| `ghostdeps doctor PROJECT [--json]` | Reports which manifests and lockfiles were found, which were parsed versus detected only, how imports were extracted per ecosystem, and the summary counts. Good first step on an unfamiliar tree, and the usual CI entry point. | No |

## What a pack contains

`pack` writes two files with the same facts in two shapes:

- `DEPS.md`, a human report with four sections: declared and used,
  declared not imported, imported not declared, and pins as recorded.
- `deps-manifest.json`, the same facts in machine-readable form, with
  the evidence for each entry: which manifest declares it, which
  lockfile pins it, and which source files import it. Manifest
  evidence is also grouped by holding directory in `source_groups`,
  which makes nested monorepo sources easier to attribute.

Reading the four sections:

- **Declared and imported** is the confirmed overlap: a declaration in
  a parsed manifest, and at least one scanned import of that name.
- **Declared, no import found** records only that no import was found
  in the scanned code. It is information, not a failure (see the trust
  rules below), and it does not affect the exit code.
- **Imported, no declaration found** names the files that import each
  package. This is the one section that counts as a finding: it sets
  exit code 1.
- **Version pins as recorded** lists exact versions exactly as the
  local manifest or lockfile writes them. It makes no comparison
  against anything outside the tree.

## What it reads

Per ecosystem:

- Python: `pyproject.toml` (project dependencies, optional
  dependencies, dependency groups) and `requirements*.txt` files.
  `setup.py` and `setup.cfg` are recorded as present but not parsed.
- JavaScript and TypeScript: `package.json` (dependencies,
  devDependencies, peerDependencies, optionalDependencies) and
  `package-lock.json` at summary level: lockfile version and root
  package pins, never the whole file.
- Rust: `Cargo.toml` dependency tables, with workspace members noted,
  and `Cargo.lock` at summary level: local (source-less) packages are
  the project itself and are excluded, packages a local package lists
  as dependencies are direct pins, and every other recorded package
  is a transitive pin recorded compactly. Checksums and the full
  dependency graph are never reproduced.
- Anything else it recognises (Gemfile, go.mod, composer.json,
  Pipfile) is listed as detected, not parsed. Nothing is silently
  skipped.

Imports are extracted from the code and cross-referenced against the
declarations. Python imports come from the real `ast` parser.
JavaScript and TypeScript imports come from pattern matching over
`import`, `export ... from`, and `require()` statements, and every
report labels that side parser-lite. Import names are matched to
distribution names with a small built-in table for the common
mismatches (PIL is Pillow, yaml is PyYAML, cv2 is opencv-python,
sklearn is scikit-learn) plus normalisation of case and separators.
Standard library modules and files inside the project itself are
classified separately and are never reported as missing declarations.
The import scanner honours `.gitignore` files in the tree and the
`ignore` list in a root `.ghostslice.json`; files it skips under those
rules are listed in the manifest under `import_scan`. Manifest and
lockfile discovery is not filtered by those rules, so dependency
evidence is not hidden just because a source directory is ignored.

## The trust rules

- **Local only, no network, ever.** There is no code path that opens
  a socket. No registry lookups, no advisory lookups, no update
  checks.
- **Evidence only.** A declared package with no import found is
  reported in exactly those words, with the common innocent
  explanations listed next to it (command line entry points, plugins,
  type-only or runtime loading). An imported package with no
  declaration names the files that import it and notes the common
  innocent causes. GhostDeps never grades a dependency, never scores
  a project, and never tells you to add or remove anything. A human
  decides what a gap means.
- **Versions as recorded.** A version in the report is the version
  written in your local manifest or lockfile. Nothing is compared
  against anything outside the tree.
- **Read-only.** GhostDeps never edits a manifest, never installs or
  removes a package, and never rewrites a lockfile. The only files
  `pack` writes are the two pack files in the output directory.

## Exit codes

Both `pack` and `doctor` use the same codes, so either works in CI:

| Code | Meaning |
| --- | --- |
| 0 | The pack built and there are no findings. |
| 1 | Findings present. Imported-not-declared is a finding. Declared but not imported is information, not a failure. |
| 2 | Could not build a pack, because no manifests were found or a manifest failed to parse. A project with no manifests is reported as having none; that is an answer, not a crash. |

## Common questions

**A package I know is used shows up as "declared, no import found".
Is something wrong?**
Not necessarily, and GhostDeps does not claim otherwise. Plugins,
command line entry points, type-only packages, and anything loaded by
name at runtime all legitimately have no static import to find. The
entry is a lead for a human to check, which is why it never changes
the exit code.

**An imported package shows up as having no declaration. Why?**
Common causes are listed next to the entry in the report: the package
may arrive through another declared package, be a sibling package in
a monorepo, or fall outside the small import-name to distribution-name
mapping table. The report names the importing files so you can check.

**GhostDeps found no manifests (exit 2). What now?**
Check that the path points at the project root, and that the tree
actually contains one of the files listed under "What it reads".
Source code alone, with no manifest or lockfile, gives GhostDeps
nothing to cross-reference, so exit 2 with a "none found" report is
the honest answer rather than a crash.

**Will GhostDeps fix the gaps it finds?**
No. Fixing declarations is deliberately out of scope: GhostDeps
reports the gap with its evidence, and a human decides what to do.

## Honest limits

- The import-name to distribution-name mapping is a heuristic table
  plus normalisation. It will miss unusual cases, and unmapped names
  are compared as written.
- Declared-not-imported is a list of leads, not a verdict. Plugins,
  entry points, and dynamically loaded packages all land there with
  no import evidence, which is why the wording stays neutral.
- Parser-lite JavaScript extraction can miss re-exports and computed
  requires. Comment stripping is string-aware, so comment markers in
  quoted strings, template literals, and regex literals do not erase
  the code that follows them, but this is still not a full JavaScript
  parser. It is labelled parser-lite everywhere it is used.
- Lockfiles are read at summary level only. There is no transitive
  resolution, no dependency tree, and no deduplication analysis in
  this version. `Cargo.lock` is summarised the same way as
  `package-lock.json`; a `Cargo.lock` whose shape is not recognised
  is reported as detected, not parsed, rather than guessed at.
- Ecosystems beyond Python, JavaScript/TypeScript, and Rust are
  detected and listed, not parsed, in v0.1.
- Monorepo workspaces are noted, not resolved; sibling packages can
  make an import look undeclared when it is satisfied inside the
  repo, and the report says so next to the entry. Nested manifest
  evidence is grouped by directory, but the cross-reference remains
  project-wide rather than being split per package.

## Layout of a pack

A pack is two files and travels on its own or next to a GhostSlice
bundle. It does not modify Slice bundles, and Slice does not need to
know it exists.

## Status

v0.1, local CLI first. Zero-dependency Python standard library, same
as the rest of the GhostSlice companion suite.

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
