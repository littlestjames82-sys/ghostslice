# GhostAtlas - Human Codebase Map Built on GhostSlice
Working name, prepared Oct 14, 2026. Paired tool #7 for GhostSlice.
Decision: NOT Goliath. Goliath stays reserved for a non-agent product (Ryan, Oct 11-12, 2026).

## Why this name
- GhostAtlas: an atlas is a book of maps for people. This is the one suite tool whose primary reader is a human, not an agent.
- Reserve alternative: GhostMap (short, but generic and likely crowded in mapping and in dev tools).
- Treat as a working name until a name check runs at build gate, same discipline as GhostSlice Oct 12.

## The problem
Slice answers an agent's question: what should I read for this task. People joining or evaluating a codebase have a different question that nothing in the stack answers: how does this thing fit together, and where do I start.

Today that means days of reading READMEs that describe the project that was planned, folder trees that say nothing about importance, and asking the one person who knows. For Ryan's studio the cases are concrete: onboarding help onto a client codebase, a buyer or partner doing diligence on a repo, Ryan himself returning to a parked project (DevPulse class of problem) and needing the shape back fast.

The data to answer it already exists inside Slice: token heat, import graph, call graph, entry points, dead-code candidates, workspace layout, history. It is just never presented as a map for a person.

## Position in the Ghost stack
- GhostSlice: agent context, token-first.
- GhostAtlas: human orientation, structure-first, built entirely on Slice data.
- GhostRecall holds decisions and rules in text form. Atlas is the visual/narrative front door that can point at Recall content, it does not replace it.
- No overlap with the Slice dashboard: the dashboard is an operator console for making bundles. Atlas output is a finished, shareable artifact a non-operator can read without running anything.

## How it pairs with GhostSlice, concretely
Reuses, does not rebuild:
- Scanner, workspaces detection, detect (generated/minified/vendored) and duplicates: Atlas sections are views over these exact results, same project state, same run stamp.
- Import graph + call graph: the map edges. Python call edges complete, other languages import-level and labelled parser-lite on the map itself, not in a footnote.
- Entries: Slice entry-point signals power the "start here" ranking, with the evidence shown per pick (manifest bin, __main__ guard, name signal, shebang), reusing the `init` wizard's evidence style.
- Token estimator: heat on the map is token cost, labelled estimates, same numbers a scan prints. Atlas never shows a second, different size metric.
- Report engine pattern: Slice's standalone single-file HTML `report` is the delivery model. An Atlas file opens offline, no server, no network calls, same as Slice reports.
- Profile: reads `.ghostslice.json` for project name/ignores, adds an `atlas` section (title, audience notes, hidden paths). Unknown keys fail loudly, per house rule.

## MVP (v0.1) - one self-contained HTML artifact + a Markdown brief
1. Map generation: `ghostatlas build <project> -o atlas.html`
   - Module map: packages/workspaces as regions, files as nodes sized by estimated tokens, edges from the import graph, generated/vendored collapsed and labelled.
   - Heat toggle: by token cost, by caller count (most depended-on), by change activity from local git log where available (labelled with the window used).
   - Every view is static SVG/HTML generated locally, no external assets, no JavaScript from a CDN. Interaction is local pan/zoom and toggles only, following Slice's safe-rendering discipline (textContent-only patterns where data is injected).

2. Start-here reading order
   - Ranked list, top 10 by default: entry points first, then most-depended-on modules, then the README/docs Slice would include, each with a one-line factual reason (depended on by N files, entry point from package manifest) and an estimated reading token/time cost.
   - Dead zones panel: dead-code candidates, unreferenced docs, and duplicate clusters, framed as "worth asking about", never as "delete this". Atlas states observations for a human to judge.

3. Architecture brief: `ATLAS.md`
   - Generated from the same run: layout, entry points, main flows visible in the call graph (top call chains, capped and labelled as sampled from static analysis), data/config hotspots, test layout and covering shape, known warnings carried from Slice lint with their existing explanations.
   - Extractive and factual only in v0.1: no LLM-written prose, no invented descriptions of what a module "does" beyond names, paths, docstring first lines (Slice already extracts those for signatures mode), and graph facts. If a module has no docstring, the brief says so instead of guessing.

4. Diligence mode (same artifact, a flag)
   - `--audience diligence` reorders the brief: size and shape, test presence, secrets guard result (counts and types only), dependency surface from manifests, licence files found, history span from git. For handing to a buyer, partner, or client.
   - It reports what was checked and what was not checked in an explicit box. It is an orientation aid, not an audit opinion, and the artifact says so. Security audit claims belong to GhostExposure's scope, not Atlas.

## Out of scope for v0.1
- LLM narration, auto-written module summaries beyond extracted first lines, chat-about-your-codebase features.
- Editing, refactoring suggestions as directives, or any write to the project.
- Hosted sharing, live collaborative maps, accounts. Sharing an Atlas means sending the file.
- Runtime tracing, profiling data, or executing the project to build the map. Static only, like Slice.
- Diagram export formats beyond the HTML artifact + ATLAS.md (no draw.io / Mermaid round-trip promises in v0.1; a Mermaid text export of the import graph is a v0.2 candidate).

## Build estimate
- Data assembly over Slice results + run stamping: 2 days
- Static map rendering (SVG layout, heat toggles, collapse rules): 4-5 days (the visual piece, estimate is honest that layout is the work)
- Reading order + brief generation: 2-3 days
- Diligence ordering + tests (fixture repos with known entry points and dead zones), README, demo on GhostBus + one parked Ryan project: 2 days
Total: roughly 1.5 to 2 weeks to a verified v0.1 if built straight through.

## Pricing draft (NOT public, NOT decided)
- MIT core generator free, same pattern as Slice.
- Paid candidate later only: a diligence/onboarding pack service for client work, delivered by the studio rather than sold as software. That is a studio services decision for Ryan, not a software paywall in v0.1.

## Verification bar
- Ground-truth fixture: on a fixture repo with known entries, graph, and dead file, the map edges, reading order top pick, and dead zone list must match the fixture's stated truth.
- Consistency test: every number in ATLAS.md equals the number from a same-run `ghostslice scan` / `graph` output. A mismatch fails the build.
- Offline test: the generated HTML makes zero network requests when opened (checked in the test harness), and contains no secret-shaped string from a planted fixture.

## Risks / honest notes
- A pretty map can imply more understanding than static analysis has. Parser-lite labelling, sampled-chain labelling, and the checked/not-checked box exist to keep the artifact honest.
- Layout quality makes or breaks it: a tangled auto-layout is worse than a good table. If the map view does not beat the Slice dashboard tree on a real repo in testing, v0.1 should ship brief-first and hold the map as experimental, stated plainly.
- Docstring-free codebases will produce sparse briefs. That sparseness is information, present it as such rather than padding prose.

## Next gate
Ryan's go on: (1) GhostAtlas as working name, (2) extractive facts only, no LLM prose in v0.1, (3) self-contained file as the share unit, no hosting, (4) build slot: Atlas is #7 in the suite, and is the most deferrable without hurting the others.
