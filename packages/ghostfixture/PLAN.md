# GhostFixture - Minimal Repro Project Generator for GhostSlice
Working name, prepared Oct 14, 2026. Paired tool #28 for GhostSlice (Wave 4).
Decision: NOT Goliath. Goliath stays reserved for a non-agent product (Ryan, Oct 11-12, 2026).

## Why this name
- GhostFixture: a fixture is the smallest self-contained setup that reproduces a situation. That is exactly the output: a small standalone project tree that reproduces the context of a task, nothing more.
- Checked against the family: GhostSlice cuts context down to a bundle, GhostFixture turns a bundle back into a runnable-shaped project skeleton. No claim of a live product search yet. Treat as a working name until a name check runs at build gate, same as GhostSlice did Oct 12.
- Alternatives held in reserve: GhostRepro (clear, but narrower - implies bug reports only), GhostMini (says small, not what it is for).

## The problem
A GhostSlice bundle is reading material for an agent: sliced text under `files/`, a manifest, a PROMPT.md. It is not a project you can open, run, hand to a teammate, or attach to a bug report.

When a developer needs a minimal reproduction of "the agent had this context and did this", or wants to share the exact slice a task ran against, today they hand-copy files out of the original repo. That is slow and error-prone in both directions:
- They copy too much: half the repo comes along, including files with secrets in them, because nobody checked each file by hand.
- They copy too little: the bundle references a module, but that module imports two more files that were never in the bundle, so the repro does not even parse.

There is no tool that turns a bundle back into an honest minimal project tree, states what it left out and why, and refuses to carry flagged secrets into the copy.

## Position in the Ghost stack
- GhostSlice governs what an agent READS (scanner, AST slicer, token estimator, `.claude_context` bundle with manifest + sha256).
- GhostFixture governs what a human or a second tool can HOLD afterwards: the bundle, materialised as a real directory tree with an inclusion record.
- GhostVerify governs whether the slice was enough. GhostFixture does not judge sufficiency; it copies what the bundle references, plus the static import closure those files need to parse.
- Agent Seatbelt governs what an agent DOES. Ghost Hands is the governed browser body.

Story: Slice -> (Verify) -> agent runs -> Fixture materialises the exact context as a shareable minimal project.
No overlap: Slice exports views of a project. Fixture builds a new, separate tree and never writes into the source project.

## How it pairs with GhostSlice, concretely
- Input is any GhostSlice bundle: reads `manifest.json` (per-file path, mode, sha256, totals) and the project the bundle was cut from (the manifest `root`, or an explicit project path). Files recorded with mode `exclude` in the manifest are not referenced and are never copied.
- Source of truth for copying is the ORIGINAL project files, not the sliced text under the bundle's `files/`. A fixture is a repro of the real code subset, at full fidelity. The bundle decides WHICH files; the project supplies the bytes.
- Secret shapes: GhostFixture runs its own shape scan before copying (provider token shapes, private key headers, password-bearing URLs, sensitive-name assignments, same conservative family as Slice's secret guard). A flagged file is excluded by default and named in the fixture manifest by path and pattern type only, never by value.
- Output is self-describing: `fixture-manifest.json` states the source bundle (path + manifest sha256), the task description, what was included (and why), what was left out (and why), and the size cap that was in force.
- No GhostSlice code is modified and no Slice export is re-run. Fixture consumes the bundle as a finished artifact.

## MVP (v0.1) - local CLI first
1. Build: `ghostfixture build <project> <bundle> -o <out-dir> [--task "..." | --task-file f] [--max-bytes N] [--include-flagged]`
   - Seed set: every file the bundle manifest lists at a mode other than `exclude`.
   - Import closure: statically resolve local imports of seed files, recursively, within the project only. Python via real `ast` (absolute and relative imports, package `__init__` chain included when present). JS/TS via import/require patterns, relative specifiers only. Other languages: no closure in v0.1, labelled in the manifest as not computed.
   - Bare/external imports (package names, unresolvable top-level modules) are recorded in the manifest as external references, not copied and not treated as errors.
   - Copy originals into a brand-new output tree, preserving relative paths. Nothing else comes along: no `.git`, no unreferenced files, no bundle artifacts beyond the fixture's own manifest and summary.
2. Hard safety rules (not options, except where stated)
   - The source project is never modified. The output directory must not be inside the project, and the project must not be inside the output directory. An existing non-empty output directory is refused.
   - Secret-flagged files are EXCLUDED by default and named in the manifest as excluded-flagged (path + pattern types only, never values). `--include-flagged` overrides, and the manifest still records that the file was flagged and included by override.
   - Total copied content is capped (default 2 MiB). The cap is printed in CLI output and recorded in the manifest. Files that do not fit are left out with reason `size-cap`, bundle-referenced files first, closure files after, in deterministic order.
   - Symlinks are never followed out of the project root. A referenced path that resolves outside the root is left out with reason `symlink-escapes-root` (or `outside-root` for non-symlink escapes).
   - Missing files (referenced by the bundle, absent from the project) are left out with reason `missing-in-project`, never invented.
   - A file the bundle lists with mode `exclude` is never copied, even when a copied file imports it: import closure does not override a bundle exclusion. It is recorded as left out with reason `bundle-excluded`. Closure only adds files the bundle never mentioned.
3. Fixture manifest + summary, written into the output tree root:
   - `fixture-manifest.json`: task, source project, source bundle path + manifest sha256, generated-at, cap, totals (files considered / included / excluded-flagged / left out / bytes copied), `included[]` (path, reason: bundle-referenced or import-closure, via importer where applicable, bundle mode, bytes, sha256), `excluded_flagged[]` (path, pattern types), `left_out[]` (path, reason, detail), `external_references[]`, and per-language closure notes.
   - `FIXTURE.md`: the same record in human form, plus how the fixture was made and its honest limits.
4. Check: `ghostfixture check <fixture-dir>`
   - Re-verifies the tree against `fixture-manifest.json`: every included file present with matching sha256, no unexplained extra files, no excluded-flagged file present. Exit 0 clean, 1 mismatch, 2 could not check.
5. MCP tools (stdio, local only): `build_fixture`, `check_fixture`, capped summary payloads, no file bodies, same discipline as Slice and Verify MCP.

Exit codes for build: 0 = fixture built (exclusions and left-outs are normal, reported outcomes), 1 = fixture would be empty, 2 = could not build (bad bundle, bad project, refused output location).

## Out of scope for v0.1
- Making the fixture run. No dependency installation, no test execution, no environment setup. The closure is static and parse-level; a fixture may still need packages, data files, or services the bundle never referenced.
- Copying sliced text instead of originals, or slicing files further. Selection is the bundle's job, already done.
- Redacting flagged files so they can be included. Flagged means excluded in v0.1; redaction is GhostSlice's secret guard territory.
- Non-local import resolution (installed packages, vendored trees outside the project root).
- Judging whether the bundle was sufficient (GhostVerify) or whether the fixture reproduces a bug. Fixture materialises context; it proves nothing about behaviour.
- Cloud, accounts, telemetry, paid layer.

## Build estimate
- Bundle reader + seed set + copy engine with root/symlink/cap rules: 1-2 days
- Python ast closure + JS/TS pattern closure + external reference capture: 1-2 days
- Secret shape scan (path + type only) + flagged exclusion flow: 1 day
- Fixture manifest + FIXTURE.md + check command: 1 day
- MCP server + tests (planted-secret fixture, symlink escape, cap behaviour, closure correctness) + README/examples: 1-2 days
Total: roughly 1 week to a verified v0.1 if built straight through.

## Pricing draft (NOT public, NOT decided)
- MIT core CLI free, same pattern as Slice / Verify / Seatbelt / Ghost Hands.
- Paid candidate later only: team repro libraries / CI fixture packs. Do not build a paid layer before a free launch validates demand.

## Verification bar
- Closure test: a fixture project where a bundled file imports a non-bundled local module, which imports one more; the fixture must contain all three, with the two extra files recorded as import-closure with their importers named.
- Planted-secret test: a bundle-referenced file carrying a known secret shape must be excluded by default, named in the manifest by path and type with no value anywhere in the output tree, and `--include-flagged` must include it while still recording the flag.
- No-touch test: source project tree hashes identical before and after a build; a build aimed inside the project is refused.
- Symlink test: a referenced symlink pointing outside the project is left out with the recorded reason; a symlink pointing inside the project is copied as content, not as a link.
- Cap test: a project whose referenced files exceed a small `--max-bytes` shows bundle-referenced files kept first, the rest left out with reason `size-cap`, and the cap stated in both CLI output and manifest.
- Round trip: `ghostfixture check` passes on a freshly built fixture and fails when a copied file is edited afterwards.

## Risks / honest notes
- Static closure is not a runtime guarantee. Dynamic imports, string-built module paths, reflection, and plugin loaders are invisible to it, and the manifest must say closure is parse-level, per language.
- Secret shapes are a conservative net, not a proof. An unflagged file can still contain a secret in a shape the scanner does not know; copy must say "no flagged shapes found", never "secret-free".
- Bundle manifests record paths as the exporter wrote them; a bundle cut from a different machine or an older project state can reference files that have moved. Missing files are reported, not hunted for.
- Copying originals means a fixture can contain code newer than the bundle if the project changed after the export. The fixture manifest records the bundle manifest hash so the pairing is auditable, and FIXTURE.md states this plainly.

## Next gate
Ryan's go on: (1) GhostFixture as working name, (2) originals copied at full fidelity (sliced text stays the bundle's job), (3) flagged files excluded by default with an explicit override flag, (4) build slot in Wave 4 as dispatched.
