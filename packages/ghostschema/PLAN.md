# GhostSchema - API Spec Slicer for GhostSlice
Working name, prepared Oct 14, 2026. Paired tool #30 for GhostSlice, Wave 4.
Decision: NOT Goliath. Goliath stays reserved for a non-agent product (Ryan, Oct 11-12, 2026).

## Why this name
- GhostSchema: the job is slicing schemas. It cuts a large API specification down to the part a task actually touches, the same way GhostSlice cuts a codebase down to the files a task needs.
- Checked against the family: GhostDocs (#12) slices non-code corpora (docs, PDFs, notes). GhostSchema is the structured-spec counterpart: machine-readable API contracts with $ref graphs, not prose. No overlap.
- No claim of a live product search yet. Treat as a working name until a name check runs at build gate, same as GhostSlice did Oct 12.
- Alternatives held in reserve: GhostSpec (shorter, but "spec" reads as requirements doc, not API contract), GhostContract (implies it enforces contracts at runtime, which v0.1 must not claim).

## The problem
API specifications are some of the largest single files a developer hands an agent. A real-world OpenAPI document runs tens of thousands of tokens: hundreds of operations, hundreds of component schemas, most of them irrelevant to the task at hand. The agent pays for all of it, and the relevant endpoint drowns in unrelated surface.

GhostSlice does not help here. It slices code by AST and import graph; a spec is one giant JSON document with an internal reference graph ($ref), not a tree of files. Slicing it by hand means tracing $refs manually, which is slow and error-prone: miss one reachable schema and the reduced spec is broken; keep too much and nothing was saved.

There is no stdlib-only, local tool in the suite that reduces a spec by reachability and proves what it kept, what it dropped, and what it could not resolve.

## Position in the Ghost stack
- GhostSlice governs what an agent READS from a codebase.
- GhostSchema governs what an agent READS from an API contract: the spec-side slicer.
- GhostDocs governs what it reads from prose corpora. GhostData (#33) governs structured data files (CSV/JSONL samples). GhostSchema is specs only: OpenAPI, JSON Schema, GraphQL SDL.
- Agent Seatbelt governs what an agent DOES, GhostVerify governs whether what it read was ENOUGH.

Story: Slice cuts the code, Schema cuts the contract, the agent works from both reduced bundles, each with a manifest.
No overlap: Slice never parses $ref graphs inside a single document; Schema never slices source files.

## How it pairs with GhostSlice, concretely
Reuses, does not rebuild:
- Token estimator: delegates to GhostSlice's calibrated estimator when a GhostSlice install or sibling checkout is reachable (same pattern as GhostPort and GhostExposure), and stamps the method string in every manifest. Falls back to a documented chars/4 estimate, labelled as a fallback. All counts are estimates.
- Manifest discipline: every run emits manifest.json with source sha256, kept/dropped lists, token estimates before and after, and an unresolved list, so a reduced spec is auditable the way a Slice bundle is.
- Bundle shape: output is a directory (reduced spec + manifest.json + SCHEMA.md summary), never an in-place edit. Input files are never modified.
- MCP: same stdio JSON-RPC pattern as Slice's MCP server, with capped summary payloads and no spec bodies by default.

Integration contract:
- Input: one spec file (OpenAPI 3.x JSON, standalone JSON Schema, or GraphQL SDL), plus a selection: a task string, explicit ids, or --all.
- Output: a bundle directory. For JSON specs, spec.json is a reduced but valid document of the same kind. For SDL, outline.json + OUTLINE.md, labelled outline everywhere (see MVP).
- Errors are explicit: unsupported or unparseable input exits 2 with the reason, never a silent empty bundle.

## MVP (v0.1) - local CLI first
1. Load and classify: `ghostschema inspect <spec>` and `ghostschema slice <spec> ...`
   - JSON parse for .json and extensionless JSON content. Detect OpenAPI 3.x (top-level `openapi` key) vs standalone JSON Schema (anything else that parses as a JSON object). Swagger 2.0 is refused with a clear message (different ref layout, out of scope for v0.1).
   - GraphQL SDL detected by .graphql/.gql extension or by SDL keyword sniffing on non-JSON text.
   - YAML is refused with a clear message, by extension (.yaml/.yml) or by content sniff. Stdlib has no YAML parser and v0.1 does not fake one. YAML support is a later gate, likely via a JSON-conversion pre-step the user runs, not a hand-rolled parser.
2. Selection
   - By task terms: `--task "add a pet to the store"` scores operations (operationId, path, summary, tags, parameter names, referenced schema names) and schemas (name, property names, title, description). Matches above zero are selected.
   - By explicit ids: `--select` accepts operationIds, `METHOD /path`, bare paths, schema names, and JSON pointers (`#/components/schemas/Pet`, `#/$defs/Order`). Unknown ids fail loudly by name, exit 2.
   - `--all` keeps everything reachable from nothing (full document, pruned only of nothing): an escape hatch and a baseline for token comparison.
3. Reachability and reduction (JSON specs, the full treatment)
   - From the selected operations/schemas, follow local $refs (`#/ ...`) transitively. Every reachable node is kept; everything else in paths/components/$defs is dropped and listed in the manifest.
   - Remote $refs (http(s) URLs, file paths, anything not starting with `#/`) are NEVER fetched. Static parsing only, no network. They are left in place in the output and recorded in the manifest as unresolved, with the pointer they were referenced from.
   - OpenAPI output keeps `openapi`, `info`, `servers`, filtered `tags`, kept path items (with their path-level parameters), pruned `components` (schemas, responses, parameters, requestBodies, headers, examples, securitySchemes referenced by kept operations), and root `security` only when its schemes survive.
   - JSON Schema output keeps the root shell ($schema, title), a pruned $defs/definitions containing only reachable defs, and when exactly one def is selected and the root is not, a root $ref to it (multiple selected defs become an anyOf of $refs).
   - The reduced document must still parse, and every local $ref inside it must resolve inside it. That is self-checked before writing; a failure is a build bug, reported as exit 2, never shipped silently.
4. GraphQL SDL: outline only
   - Parse type-system definitions statically (type, interface, input, enum, union, scalar, schema, extend): names, kinds, fields with their types, enum values, union members.
   - Reachability by name: from selected types (by --select name or task terms), follow field return types, argument types, implemented interfaces, and union members.
   - Output is an OUTLINE: outline.json + OUTLINE.md listing kept types and their fields, dropped type names in the manifest. Every artifact is labelled outline in its content and in the manifest (`treatment: outline`). An outline is never presented as a complete reduced schema, and no .graphql file is emitted, because SDL reachability by name cannot prove a partial SDL document is still valid or complete.
5. Manifest and summary
   - manifest.json: tool + version, generated_at, source path + sha256 + bytes, format, treatment (reduced or outline), token method, original/sliced/saved token estimates, selection echo, kept lists, dropped lists, unresolved remote refs with referrers, warnings.
   - SCHEMA.md: the same in plain words for a human skimming the bundle.
6. MCP tools (stdio, local only)
   - `schema_slice` and `schema_inspect` with capped summary payloads (manifest fields and listings, no spec bodies), same discipline as Slice MCP.

## Out of scope for v0.1
- YAML specs of any flavour. Refused, not approximated.
- Swagger / OpenAPI 2.0. Refused with a pointer to convert to 3.x first.
- Fetching or resolving remote $refs. No network at all in v0.1.
- Validating a spec against the OpenAPI or JSON Schema meta-schemas. GhostSchema proves internal $ref closure of the reduced output, not spec correctness.
- Emitting a reduced GraphQL SDL document. Outline only, by design (see MVP item 4).
- Code generation, client stubs, mock servers, or calling the API described.
- Editing the input spec, or writing anywhere outside the output bundle directory.
- Cloud, accounts, telemetry, paid layer.

## Build estimate
- Loader + classification + YAML/Swagger refusal: 1 day
- $ref graph + reachability closure + OpenAPI reduction: 2-3 days
- Standalone JSON Schema reduction ($defs pruning, root ref/anyOf): 1-2 days
- SDL outline parser + name reachability: 2 days
- Manifest, SCHEMA.md, MCP, self-check: 1-2 days
- Tests (planted unreachable schemas, external-ref fixtures, SDL fixtures), README, examples: 2 days (Agent B, in parallel)
Total: roughly 1.5 to 2 weeks to a verified v0.1 if built straight through. SDL parsing is the part most likely to slip; it is outline-only precisely so a parser gap degrades to a missing type in the outline, which the manifest can list, instead of a corrupt reduced schema.

## Pricing draft (NOT public, NOT decided)
- MIT core CLI free, same pattern as Slice / Seatbelt / Ghost Hands.
- Paid candidate later only: team spec-library packs / hosted bundle history. Do not build a paid layer before a free launch validates demand.

## Verification bar
- Planted-waste test: a fixture OpenAPI spec with an operation chain A -> B -> C and an unrelated operation + schema set. Slicing by the task that names A must keep A, B, C and drop the unrelated set, by name, in the manifest.
- Closure test: every local $ref in every reduced output resolves inside that output. Automated, runs on every fixture.
- External-ref test: a fixture with an https $ref. The run must not touch the network, must keep the ref visible in the output, and must list it as unresolved in the manifest.
- YAML test: .yaml input and YAML content in a .json file both refuse with the YAML message and exit 2. Input file hash unchanged after every run, refused or not.
- SDL test: outline for a fixture schema names the reachable types and fields, drops the unreachable type by name, and the word outline appears in outline.json, OUTLINE.md, and the manifest treatment field.
- Token honesty: manifest original estimate equals the estimator applied to the untouched source text; sliced estimate equals the estimator applied to the emitted spec text.

## Risks / honest notes
- Task-term selection is lexical, same class of heuristic as `ghostslice task`. It will miss operations whose names share no words with the task. Explicit --select is the precise route and the README must say so.
- $ref graphs can hide references in places a static walker must be careful to visit (allOf/anyOf/oneOf, nested properties, parameters, examples are skipped as data, not refs, unless they contain a literal $ref key, which the walker does follow). The closure self-check is the safety net: if it ever fails, the run fails loudly.
- SDL parsing is regex-and-brace matching, not a full GraphQL grammar. Descriptions, directives with parentheses, and extend blocks are handled best-effort; the outline lists what it parsed and the manifest warns that SDL parsing is outline-grade. That is why SDL never gets the full treatment in v0.1.
- A reduced spec is a reading aid for an agent, not a deployable API contract. Copy must say so: do not ship the reduced spec as the API's source of truth.

## Next gate
Ryan's go on: (1) GhostSchema as working name, (2) JSON-first scope with YAML refused rather than approximated, (3) SDL outline-only with the labelling rule, (4) remote $refs listed, never fetched.
