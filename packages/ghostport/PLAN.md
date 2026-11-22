# GhostPort - Migration Slicer and Workbench for GhostSlice
Working name, prepared Oct 14, 2026. Paired tool #9 for GhostSlice.
Decision: NOT Goliath. Goliath stays reserved for a non-agent product (Ryan, Oct 11-12, 2026).

## Why this name
- GhostPort: porting is the established word for moving code across versions, frameworks, and languages. The tool ports a codebase one proven slice at a time.
- Reserve alternative: GhostMigrate (also clear, slightly more generic). Port is shorter and matches the one-slice-at-a-time image.
- Treat as a working name until a name check runs at build gate, same discipline as GhostSlice Oct 12. Port has many uses in software, so the check should look specifically at migration-tool collisions.

## The problem
Version and framework migrations (Python minor/major, Node LTS, React class to hooks, a framework major release) share a failure shape:
- The surface that actually needs changing is a small fraction of the repo, buried in code that must not be touched.
- Handing an agent the whole repo invites unrelated edits, style churn, and regressions far from the migration.
- Handing it one file at a time loses the call graph, so a migrated callee breaks an unmigrated caller at run time.
- The work has a natural order (leaves of the dependency graph first, entry points last) that folder order does not give you.

What migration work needs is a sequence of bundles: each one contains the next unit to port in full, its already-ported dependencies as stable context, its not-yet-ported callers as signatures so the porter can keep the contract, and a checklist tied to that unit's tests.

## Position in the Ghost stack
- GhostSlice: task bundles from TF-IDF/graph selection.
- GhostPort: migration bundles from a pattern scan + dependency order. The selection signal is "matches the migration pattern", which Slice has no concept of.
- GhostVerify post is the per-unit finisher: a ported unit is a patch, Verify checks it in a temp copy and runs its tests.
- GhostShard also sequences bundles by graph, but for parallel task shards. Port sequences strictly for dependency order and pattern state (ported / not yet), single line of work. The two planners must share the graph code, not merge into one tool.

## How it pairs with GhostSlice, concretely
Reuses, does not rebuild:
- Scanner + slicer modes: each port unit is a Slice bundle (unit full, ported deps full or signatures per profile, unported callers signatures, unit's tests full).
- Call graph + import graph for ordering: topological order over the touched subgraph, cycles detected and reported as a named blocker with the cycle printed (a cycle in the touched set means the units in the cycle port together, as one combined unit, and the plan says so).
- Pattern scan is new, but built on Slice detection habits: per-migration pattern packs are data files (regex + AST checks for Python, parser-lite checks for other languages, each pattern with an id, a plain-words description, and a source doc reference with a date). Pattern hits are findings with file + line + pattern id, redaction-safe like the secrets guard.
- Profile: `.ghostslice.json` section `port` (migration pack id, pattern overrides, per-unit budget). Fit ladder per unit, same exit discipline as Slice.
- Ledger: `.ghostport-history.jsonl` records unit, bundle hash, state changes (planned, bundled, ported-claimed, verified), and the Verify report reference, so progress survives across sessions and agents. State "verified" can only be written from a GhostVerify post report, never by hand-editing the plan. Other states are user/agent claims and are labelled as claims.
- Estimator + prices: per-unit and total-remaining estimates, same table, labelled estimates.

## MVP (v0.1) - one migration pack end to end, planner + sequencer
Rationale: ship one real migration well rather than five pattern packs badly. The pack is a build-gate choice for Ryan; the suggested first pack is a Python version-upgrade pattern set (deprecated stdlib patterns with dated references), because Slice's Python support is its strongest (full ast + call graph) and Ghost's own repos give real test material.

1. Scan: `ghostport scan <project> --pack <pack-id>`
   - Lists every pattern hit: file, line, pattern id, plain-words description, the unit it belongs to.
   - Units are formed from hits by file/module + graph proximity, documented rules, no model.
   - Output includes the honest negative: files scanned with zero hits, and languages in the project the pack does not cover, named as not covered.

2. Sequence: `ghostport plan <project> --pack <pack-id>`
   - Orders units leaves-first over the touched subgraph, groups cycle members into combined units, attaches each unit's covering tests (Scope-style mapping where available, otherwise the unit's own test files, method labelled).
   - Writes `PORT_PLAN.md` (unit table in order, per-unit estimated tokens, total, blockers) + `port-plan.json`.

3. Bundle per unit: `ghostport bundle <project> --unit <id> -o <folder>`
   - The Slice bundle for that unit as described above, plus a `UNIT.md` checklist: patterns to fix in this unit with locations, contract notes (callers at signatures that must keep working), the test command from profile if any, and the state box to be filled by the Verify step later.
   - Bundle validates with `ghostslice check`.

4. Status: `ghostport status <project>`
   - Reads the Port ledger: units planned / bundled / claimed / verified, estimated tokens remaining, next unit in order. This is the resumption view for a migration that spans weeks.

## Out of scope for v0.1
- Performing the migration: no code rewriting, no auto-fixes, no codemods. Port prepares and sequences, agents and humans port. (Codemods for specific patterns are a later, per-pattern gate with their own tests.)
- Additional migration packs beyond the first, cross-language porting (for example JS to TS) as a v0.1 claim, and framework packs for stacks Slice parses only at parser-lite level, unless Ryan picks one of those as the first pack knowing the graph limits.
- Running tests itself: that remains GhostVerify post with its temp-copy guardrails.
- Tracking state anywhere except the local project ledger.

## Build estimate
- Pattern pack format + first pack + scan: 4-5 days (pattern correctness is the work, each pattern needs fixtures)
- Unit formation + graph sequencing + cycle handling: 3 days
- Per-unit bundle + checklist + ledger + status: 3 days
- Tests (per-pattern positive/negative fixtures, cycle fixture, resume-from-ledger fixture), README, demo scan on a real Ryan Python repo: 2-3 days
Total: roughly 2 to 2.5 weeks to a verified v0.1 if built straight through, for one pack.

## Pricing draft (NOT public, NOT decided)
- MIT core + first pack free, same pattern as Slice.
- Paid candidate later only: additional maintained pattern packs (framework majors change yearly, maintenance is real work). Price nothing and build no pack store until the first pack proves the format.

## Verification bar
- Pattern fixtures: each pattern in the first pack has a positive fixture it must hit and a look-alike negative it must not hit. Any false hit on the negative set fails the build.
- Ordering test: on a fixture graph, no unit is sequenced before a touched dependency it calls, cycles are combined and named.
- Ground-truth demo: scan a real repo and hand-check the first 20 hits against the files. The report on that check goes in the build report, misses included.
- State integrity test: `status` shows zero verified units until a Verify report exists in the ledger chain.

## Risks / honest notes
- Pattern packs rot: APIs deprecate and docs move. Each pattern carries its reference and date, and `ghostport scan` prints the pack version + date so a stale pack looks stale. An undated pattern is a bug.
- A migration scan that misses a pattern gives false confidence. Copy must say "no hits for pack X version Y", never "this project is ready to upgrade". The not-covered languages list exists for the same reason.
- Sequencing by static graph misses dynamic calls (registries, string dispatch). Units formed around such code can be wrongly ordered; the plan format has a manual reorder/merge override in the profile, documented, for exactly this case.

## Next gate
Ryan's go on: (1) GhostPort as working name, (2) first migration pack choice (suggested: Python version-upgrade patterns), (3) planner only, no codemods or auto-fixes in v0.1, (4) build slot: Port is #9 in the suite, and is demand-driven (build it when a real migration is on the table).
