# GhostPrimer - First-Session Starter Bundle for GhostSlice
Working name, prepared Oct 14, 2026. Paired tool #24 for GhostSlice (Wave 4).
Decision: NOT Goliath. Goliath stays reserved for a non-agent product (Ryan, Oct 11-12, 2026).

## Why this name
- GhostPrimer: a primer is the short book you read first. This tool builds the small pack a new agent session, or a new hire driving one, should read before anything else in a project.
- Checked against the family: GhostAtlas is the full human map of a codebase, GhostRecall slices project memory for a task. Primer is neither. It is the minimal first-session pack, code plus memory, sized to be read whole.
- Alternatives held in reserve: GhostOnboard (implies HR process and account setup, which this never does), GhostStarter (too close to starter-pack naming in GhostPacks, which are profile data packs, a different thing).

## The problem
Every new agent session on an existing project starts cold. The agent either gets the whole tree (expensive, mostly waste) or a task slice from GhostSlice (right for a known task, wrong for day one, when there is no task yet, just "get oriented"). The human version is the same: a new hire opens a repo and reads files in directory order.

What a first session actually needs is small and predictable:
- What this project is (name, description, entry points, how it is laid out).
- The handful of files everything else depends on, at readable depth.
- The project memory that is already written down: standing decisions, agent instructions committed to the repo, the latest changelog entry, the plan or roadmap headings.
- An honest list of what was NOT included, so the reader knows the pack is a starter, not the project.

Today that pack is assembled by hand, or not at all, and the agent burns its first expensive run rediscovering entry points and re-asking decisions the project already recorded.

## Position in the Ghost stack
- GhostSlice governs what an agent READS for a task (scanner, AST slicer, token estimator, .claude_context bundle with manifest + sha256).
- GhostRecall governs project MEMORY for a task: it selects decisions, notes, and docs from project-local sources with provenance, supersession, and conflict handling.
- GhostAtlas is the full human MAP: whole-codebase structure rendered for a person, meant to be browsed.
- GhostPrimer is the first-session pack: it composes a minimal code slice plus a memory primer into one small bundle a new session reads whole. It is the front door, not the map and not the task slice.
- Agent Seatbelt governs what an agent DOES. GhostVerify governs whether a slice was ENOUGH.

Story: Primer (session one) -> Recall + Slice (per task) -> Verify (pre/post) -> agent runs under Seatbelt. Atlas sits beside the story for the human.

No overlap, stated plainly:
- Primer is not a map. It does not try to cover the codebase; it deliberately covers a starter subset and names the rest as not included. Atlas covers.
- Primer does not reimplement Recall. When a GhostRecall bundle is supplied, Primer consumes it: it takes the bundle's selected, current memory items as its memory source. Without one, Primer falls back to a fixed, shallow pass over well-known project-local memory files (headings and capped section extracts), and says so in the bundle. Task-level memory selection, supersession logic, and conflict detection stay Recall's job.

## Hard rules
- Project-local sources only. Every code file and every memory item must resolve inside the project root. Anything outside the root is refused, by path check, not by convention.
- Muse's private memory is excluded by rule: the user's `~/MEMORY.md` and `~/memory/` tree are never read, never copied, and a source path resolving into them is refused even if passed explicitly. Primer primes from the project's own record, not from the assistant's.
- Extractive facts only. No LLM, no summarising model, no generated prose about the code. The only prose in the bundle is labelled template text (section headings and fixed framing lines, marked as template in the manifest). Everything else is copied or structurally derived from project files: metadata fields, signatures, docstring first lines, headings, and verbatim section extracts with provenance.
- Secrets guard: memory extracts and code files are scanned for secret-shaped literals; a flagged memory item is blocked (recorded, not included), a flagged code file is excluded and named, same discipline as Recall and Slice.
- Local only, Python stdlib only, no network. No accounts, no telemetry.

## How it pairs with the stack, concretely
- GhostSlice: Primer's bundle follows the Slice bundle schema (manifest with per-file original_tokens / sliced_tokens / sha256 and top-level integer totals) and uses Slice's calibrated token estimator when Slice is importable (package, sibling checkout, or GHOSTPRIMER_GHOSTSLICE_SRC), so a Primer bundle can be validated by `ghostslice check`. The code slice reuses Slice's mode names (full, signatures, outline). Primer builds its starter selection itself (entry points plus highest fan-in modules); it does not replace Slice export for task work.
- GhostRecall: `--recall-bundle <dir>` consumes a Recall bundle's manifest and its exported memory item files verbatim, filtered to items Recall marked current (not superseded, not excluded, not blocked). Primer records which path it took (recall-bundle or shallow fallback) in the manifest.
- GhostAtlas: no code shared in v0.1; the distinction is scope and audience, documented above.

## MVP (v0.1) - local CLI first
1. Build: `ghostprimer build <project> -o <bundle> [--budget N] [--recall-bundle <dir>] [--task "..."]`
   - Project facts block: name, version, description, language mix, entry points, top-level layout, extracted from pyproject.toml / package.json / README and the tree itself. Fields that cannot be found are recorded as not found, never invented.
   - Code starter slice:
     - Entry-point files at signatures mode (Python via real `ast`; JS/TS parser-lite, labelled; other languages head excerpt, labelled).
     - Highest fan-in modules (import graph) at signatures, then outline, until the code share of the budget is spent.
     - README extract: title, headings, and the first paragraph under each heading, capped.
   - Memory primer:
     - From a supplied Recall bundle when given (current items only, verbatim, with Recall's provenance).
     - Otherwise a shallow fallback pass over a fixed list of project-local files when present: AGENTS.md, CLAUDE.md, DECISIONS.md and docs/decisions/, CHANGELOG.md (latest entry only), CONTRIBUTING.md, PLAN.md, ROADMAP files. Headings plus capped section extracts, each item with file + line provenance.
     - Memory share capped (default 40 percent of budget) so memory cannot crowd out code.
   - Budget fit: default budget 6,000 estimated tokens. Downgrade ladder is signatures -> outline -> exclude, largest first. Entry points are never dropped below outline. If the budget cannot be met, the bundle is still written and the unmet budget is reported, never hidden.
   - Output: `PRIMER.md` (the pack itself: facts, start-here list, code slice, memory primer, not-included list, limits), `manifest.json` (Slice-schema files plus memory items with provenance, totals, token method, primer sha256), and `files/` with the sliced code.
2. Check: `ghostprimer check <bundle>`
   - Recomputes file hashes and totals, verifies PRIMER.md against the manifest sha, verifies every recorded source path resolves inside the recorded project root, and verifies no memory item came from the excluded private-memory locations. Exit 0 pass, 1 fail with reasons, 2 could not check.
3. Doctor: `ghostprimer doctor <project>`
   - Reports which primer sources exist or are missing (entry points, README, each memory file, a Recall bundle if one is present), the estimator in use, and the default budget outcome on this project. Read-only.
4. MCP tools (stdio, local only)
   - `primer_build` and `primer_check` with capped summary payloads, no raw file bodies by default, same discipline as Slice MCP.

## Out of scope for v0.1
- Calling any model, generating summaries, or writing orientation prose about the code. Extractive only, forever the point of this tool.
- Task-specific slicing (Slice and Recall own that), whole-codebase coverage or rendering (Atlas owns that), and memory selection logic beyond the shallow fallback (Recall owns that).
- Reading anything outside the project root, including the user's private memory, shell history, or other projects.
- Onboarding actions: no account setup, no environment install, no running the project. Primer produces reading material only.
- Cloud, accounts, telemetry, paid layer.

## Build estimate
- Project discovery + facts extraction: 1-2 days
- Starter selection (entry points, fan-in graph, budget ladder): 2 days
- Python signatures slicer + parser-lite outlines: 1-2 days
- Memory primer (Recall-bundle consumption + shallow fallback + provenance): 2 days
- Bundle writer + check + doctor + MCP: 1-2 days
- Tests (fixture projects, planted secret in memory file, outside-root refusal, Recall-bundle fixture), README, examples: 2 days
Total: roughly 1.5 to 2 weeks to a verified v0.1 if built straight through.

## Pricing draft (NOT public, NOT decided)
- MIT core CLI free, same pattern as Slice / Seatbelt / Ghost Hands.
- Paid candidate later only: team onboarding packs bundled with GhostPacks distribution. Do not build a paid layer before a free launch validates demand.

## Verification bar
- Fixture test: on a fixture project with known entry points, the starter slice contains the entry points at signatures and the highest fan-in module; a file nothing imports and no entry point references is not included and appears in the not-included list.
- Recall consumption test: given a Recall bundle fixture with one current and one superseded decision, the primer includes the current one and not the superseded one, and the manifest records the recall-bundle path.
- Exclusion test: a memory source path outside the project root, and one pointing into the user's private memory locations, are both refused; nothing from them appears in the bundle.
- Secret test: a planted secret-shaped literal in a project memory file blocks that memory item; it is recorded as blocked and its text does not appear in PRIMER.md.
- Cross-check: a Primer bundle on a Python fixture passes `ghostslice check` with totals reproduced, and `ghostprimer check` passes on the same bundle and fails it after a one-line tamper of PRIMER.md.
- Budget test: an impossibly small budget still produces a bundle, reports the budget unmet, and never drops an entry point below outline.

## Risks / honest notes
- The shallow memory fallback is deliberately dumb: headings plus capped extracts will miss decisions buried mid-paragraph. That is accepted in v0.1 and is exactly why the Recall-bundle path exists; the bundle states which path produced its memory section.
- Fan-in is a proxy for importance, not importance itself. A generated or vendored file can rank high; the profile can exclude paths, and the not-included list keeps the choice auditable.
- Parser-lite outlines for non-Python languages can mis-attribute nested declarations; every non-Python file's mode confidence is labelled in the manifest.
- Extractive facts can still be wrong if the project record is wrong (a stale README, a lying changelog). Primer cites provenance for every item so a reader can check the source in one hop.

## Next gate
Ryan's go on: (1) GhostPrimer as working name, (2) CLI-first with the Slice-schema bundle, (3) the private-memory exclusion rule as written, (4) build order within Wave 4 (all 10 at once per his dispatch).
