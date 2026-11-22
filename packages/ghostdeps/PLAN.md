# GhostDeps - Dependency Context Pack for GhostSlice
Working name, prepared Oct 14, 2026. Paired tool #32 for GhostSlice (Wave 4).
Decision: NOT Goliath. Goliath stays reserved for a non-agent product (Ryan, Oct 11-12, 2026).

## Why this name
- GhostDeps: plain job, plain name. It packs what a project depends on into context an agent can read.
- Checked against the family: GhostSlice slices code, GhostVerify checks sufficiency, GhostExposure maps audit surfaces. None of them answer "what does this project declare, and what does the code actually import?" That is this tool.
- Alternatives held in reserve: GhostManifest (too narrow, lockfiles matter as much as manifests), GhostImports (names only half the job, misses the declared side).

## The problem
An agent dropped into an unfamiliar project has no cheap way to learn its dependency shape:

- Manifests and lockfiles are long, machine-shaped, and token-expensive to paste whole. A `package-lock.json` can be thousands of lines, most of it transitive noise.
- What a project *declares* and what its code *actually imports* drift apart. Manifests accumulate entries nothing imports any more; code imports packages nobody declared, which then break on a clean install.
- Version pins are scattered across manifests, lockfiles, and requirement files with different syntax per ecosystem, so "what version are we on" takes a human several file opens to answer.

Today the agent either burns tokens reading raw lockfiles, or guesses, and guesses about dependencies turn into broken installs and phantom imports.

## Position in the Ghost stack
- GhostSlice governs what an agent READS (source code, sliced to budget).
- GhostDeps governs the DEPENDENCY CONTEXT around that code: declared vs imported, pins as recorded, gaps named with evidence.
- GhostExposure governs audit surfaces (evidence only, no verdicts). GhostDeps follows the same discipline for dependencies: evidence only, no safety or vulnerability judgement.
- Agent Seatbelt governs what an agent DOES. GhostDeps never installs, removes, or changes anything.

Story: Slice packs the code -> Deps packs the dependency facts -> the agent starts knowing both the code and what it stands on.

## How it pairs with GhostSlice, concretely
- Same family conventions: local CLI first, zero-dependency Python stdlib, manifest + human report next to the pack, exit codes a CI can read.
- Output is a context pack (`DEPS.md` + `deps-manifest.json`) shaped so it can ride alongside a Slice bundle or be pasted on its own. It does not modify Slice bundles.
- Token discipline borrowed from Slice: summaries, not raw lockfile dumps. `package-lock.json` is read at summary level (top-level packages and pins), never reproduced whole.
- GhostSlice stays the code slicer. GhostDeps reads manifests, lockfiles, and import statements only; it never slices source bodies.

## MVP (v0.1) - local CLI first
1. Manifest and lockfile parsing, local files only:
   - Python: `pyproject.toml` (via stdlib `tomllib`: project dependencies, optional-dependencies, dependency-groups), `requirements*.txt` (including `-r` includes noted, not fetched), `setup.cfg` / `setup.py` recorded as present-but-unparsed if encountered (labelled).
   - JavaScript/TypeScript: `package.json` (dependencies, devDependencies, peerDependencies, optionalDependencies), `package-lock.json` at summary level only (lockfile version, root package pins).
   - Rust: `Cargo.toml` (dependencies, dev-dependencies, build-dependencies, workspace members noted).
   - Anything else present (Gemfile, go.mod, composer.json, Pipfile) is listed as detected-not-parsed in v0.1, never silently skipped.
2. Import extraction, cross-reference evidence:
   - Python imports via real `ast`: top-level module names per file, with file lists.
   - JS/TS imports via parser-lite regex over `import` / `export ... from` / `require()` statements, labelled parser-lite in every report.
   - Import names mapped to distribution names with a small built-in table for the common mismatches (PIL -> Pillow, yaml -> PyYAML, cv2 -> opencv-python, sklearn -> scikit-learn, and similar), plus PEP 503 style normalisation (case, `_` / `-` / `.`). Unmapped names are compared as-is and the report says so.
   - Local modules (files and packages inside the tree) and Python stdlib modules are classified separately, never reported as missing declarations.
3. The pack: `ghostdeps pack <project> [-o <out>]`
   - `DEPS.md`: human report with four sections: declared-and-used, declared-not-imported, imported-not-declared, pins as recorded.
   - `deps-manifest.json`: the same facts machine-readable, plus per-dependency evidence (which files import it, which manifest declares it, which lockfile pins it).
   - Wording rule: declared-not-imported entries say "no import found in scanned code" and list possible innocent explanations (CLI entry points, plugins, type-only or runtime loading). The words "unused", "safe to remove", and "dead" never appear as a verdict.
   - Imported-not-declared entries name the importing files as evidence and note common innocent causes (transitive availability, stdlib lookalikes, monorepo siblings).
4. Doctor: `ghostdeps doctor <project>` reports which manifests/lockfiles were found, which were parsed vs detected-only, and the parser confidence per language. Exit 0 = pack built, 1 = findings present (imported-not-declared is a finding; declared-not-imported is information, not a failure by default), 2 = could not parse (no manifests found, or a manifest failed to parse).

## Hard rules (v0.1, no exceptions)
- No network, ever. No registry lookups, no CVE or advisory lookups, no "check for updates". There is no code path that opens a socket.
- No vulnerability verdicts, no safety grades, no "outdated" labels. A version is reported as recorded in the local files. The word "latest" is never used about a version.
- Local evidence only: if it is not in the tree, it is not in the report.
- Read-only: GhostDeps never edits a manifest, never installs or removes a package, never rewrites a lockfile.

## Out of scope for v0.1
- Vulnerability scanning, licence auditing, update checking, or upgrade planning (GhostPort owns migration planning; this is not that).
- Lockfiles beyond summary level: full transitive resolution, dependency trees, dedup analysis.
- Ecosystems beyond Python / JS-TS / Rust parsing (detected-not-parsed list only).
- Monorepo workspace resolution beyond noting members and sibling packages.
- Fixing declarations. Deps reports the gap; a human decides.

## Build estimate
- Manifest/lockfile parsers (Python, package.json, package-lock summary, Cargo): 2-3 days
- Import extraction (ast + parser-lite) and name mapping: 1-2 days
- Cross-reference, pack writer (DEPS.md + manifest), doctor: 1-2 days
- Tests (fixture projects with planted gaps in each ecosystem), README, examples: 2 days
Total: roughly 1 to 1.5 weeks to a verified v0.1 if built straight through.

## Pricing draft (NOT public, NOT decided)
- MIT core CLI free, same pattern as Slice / Verify / the rest of the suite.
- Paid candidate later only: team packs that bundle Deps output into CI gates. Do not build a paid layer before a free launch validates demand.

## Verification bar
- Fixture Python project with one declared-not-imported package and one imported-not-declared package: pack must place both in the right sections, name the importing files for the second, and use evidence wording only.
- Fixture JS project: `package.json` declared set cross-checked against parser-lite imports; a `package-lock.json` present must be summarised, and the pack output must be dramatically smaller than the raw lockfile.
- Fixture Rust project: Cargo dependencies cross-checked against `use` statements at outline level, labelled as such.
- Clean fixture (declared set exactly matches imports): imported-not-declared section empty, exit path clean.
- Real-repo smoke: run against GhostSlice itself (stdlib only, zero declared dependencies) and report the result honestly; zero-dependency projects must produce a sane, short pack, not an error.
- Wording scan: the strings "safe to remove", "vulnerable", "outdated", and "latest version" must not appear in any generated report.

## Risks / honest notes
- Name mapping is the weak point: import name to distribution name is a heuristic table plus normalisation. Dynamic imports, plugin loading, and entry-point-only dependencies will land in declared-not-imported with no import evidence; the wording rule exists precisely because that section is leads, not verdicts.
- Parser-lite JS/TS extraction can miss re-exports and computed requires, and can catch commented-out imports. It is labelled parser-lite everywhere it is used.
- Lockfile formats drift between tool versions (npm lockfile v1 vs v3 shapes differ). Summary-level parsing must degrade to detected-not-parsed rather than guess.
- A dependency gap is evidence about declarations and imports, nothing more. Copy must never let it read as a safety or hygiene judgement.

## Next gate
Ryan's go on: (1) GhostDeps as working name, (2) Python + JS/TS + Rust parsing in v0.1 with everything else detected-not-parsed, (3) no network and no vulnerability data as a permanent product rule, not just a v0.1 limit, (4) declared-not-imported being information-only (not a failing finding) by default.
