# GhostPrimer
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/littlestjames82-sys/ghostprimer/actions/workflows/ci.yml/badge.svg)](https://github.com/littlestjames82-sys/ghostprimer/actions/workflows/ci.yml/actions)

The first-session starter pack for a project.

GhostSlice slices context for a known task. GhostPrimer is for before
there is a task: it builds the small bundle a brand new agent session,
or a new hire driving one, should read first to get oriented: what the
project is, where it starts, the handful of files everything else
leans on, and the project memory that is already written down.

One pack, sized to be read whole, with an honest list of what it left
out.

## The 30-second version

- Run `ghostprimer doctor <project>` to preview, then
  `ghostprimer build <project> -o <bundle>` to build.
- Read `<bundle>/PRIMER.md` top to bottom. That one file is the pack.
- The pack is extractive only: text is copied or structurally derived
  from project files, never written by a model about your code.
- It is a starter, not the project. Files it skipped, and why, are
  named in the pack itself (see "What gets left out and why" below).
- Nothing outside the project root is read, except a GhostRecall
  bundle or GhostHandoff pack you pass in explicitly. Your assistant's
  private memory is never read (see "Hard rules").

## Quickstart

Requires Python 3.11 or newer. Standard library only: no dependencies
to install, no network, no account.

If the `ghostprimer` command is installed:

```bash
ghostprimer doctor path/to/project                 # read-only preview
ghostprimer build path/to/project -o /tmp/primer   # build the pack
ghostprimer check /tmp/primer                      # verify it (optional)
```

From a source checkout, without installing, the same commands are:

```bash
PYTHONPATH=src python3 -m ghostprimer doctor path/to/project
PYTHONPATH=src python3 -m ghostprimer build path/to/project -o /tmp/primer
PYTHONPATH=src python3 -m ghostprimer check /tmp/primer
```

Then read `/tmp/primer/PRIMER.md`. A guided tour on a tiny sample
project is in [examples/README.md](examples/README.md).

### What a build writes

A bundle is a plain folder, not an archive:

| Path | What it is |
|---|---|
| `PRIMER.md` | The pack itself: facts, start-here list, README extract, code slice, memory primer, not-included list, and limits. Read this. |
| `manifest.json` | The audit record: every included file and memory item with token counts, sha256, slice mode, and provenance, plus totals and the omissions. |
| `files/<relative path>` | The sliced code files, at their original relative paths, exactly as recorded in the manifest. |

The project being primed is never modified. Deleting the bundle
folder undoes everything.

### A real example

Building the sample project in `examples/sample_project/`:

```text
$ ghostprimer build examples/sample_project -o /tmp/demo-primer
GhostPrimer bundle: /tmp/demo-primer
  files: 3 (114 sliced tokens, was 167)
  memory: 3 items via fallback (109 tokens)
  not included: 1, blocked: 0
```

The pack contains the two entry points (`src/demoapp/__init__.py`,
`src/demoapp/main.py`) and `greeter.py`, the module the entry point
imports, all at signature depth. The one omission is named in the
pack: `src/demoapp/unused.py`, left out because nothing imports it
and it is not an entry point. Small numbers, same shape as a real
project: a few files in, everything else accounted for.

## What goes in the pack

- **Project facts, extracted**: name, version, description, entry
  points, language mix, and top-level layout, read from the project's
  own metadata (`pyproject.toml`, `package.json`) and tree. A field
  that cannot be found is recorded as "not found". Nothing is invented.
- **A code starter slice**: entry points first, then the highest
  fan-in modules (the files the rest of the project imports most).
  Each file is included at signature depth if it fits the remaining
  code budget, otherwise at outline depth, otherwise not at all.
  Entry points are the exception: they are never dropped below
  outline, and if that breaks the budget, the budget is reported as
  unmet instead (see "Budgets").
- **A README extract**: the title, the headings, and the first
  paragraph under each heading, capped. If the README trips the
  secrets guard, the extract is blocked and recorded, not included.
- **A memory primer**: standing rules and decisions from
  project-local files. When a GhostRecall bundle is supplied with
  `--recall-bundle`, its current items are used verbatim with their
  provenance; superseded, excluded, and blocked items are never
  carried in. Otherwise a shallow fallback pass reads the well-known
  files (`AGENTS.md`, `CLAUDE.md`, `DECISIONS.md`, `docs/decisions/`,
  the latest `CHANGELOG.md` entry only, `CONTRIBUTING.md`, `PLAN.md`,
  roadmap files): headings plus capped extracts, each item with file
  and line provenance. The manifest records which path produced the
  memory section (`memory_path`: `recall-bundle` or `fallback`).
- **An optional previous-session handoff**: when a GhostHandoff pack
  is supplied with `--handoff-pack`, its recorded state, open loops,
  and next steps are added as a separately labelled section. The
  input may be the pack directory or its `handoff.json` file.
  Handoff items pass through the same secret scan and compete for
  the same memory budget share as other memory; the manifest records
  the input as `handoff_input`.

## What gets left out and why

Leaving things out is the point of a starter pack, so every omission
in the starter selection is named, with a reason, in the `Not
included` section of `PRIMER.md` and in `manifest.json` under
`not_included` (blocked items are under `memory_blocked` and are
also listed in `PRIMER.md`, marked BLOCKED).

| Reason recorded | What it means |
|---|---|
| `unreferenced: no project file imports it and it is not an entry point` | A Python or JS/TS file with fan-in 0. The starter slice is entry points plus depended-on modules, so it is left for a later, task-specific slice. |
| `code budget spent` | A candidate file that fit at neither signature nor outline depth within the remaining code budget. |
| `memory budget share spent` | A memory item dropped because memory had already used its capped share of the budget. |
| `secret-shaped literal found (...); excluded` | A code file excluded by the secrets guard. Only the shape names are recorded, never the value. |
| `BLOCKED, secret-shaped literal found (...)` | A memory or handoff item blocked by the secrets guard. Only its path, title, and the shape names are recorded. |
| `BLOCKED, secret-shaped literal in README` | The README extract was blocked by the secrets guard; no part of it is included. |

Scope of that list, stated plainly: it covers the starter selection
(candidate code files, memory items, handoff items, and the README
extract). It is not an inventory of every path in the repository.
Top-level test directories (`tests/`, `test/`), skipped directories such as
`.git` and `node_modules`, non-code files, and anything else outside
the starter selection are simply not candidates, and are not listed
one by one.

## Budgets

- Default budget: 6,000 estimated tokens for the whole pack
  (`--budget N` to change it).
- Memory is capped at 40 percent of the budget by default, so memory
  cannot crowd out code. One exception, by design: the first memory
  item is always kept, even if it alone exceeds the share.
- Code gets what memory did not use. Files are considered in
  candidate order (entry points, then fan-in rank) and downgraded
  per file: signatures, then outline, then excluded.
- If the budget cannot be met, the bundle is still written, entry
  points are kept at outline, and the shortfall is reported in the
  build output, in `PRIMER.md`, and as `budget_unmet` in the
  manifest. It is never hidden.
- Token counts are estimates (see "Honest limits"), and the
  estimator in use is stamped in the manifest as `token_method`.

## Hard rules

- **Project-local sources only, checked by resolved path.** Every
  code file and project-memory source is resolved (symlinks
  included) and must resolve inside the project root. Anything
  resolving outside is refused by that path check, not by
  convention. The only inputs that may live outside the root are a
  GhostRecall bundle (`--recall-bundle`) and a GhostHandoff pack
  (`--handoff-pack`), and only because you supplied them explicitly;
  a handoff pack that names a different project is refused.
- **Private memory is never read.** The user's own assistant memory
  (`~/MEMORY.md` and `~/memory/`) is excluded by rule. The check is
  on the resolved path: a source that resolves into either location
  is refused even if a project file points straight at it, and a
  project root that is itself one of those locations is refused.
  A supplied GhostHandoff pack in a private memory location is
  refused the same way. A supplied GhostRecall bundle is different
  by design: it is an explicit input whose current items Primer
  takes verbatim from the bundle itself, while any item content
  Primer instead fetches from a project source path goes through
  the same resolved-path check as any other source.
  Primer primes from the project's record, not the assistant's.
  Note what this rule does and does not cover: it governs what
  Primer reads as project, code, and memory sources; the bundle
  output folder is wherever you tell `-o` to write.
- **Extractive only.** No model is called and no prose is generated
  about your code. The only written text is fixed template framing,
  marked as template in `PRIMER.md` and listed in the manifest.
  Everything else is copied or structurally derived from project
  files: metadata fields, signatures, docstring first lines,
  headings, verbatim extracts.
- **Secrets guard.** Memory extracts, handoff items, and code files
  are scanned for secret-shaped literals. A flagged memory or
  handoff item is blocked and recorded, never included; a flagged
  code file is excluded and named. A clean scan means none of the
  recognised shapes were found; it is not a guarantee that a file
  holds no secrets.
- **Local only.** Python standard library only. No network, no
  accounts, no telemetry. Primer never runs your project and never
  modifies it; it produces reading material only.

## Commands

```bash
ghostprimer build <project> -o <bundle> [--budget N] [--recall-bundle <dir>] [--handoff-pack <dir-or-handoff.json>] [--task "..."] [--json]
ghostprimer check <bundle>
ghostprimer stale <bundle> [--project <dir>]
ghostprimer doctor <project>
ghostprimer mcp
```

Run `ghostprimer <command> --help` for the full, current option
help of any command.

- `build` writes `PRIMER.md`, `manifest.json`, and `files/` into the
  bundle folder. `--task "..."` is only a label, recorded verbatim
  in the manifest; selection is task-free by design and does not
  change with it. `--json` prints the build summary as one JSON
  object instead of text lines. Exit 0 on success, 2 when the
  project or a supplied pack is refused.
- `check` verifies a bundle against its manifest: file hashes and
  totals recomputed, `PRIMER.md` verified against its recorded
  hash, every recorded memory item's source path confirmed
  inside the project root, and no memory item sourced from the
  excluded private locations. Prints a JSON report. Exit 0 pass, 1 fail with
  reasons, 2 could not check.
- `stale` reports whether a bundle still matches its project. The
  bundle must pass `check` first (staleness is only reported for a
  verified bundle); then every recorded source is re-read, with its
  path re-verified inside the project root before it is opened, and
  re-sliced at the recorded mode for comparison against the recorded
  hash. It reports changed, missing, and refused sources, project
  facts that drifted (name, version, description), new entry points
  the pack does not know, and memory sources that are gone. Exit 0
  fresh, 1 stale with the differences listed, 2 could not check.
  `--project` compares against a given tree instead of the root
  recorded in the manifest, for projects that moved.
- `doctor` is read-only: extracted facts, entry points found, which
  primer sources exist or are missing, whether a Recall bundle was
  found at a conventional location, the estimator in use, and
  whether GhostSlice's estimator is available. Prints a JSON
  report. Exit 0 if the project can be primed, 2 otherwise. Run it
  first on an unfamiliar project; it predicts the shape of a build
  but does not report the budget outcome.
- `mcp` serves `primer_build`, `primer_check`, and `primer_stale` over stdio
  (newline-delimited JSON-RPC) with capped summary payloads and no
  raw file bodies by default. No network listener is opened.

The bundle follows the GhostSlice bundle schema (per-file token
counts and sha256, integer top-level totals, token method recorded),
so a Primer bundle can also be validated with `ghostslice check`
when GhostSlice is installed or a sibling checkout is present and
the bundle was built with GhostSlice's estimator (see the fallback
note under "Honest limits").

## Honest limits

- The shallow memory fallback is deliberately dumb. Headings plus
  capped extracts will miss decisions buried mid-paragraph. That is
  exactly why the Recall bundle path exists; the manifest records
  which path produced the memory section.
- Fan-in is a proxy for importance, not importance itself. A
  generated or vendored file can rank high; the not-included list
  keeps every starter choice auditable.
- Fan-in itself is exact for Python (real AST) and parser-lite for
  JS/TS: relative `import`, `export ... from`, `require`, and
  dynamic `import()` specifiers are resolved statically, including
  extensionless imports, directory index files, and `.js`
  specifiers that name `.ts` sources. Comments and string contents
  are masked before scanning, so import-shaped text inside them
  never counts. Languages other than Python and JS/TS get no import
  graph yet: their files rank after files with known fan-in, and
  the manifest records their `fan_in` as 0 with `fan_in_method`
  "none", meaning unknown, not zero. Every file entry records its
  `fan_in_method` ("ast", "parser-lite", or "none") next to the
  count.
- Code slicing depth varies by language the same way: Python is
  sliced with the real AST, JS/TS with a parser-lite pass, and other
  languages get a head excerpt. Every file entry records its slice
  mode and confidence label in the manifest.
- Extractive facts can still be wrong when the project record is
  wrong: a stale README, a changelog that lies. Every memory item
  carries provenance so a reader can check the source in one hop.
- Token counts are estimates, not exact tokenizer counts, and the
  estimator in use is stamped in the manifest. When GhostSlice is
  not available, a documented chars/4 fallback estimator is used
  instead; bundles built on the fallback carry that method string
  and will not reproduce under `ghostslice check`. `doctor` reports
  which estimator a build on this machine would use.

- Staleness is stated about the pack, and the pack is the slices: a
  source edit that leaves the recorded slice unchanged (a comment
  under signatures mode, say) is not detected by `stale`. Memory
  freshness is weaker still: `stale` verifies each memory source
  still exists and lists sources whose mtime is newer than the build,
  but it cannot prove a memory file's content is unchanged, and it
  says so by keeping the mtime list informational, never a verdict.

## Where it sits

Primer is the front door. After session one, per-task work belongs
to GhostSlice (code) and GhostRecall (memory), GhostVerify checks
the bundle was enough, and GhostAtlas remains the full map for
humans. GhostHandoff can close a session, and a later Primer build
can carry that pack's recorded state, open loops, and next steps
into the next session when the pack is supplied explicitly. Primer
does not replace any of them, does not set anything up, and never
runs your project.

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
