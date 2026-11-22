# GhostLift - Decompiler / Lifter for GhostSlice
Working name, prepared Oct 14, 2026. Origin: Ryan's Oct 14, 2026 chat, "What about a decompiler."
Decision: NOT Goliath. Goliath stays reserved for a non-agent product (Ryan, Oct 11-12, 2026).

## Why this name
- GhostDecompile overpromises. A general decompiler (Ghidra class) is years of work, and lifted output is a reconstruction, not the original source. Lift is the honest word: it lifts a compiled or minified artifact back up to readable source a person and GhostSlice can work with.
- GhostLift: no direct product claim made here. Treat as a working name until a name check runs at build gate, same discipline as GhostSlice on Oct 12, 2026.
- Sits next to GhostSlice in the family: Lift recovers the source, Slice then governs what an agent reads from it.

## The problem (Ryan's framing)
GhostSlice works on source. Whole projects have no source to slice: a vendor SDK or legacy app where only the compiled artifact survives, a production JS bundle with no repo behind it, a .pyc-only Python deployment, a shipped build that no longer matches its repo. GhostSlice's scanner skips binaries and its detection (v0.12) flags minified and generated files, so that code is invisible to the whole suite. The developer either re-derives it by hand or feeds an agent an artifact it cannot read.

## Position in the Ghost stack
- GhostLift governs what an agent can RECOVER (compiled / minified artifacts back to readable source, before any slicing).
- GhostSlice governs what an agent READS (pre-flight, before any spend).
- Agent Seatbelt governs what an agent DOES (consequential actions, approvals).
- Ghost Hands is the governed browser body.
That is a clean recover -> read -> action -> body story, no overlap. Lift is a front door for Slice, not a second slicer.

## MVP (v0.1) - three tiers, honesty labelled per file
Every lifted file is watermarked in the output manifest as lifted, with its tier, its source artifact, and the artifact's sha256. Lifted output is never passed off as original source. Where a tier label applies is per file, not per run.

1. Tier 1 - Exact Recovery (source maps and debug symbols)
   - Parse a version 3 source map (.js.map / .css.map) and recover each entry in sources that carries sourcesContent, byte for byte.
   - Recovered paths are sanitised so no source path can escape the output tree (no absolute paths, no .. traversal); any path that had to be rewritten is recorded in the manifest.
   - Sources listed in a map but carrying no embedded content are reported as not recovered, by name, never silently dropped.
2. Tier 2 - Structured Lift (Python .pyc beachhead, minified JS second)
   - Python .pyc: parse the 16-byte .pyc header and the marshal stream with GhostLift's own safe byte parser. It never calls marshal.loads on an artifact, never imports it, and never executes it. Parser limits (file size, object count, nesting depth, string size) fail the lift loudly instead of consuming unbounded resources.
   - Reconstruct a readable Python source skeleton from code-object metadata (module, classes, functions, async and generator markers, argument names including positional-only, keyword-only, *args and **kwargs, docstrings): the same shape GhostSlice signatures mode produces, ready for Slice to scan and slice. Bodies are NOT claimed as recovered; each lifted body carries a placeholder plus an approximate adaptive-bytecode listing as comments, for reading only.
   - Bytecode support is pinned to the code-object layouts GhostLift has tests for (CPython 3.11 / 3.12 / 3.13 marshal layouts). An artifact with an unknown magic is refused by name in inspect and lift, not guessed at.
   - Minified JS: beautify plus function-boundary recovery built on GhostSlice parser-lite ideas. Scoped as the second Tier 2 target; the core build lands Python first.
3. Tier 3 - Pseudo-Source Outline (other bytecode, label only in v0.1)
   - For other bytecode (Java class, .NET, Android dex and similar), v0.1 produces at most a labelled pseudo-source outline (names and structure), and only where a later plan names that format.
   - In the core v0.1 build these artifacts are detected by inspect and reported as Tier 3 / not yet liftable. No outline is faked from data GhostLift cannot parse.
4. Inspect (before any lift)
   - `ghostlift inspect <artifact>` reports artifact type, detected tier, magic and implied CPython version for .pyc, size, sha256, embedded source filename, and top-level symbol count, with a --json form. Inspect never executes anything.
5. Slice-Compatible Output
   - `ghostlift lift <artifact-or-folder> -o <out>` writes files/ (the recovered or lifted source tree) plus manifest.json in the GhostSlice bundle style: per file path, sha256 of the output, a token estimate labelled as an estimate, lifted: true, tier, tier name, recovery kind (exact / structured / outline), source artifact and its sha256.
   - A lifted tree is then a normal project GhostSlice can scan, slice, and export.

## Out of scope for v0.1
- A general-purpose decompiler, native binaries (no Ghidra-class work), control-flow reconstruction to original-quality source, and recovery of comments, formatting, variable names that were never stored, or default argument values not present in the artifact metadata GhostLift reads.
- Executing, importing, or dynamically loading any artifact, at any tier, for any reason.
- Android APK / dex, Java, .NET, and WASM lifting beyond Tier 3 detection and reporting.
- Any circumvention use: no licence checks, DRM, or protection bypass. GhostLift is for code you own or have the right to inspect. That line goes in the README and in this plan.
- Network, accounts, cloud sync, payments, telemetry, Tauri / Electron packaging.

## Build estimate
- Safe marshal parser + .pyc header handling (with parser limits and layout tests): 3-4 days
- Python structured reconstruction (signatures, classes, nesting, docstrings, bytecode comment listing): 2-3 days
- Tier 1 source map recovery + path sanitising: 1-2 days
- CLI (inspect / lift) + Slice-style manifest and output tree: 1-2 days
- Hardening, round-trip tests, README, demo on a compiled Ghost tool: 1-2 days
Total: roughly 1.5 to 2 weeks to a verified v0.1 core (Tier 1 + Tier 2-Python), if built straight through. Minified JS Tier 2 and any Tier 3 outline format are follow-on work, not hidden inside that estimate.

## Pricing draft (NOT public, NOT decided)
- MIT core CLI free, same pattern as Seatbelt / Ghost Hands / GhostSlice.
- Paid candidate later only: maintained lifters for more artifact formats. Do not build a paid layer before a free launch validates demand.

## Verification bar
- Round-trip smoke test: compile a small Python file to .pyc, lift it back, and compare the function and class signatures (names and arguments) between the original and the lifted source parsed as AST. The result, including any mismatch, is recorded honestly.
- Tier 1 test: build a source map fixture with embedded sourcesContent and confirm the recovered files match the original bytes exactly.
- Safety test: grep / fixture proof that the package contains no marshal.loads, no exec / eval, and no import of a lifted artifact, and a malformed or hostile marshal fixture is refused by the parser limits without executing anything.
- Manifest test: every output file is marked lifted with its tier, and re-running a lift reproduces the same manifest totals and hashes.

## Risks / honest notes
- Recovery quality is bounded by what the artifact stores. Source maps can be exact; .pyc metadata supports structure and signatures, not the original bodies, comments, or formatting. Copy and manifests must say reconstruction where it is reconstruction.
- Untrusted marshal is a real attack surface in CPython. That is why GhostLift parses the byte format itself with limits instead of unmarshalling: a parser bug should produce a refused lift, never code execution.
- Bytecode layouts change between CPython versions. Support is pinned and tested per version, unknown magic is refused, and the supported set is stated in the README rather than implied.
- Legal scope matters: lifting is for your own code or code you have the right to inspect. GhostLift is not a tool for bypassing licences or protections, and the plan does not scope any such feature.

## Next gate
Ryan's go on: (1) GhostLift as working name, (2) Tier 1 + Tier 2-Python as the v0.1 core, minified JS as the next Tier 2 target, (3) static only, never execute an artifact, as a non-negotiable rule.
