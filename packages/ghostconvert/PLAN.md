# GhostConvert - Slice Bundle Format Converter for the GhostSlice Suite
Working name, prepared Oct 14, 2026. Paired tool #27 for GhostSlice, Wave 4.
Decision: NOT Goliath. Goliath stays reserved for a non-agent product (Ryan, Oct 11-12, 2026).

## Why this name
- GhostConvert: plain job, plain name. It converts a finished GhostSlice bundle into the instruction formats other agents actually read.
- Checked against the family: Slice cuts, Convert carries the cut across tools. No claim of a live product search yet. Treat as a working name until a name check runs at build gate, same as GhostSlice did Oct 12.
- Alternatives held in reserve: GhostPort (taken, Wave 2 migration slicer), GhostBridge (taken, separate product), GhostCast (implies broadcasting or sending, which this tool never does).

## The problem
GhostSlice ships one canonical bundle: a `.claude_context` directory with `PROMPT.md`, `manifest.json`, and `files/`. That shape is native to Claude Code style workflows. The rest of the agent world reads different surfaces:

- Tools that follow the AGENTS.md convention want one `AGENTS.md` at the project root.
- Cursor wants rules under `.cursor/rules/` as `.mdc` files with frontmatter.
- GitHub Copilot wants `.github/copilot-instructions.md`.
- Everything else wants a single plain prompt file it can paste or attach.

Today the developer hand-copies `PROMPT.md` into those shapes, or re-slices per tool and loses Slice's calibrated choices. Hand conversion drops things silently: the slice mode each file was cut at, per-file token counts, hashes, redaction records, and the list of excluded files all vanish without a note, so nobody can tell what the receiving agent did not get.

## Position in the Ghost stack
- GhostSlice governs what an agent READS: it makes the slicing decisions and records them in the manifest.
- GhostConvert governs the SHAPE that reading arrives in. It makes no slicing decisions of its own and never re-slices; it re-expresses a finished bundle, decisions intact, in the target tool's format.
- GhostPacks manages Slice profiles as data packs. Convert is downstream of a bundle, not of a profile, so there is no overlap.
- GhostVerify checks a bundle is sufficient. Convert assumes a bundle that already passed whatever checks the user runs; it converts, it does not judge.

Story: project -> Slice (bundle) -> Verify (optional) -> Convert (per target tool) -> agent runs in its native format.

## How it pairs with GhostSlice, concretely
Reads, never writes, the bundle:
- Input is a GhostSlice bundle directory: `manifest.json` is the authority for file order, per-file mode, language, token estimates, and sha256; file bodies come from `files/<path>` exactly as Slice wrote them. `PROMPT.md` is the fallback body source when a `files/` entry is missing on disk, parsed on its `# File: <path> (mode: <label>)` headers.
- The source bundle is treated as read-only. Convert hashes nothing into it, writes nothing into it, and refuses an output directory inside the bundle directory.
- Converted output keeps the manifest's file order. Mode labels stay visible as section headers or comments wherever the target format allows.
- Every conversion emits a losses note naming what the target format cannot carry (per-file hashes, token counts, redaction metadata, excluded files, symbol lists) instead of dropping it silently. The note ships in the output directory and is summarised in the CLI output.
- No GhostSlice code is imported. Convert reads the bundle format only, so it works on bundles produced by any Slice version that keeps the documented manifest shape.

## MVP (v0.1) - local CLI, four targets
1. `ghostconvert convert <bundle> --to <target> -o <outdir>` with targets:
   - `agents`: one `AGENTS.md`. Header records source project, Slice totals, and the conversion note. One `## File: <path> (mode: <label>)` section per file, body in a fenced block, manifest order.
   - `cursor`: `.cursor/rules/*.mdc`. Files grouped by top-level directory into one rule file per group (root-level files into a `root` group), each with frontmatter (description, globs naming the original paths) and per-file sections carrying the mode label. Grouping is a loss and is named in the losses note.
   - `copilot`: `.github/copilot-instructions.md`, same section discipline as `agents`.
   - `generic`: one `prompt.md`, plain concatenation with `# File: <path> (mode: <label>)` headers, closest to the original `PROMPT.md` shape.
   - `--to all` runs every target into subdirectories of the output dir.
2. Losses accounting, per target, computed from the manifest, written to `LOSSES.md` in the output dir (for `all`, one per target subdirectory):
   - Always named when present: excluded files (in the manifest, no body in any target), per-file sha256 values, per-file token estimates, redaction counts and kinds, `symbols_included` lists, package groupings, Slice fit/score metadata.
   - Per target: frontmatter and section limits of the format itself (for example, Cursor rule files cannot carry per-file hashes; AGENTS.md has no machine-readable per-file metadata block).
   - A conversion with zero losses says so in the note instead of omitting the file.
3. `ghostconvert inspect <bundle>`: prints bundle summary (project, Slice version, file count by mode, totals) and which targets are available, without writing anything.
4. `ghostconvert targets`: lists the four targets and the artifact path each one writes.
5. Safety rules:
   - Output directory must be named by the user and must not be the bundle directory or inside it. Existing files at the exact artifact paths are overwritten only with `--force`; otherwise the run refuses and names the collision.
   - Manifest paths are validated as relative and contained; a path that escapes the bundle is skipped and named in the losses note, never followed.
   - A malformed manifest, or a bundle with no readable file bodies, exits 2 (could not convert), never a partial silent success. Files missing bodies are converted as absent and named in the losses note.
   - Exit codes: 0 = converted (losses, if any, are in the note; losses are not failures), 2 = bad bundle or bad arguments.

## Out of scope for v0.1
- Re-slicing, re-scanning the project, or changing any mode. Convert expresses Slice's decisions; it does not second-guess them.
- Editing the source bundle, the source project, or the target project's existing instruction files in place. Output goes to a fresh directory the user names; merging into a live project is the user's step.
- Targets beyond the four: Aider conventions, Windsurf, Claude project files, XML or JSON wrappers (Slice already ships anthropic-xml and json presets at export time; duplicating them is not Convert's job).
- Reverse conversion (target format back to a bundle), and round-trip guarantees.
- MCP server, cloud, accounts, telemetry, paid layer.

## Build estimate
- Bundle reader (manifest authority, files/ bodies, PROMPT.md fallback, path containment): 1 day
- Four target renderers with mode-label discipline: 1-2 days
- Losses accounting per target + LOSSES.md: 1 day
- CLI, overwrite guard, exit codes: half a day
- Tests (golden bundles, per-target loss checks, source-bundle immutability), README, examples: 1-2 days (Agent B, in parallel)
Total: roughly 3 to 5 days to a verified v0.1 if built straight through.

## Pricing draft (NOT public, NOT decided)
- MIT core CLI free, same pattern as Slice / Seatbelt / Ghost Hands.
- Paid candidate later only: team format packs for additional target tools. Do not build a paid layer before a free launch validates demand.

## Verification bar
- Golden bundle test: a real GhostSlice bundle (built by Slice itself from a fixture project, mixed modes including an excluded file and a symbols-mode file) converts to all four targets; file order and mode labels match the manifest in every artifact.
- Losses test: the same bundle's LOSSES.md for each target names the excluded file, the per-file hashes, and the token estimates. A target that carried everything would have to say zero losses explicitly.
- Immutability test: sha256 of every file in the source bundle is identical before and after every conversion, and no new file appears inside the bundle directory.
- Real-repo test: a bundle sliced from the GhostSlice repo itself converts to all four targets without error, and the AGENTS.md output opens with the conversion header and keeps manifest order.

## Risks / honest notes
- Target formats drift: Cursor's .mdc frontmatter and Copilot's instruction file conventions change over time. Convert pins the shapes it writes in its README and treats a format change as a version bump, not a silent edit.
- Grouping for Cursor is a judgement call (by top-level directory). It is named as a loss because the receiving tool sees rule files Slice never made.
- Converted context is still sliced context: a signatures-mode file arrives as signatures in every target. The mode label is the warning; Convert must never present a converted bundle as the full project.

## Next gate
Ryan's go on: (1) GhostConvert as working name, (2) the four v0.1 targets (AGENTS.md, Cursor rules, Copilot instructions, generic prompt), (3) losses note as a shipped artifact rather than console-only output, (4) output to a fresh user-named directory only, never merged into a live project by the tool.
