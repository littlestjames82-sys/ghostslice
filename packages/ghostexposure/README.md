# GhostExposure
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/littlestjames82-sys/ghostexposure/actions/workflows/ci.yml/badge.svg)](https://github.com/littlestjames82-sys/ghostexposure/actions/workflows/ci.yml/actions)

**Build a review bundle of only a sensitive surface, with a manifest that accounts for every other file in the tree.**

By Ghost Developer Studio. Working name, v0.1 design per `PLAN.md`. MIT core pattern, local-only, no network calls.

GhostExposure prepares evidence for a code review hand-off. You define the sensitive surface (auth, payments, secrets handling, personal-data paths) as a readable surface pack. GhostExposure scans the whole project, decides for every file whether it is in the bundle or not, records the reason for each decision, and exports a bundle a receiver can verify against its manifest without trusting you.

It stays in evidence language on purpose: *contained, accounted for, verified against the manifest.* It does not use assurance language, because it cannot offer assurance.

## Quick start

Requirements: Python 3.10 or newer. No third-party dependencies. No network access is needed or used.

Install from a checkout of this repo:

```bash
pip install .
ghostexposure --version
ghostexposure --help
```

Sender, in three commands (replace the paths with your own):

```bash
# 1. Preview the in/out decision for every file. Fix conflicts first.
ghostexposure scan ./my-project --surface surfaces/starter.json

# 2. Write the bundle to a new, empty folder.
ghostexposure export ./my-project --surface surfaces/starter.json -o ./my-bundle

# 3. Send the whole bundle folder: files/, manifest.json,
#    exposure.json, EXPOSURE.md, and PROMPT.md.
```

Receiver, in one command:

```bash
ghostexposure verify ./my-bundle
```

If `verify` reports that the bundle on disk matches its manifest and partition, the check it performs has passed. Read the limits below for what that check does and does not cover. Start with `EXPOSURE.md` inside the bundle before reading code.

New to the tool? Work through `examples/` first: `examples/mini_project/` plus `examples/starter-surface.example.json` show the full scan, export, and verify flow on two files you can follow by hand. See `examples/README.md`.

## What this tool is not

- It is **not a security audit**, and it **does not certify** anything. It prepares and proves a bundle. Reviewers review.
- It does not scan for vulnerabilities, look up CVEs, or grade code.
- It does not prove a project is safe, compliant, or certified compliant.
- It cannot prove a sender did not share other files by another channel. It proves what is in this artifact, checked against its manifest, and nothing about what happened in the world outside the artifact.

Coverage limit, stated plainly: a surface pack only matches the signals it lists. GhostExposure does not detect sensitive logic in files with no matching signals. A bundle is "the files this surface pack matched, plus their direct graph context", never "everything sensitive in this project".

## Key terms

Every file in the scanned tree gets exactly one decision. There is no fifth state and no unlisted file.

| Decision | Meaning |
|---|---|
| `surface` | The file matched the surface pack (or was pinned in). It is in the bundle in full. |
| `context` | The file did not match the pack itself, but it imports (calls into) a surface file. It is in the bundle at signatures for Python files, so a receiver can judge callers without receiving unrelated code in full. |
| `out` | The file matched nothing and is not graph context (or was pinned out with no surface match). It is not in the bundle, but it is listed by name in `exposure.json` so its absence is accounted for. |
| `conflict` | The file matched a sensitive pattern **and** a user pin-out. Export stops on a conflict until a person decides. The tool never resolves a conflict silently in either direction. |

Reason codes record *why* a decision was made. They appear in `scan` output and in `exposure.json`:

| Code | Fired when |
|---|---|
| `glob` | A path pattern in the pack matched the file path. |
| `symbol` | A function, class, or name pattern in the pack matched the file text. |
| `import` | An import or dependency pattern in the pack matched the file text. |
| `data` | A field-name pattern shaped like a personal identifier matched the file text. |
| `graph-neighbour` | The file imports a surface file (distance-1 graph context). |
| `user-pinned-in` | The project's `.ghostslice.json` pinned the file in. |
| `user-pinned-out` | The project's `.ghostslice.json` pinned the file out. |

---

## For senders

You are preparing a bundle for an outside reviewer, a contractor, or an agent.

### 1. Write or pick a surface pack

A surface pack is a JSON file you can read top to bottom. Each pattern has an id, a kind, a pattern, and a plain-words reason. Kinds: `glob` (paths), `symbol` (function/class names), `import` (dependencies such as a payments SDK), `data` (field names shaped like personal identifiers).

A minimal pattern looks like this:

```json
{"id": "glob-auth", "kind": "glob", "pattern": "auth/**",
 "reason": "Authentication code is part of the sensitive surface."}
```

The pack itself has `id`, `version`, `date`, `description`, `patterns`, and `coverage_limits`. Inspect any pack before you use it:

```bash
ghostexposure packs --surface <pack.json>
```

`packs` prints the pack summary and every pattern with its reason, so you can confirm the definition matches the review you intend before scanning.

See `examples/starter-surface.example.json` for a starter pack covering auth, payments, config/secrets handling, and personal-data shapes. See `surfaces/starter.json` for the built-in starter pack used when `--surface` is omitted. Copy a pack, edit it, version it. The exact pack you used is written into every export, so the receiver can read the same definition you used.

You can also pin files in or out in the project's `.ghostslice.json`:

```json
{"exposure": {"surface": "starter-auth-payments-data",
              "pinned_in": [],
              "pinned_out": ["docs/internal-notes.md"]}}
```

Pins are globs, matched the same way as pack `glob` patterns. A pin-in puts a file in the bundle even when no pack pattern matches it. A pin-out keeps a file out, unless it also matches a sensitive pattern.

If a file matches a sensitive pattern **and** a pin-out, that is a **conflict**. GhostExposure lists it as a conflict requiring your decision. It never resolves a conflict silently in either direction. To proceed, change the pin or the pack, or export with `--exclude-conflicts`, which leaves conflicted files out and records that explicit choice in `exposure.json`.

### 2. Scan before you export

```bash
ghostexposure scan <project> --surface <pack.json>
ghostexposure scan <project> --surface <pack.json> --json   # machine-readable output
```

Scan prints every file in the tree with its proposed decision and the reason codes that fired (`glob`, `symbol`, `import`, `data`, `graph-neighbour`, `user-pinned-in`, `user-pinned-out`), lists any conflicts, and prints what the pack does not cover.

Read the scan before exporting:

- Every path you expect to see should appear exactly once.
- Check the `conflict` lines first. Scan exits with status `1` when conflicts are present, `0` otherwise, so scripts can gate on it.
- Check a few `out` lines you care about. An `out` decision records a pattern outcome only; it is not a statement about the file's contents in general.

Files and folders the inventory always skips: `.git`, `__pycache__`, `.tox`, `.venv`, `venv`, `node_modules`, `dist`, `build`, `.ghostexposure-cache`, and paths matched by the project's `.gitignore`. If the export folder is placed inside the project, it is excluded from its own inventory.

### 3. Export

```bash
ghostexposure export <project> --surface <pack.json> -o <bundle-folder>
```

The output folder must be new or empty; export stops rather than writing into a non-empty folder. Export also stops (exit status `2`) when unresolved conflicts remain, unless `--exclude-conflicts` is given.

The bundle contains:

| File | What it is |
|---|---|
| `files/` | Surface files in full, direct graph context (callers/callees) at signatures. Nothing else. |
| `manifest.json` | GhostSlice bundle manifest: per file, mode, token estimate, sha256. Validates with `ghostslice check`. |
| `exposure.json` | Per-file in/out decision with reason codes, line numbers recorded for text-pattern matches, a per-pattern coverage record (files each pattern matched, including patterns with no matches recorded), the tree inventory hash, the surface pack used, tool versions, and any redaction records. |
| `EXPOSURE.md` | Human summary: the surface definition in full, counts, the pattern coverage record, estimated token totals, the coverage limits statement, and receiver verification instructions. Read this first. |
| `PROMPT.md` | The exported files concatenated with per-file headings, in the same order and form as in `files/`. A convenience copy for pasting into a review tool; `files/` plus the manifest remain the record that `verify` checks. |

Token totals are **estimates** from GhostSlice's estimator and its local, dated price table. They are not billed amounts. When GhostSlice is not reachable, a documented `len(text) / 4` fallback estimate is used instead, and the method string recorded in the manifest says which estimator produced the figures.

### Redaction: on by default

If a surface file contains a secret-shaped literal, the export warns, and **by default** replaces that value with a redaction marker in the exported copy only. Your source project is never altered. Each redaction is recorded in the manifest (file and finding type, never the value).

In detail:

- Detection covers a fixed set of shapes (for example cloud access keys, common token prefixes, private-key blocks, and quoted assignments under sensitive names). A literal in another shape will not be recorded or redacted by this tool. The coverage limits in every export say so.
- Redaction records list path, line, and finding type only. The literal value is never written to `manifest.json`, `exposure.json`, `EXPOSURE.md`, or any log.
- Binary files matched as surface or context are carried verbatim under `files/` and recorded as binary in the manifest; they are not scanned as text.

Exporting a literal unredacted requires the explicit flag `--allow-unredacted`, and using that flag is also recorded in the manifest. There is no quiet path that ships a live-looking key. Treat any key that has ever been in a shared bundle as exposed and rotate it; redaction in the copy is a guardrail, not a time machine.

### 4. Send the bundle folder

Send the whole folder, including `exposure.json` and `EXPOSURE.md`. The receiver's steps are below, and they do not require trusting you or this README.

---

## For receivers

You received a bundle. Your job is to check that what you have is what the manifest says you have.

### 1. Verify the bundle

```bash
ghostexposure verify <bundle-folder>
ghostexposure verify <bundle-folder> --json   # machine-readable output
```

Verify re-runs the GhostSlice bundle check, confirms the inventory hash and the in/out partition in `exposure.json` match the bundle contents, and confirms every file in the sender's tree inventory is accounted for in the partition (in, or out, no third state). If a file was added to the bundle, or a listed file is missing, verify fails and names the file.

Verify exits with status `0` when the bundle matches its manifest and `1` when it does not. Each problem line names the specific discrepancy: a missing bundle file, a hash mismatch, a file present on disk but not recorded, a file recorded but missing on disk, or a partition entry that does not match the inventory count.

Verify also prints its own limit, every time: it cannot prove a sender did not share other files by another channel, and it cannot prove the surface pack was the right definition. It proves the bundle matches its manifest.

### 2. Read `EXPOSURE.md` before the code

It contains the full surface pack that was used (every pattern and its reason), the counts (files in tree, files in bundle, surface vs context), and what the pack does not cover. Judge the review scope from that, not from the folder alone: code outside the patterns was not in the tree view either side used, and sensitive logic in a file with no matching signal would not have been included.

Also check `exposure.json` directly when you need the per-file record: every inventory path, its decision, its reason codes, and its hash at scan time.

### 3. Work only from the bundle

Files marked `context` are present at signatures so you can judge the surface's callers and callees. Files marked as surface are in full. Everything else was accounted for as out, and is listed by name in `exposure.json`, so you can ask the sender about a specific excluded file instead of guessing.

---

## Commands

| Command | What it does |
|---|---|
| `ghostexposure scan <project> --surface <pack>` | Full inventory, per-file in/out proposal with reason codes, conflicts, coverage limits |
| `ghostexposure export <project> --surface <pack> -o <folder>` | Write the bundle (`files/`, `manifest.json`, `exposure.json`, `EXPOSURE.md`, `PROMPT.md`) |
| `ghostexposure verify <bundle-folder>` | Check a received bundle against its manifest and partition, naming any discrepancy |
| `ghostexposure packs [--surface <pack>]` | Print a surface pack's summary and every pattern with its reason |

All four run locally. No command makes a network call.

Shared options and exit codes:

- `--surface <pack.json>` (`scan`, `export`, `packs`): path to a surface pack JSON. When omitted, the built-in starter pack in `surfaces/starter.json` is used.
- `--json` (`scan`, `verify`): print a single JSON document instead of the human-readable report. Useful for scripts; the human report and the JSON report carry the same decisions and limits.
- `--version`: print the tool version and exit.
- Exit codes: `0` means success (for `scan`, no conflicts; for `verify`, the bundle matches). `1` means `scan` found conflicts or `verify` found a mismatch. `2` means the command stopped before completing, for example an unresolved conflict at export, a non-empty output folder, or an unreadable surface pack. The error message on stderr says which.

Run `ghostexposure <command> --help` for the full per-command options, including `--allow-unredacted` and `--exclude-conflicts` on `export`.

## Troubleshooting

| Symptom | What it means and what to do |
|---|---|
| `export stopped: unresolved conflicts ...` | A file matched the pack and a pin-out. Change the pin in `.ghostslice.json` or the pattern in the pack, or re-run with `--exclude-conflicts` to leave the files out with that decision recorded. |
| `export stopped: output folder exists and is not empty` | Export never overwrites a bundle. Pick a new folder or empty the old one, then re-run. |
| `error: surface pack not found: ...` | The `--surface` path does not exist. Check the path, or omit `--surface` to use the built-in starter pack. |
| `error: surface pack ... missing fields: ...` | The pack JSON is missing a required field (`id`, `version`, `date`, `description`, `patterns`, or `coverage_limits`), or a pattern is missing `id`, `kind`, `pattern`, or `reason`. Compare with `examples/starter-surface.example.json`. |
| `verify` reports `present on disk but not recorded in bundle` | A file was added under `files/` after export, or the folder was copied incompletely in the other direction for the paired `missing on disk` message. Ask the sender for a fresh export rather than editing the bundle by hand. |
| `verify` reports `hash mismatch for bundled file: ...` | The file on disk differs from the hash recorded at export. Treat the bundle as not matching its manifest; request a fresh export. |
| A file you expected in the bundle is `out` | No pack pattern matched it and it does not import a surface file. Add a pattern to the pack or pin it in with `pinned_in`, then scan again. Widening the pack widens what you share, so record the reason in the pattern. |

## Honest limits

- Pattern-bound detection will miss novel sensitive code. The coverage statement is in every export so this limit travels with the artifact.
- The in/out partition proves accounting against the inventory the sender's scan produced. Verify checks that partition against the bundle, not against a tree you do not have.
- Graph context is static analysis. For Python it uses GhostSlice's call graph; for other languages it is import and outline level, and `EXPOSURE.md` says which.
- Graph context is distance-1 callers only: files that import a surface file. Files a surface file itself imports are not pulled in by the graph rule; include them with a pattern or a pin if the review needs them.
- Estimates are estimates: token counts and costs come from a local estimator and a dated price table.

## Layout of this repo

```
PLAN.md        the v0.1 plan and verification bar
README.md      this file, written for senders and receivers
src/           the tool (Agent A)
surfaces/      starter surface packs (Agent A)
tests/         the verification-bar tests and fixtures (Agent B)
examples/      a mini project, an example surface pack, and a sample EXPOSURE.md
```

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
