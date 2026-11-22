# GhostScope - PR and Diff Review Slicer for GhostSlice
Working name, prepared Oct 14, 2026. Paired tool #5 for GhostSlice.
Decision: NOT Goliath. Goliath stays reserved for a non-agent product (Ryan, Oct 11-12, 2026).

## Why this name
- GhostScope: it scopes a review to what actually matters in a change. Reviewers scope work all the time, the name matches the habit.
- Reserve alternative: GhostReview (generic and crowded, likely taken by review bots). Scope also avoids confusion with GhostVerify post, which checks a patch in a temp copy. Scope prepares the reading, Verify runs the check.
- Treat as a working name until a name check runs at build gate, same discipline as GhostSlice Oct 12.

## The problem
Code review today forces a bad choice:
- Read the diff alone and miss that a one-line change to a shared function breaks 14 callers.
- Or read the whole repo area and drown, so the review becomes a rubber stamp.

Agent reviewers have the same problem with a token bill attached. A raw PR diff has no callers, no callees, no covering tests, no history of the touched symbols. A full-repo bundle has all of that at full cost, most of it irrelevant to this change.

What a reviewer, human or agent, actually needs is change-centred context: the change in full, everything it touches in proportion to risk, and nothing else.

## Position in the Ghost stack
- GhostSlice builds task-centred bundles from a project.
- GhostScope builds change-centred bundles from a diff.
- GhostVerify post checks a patch the agent produced. Scope is for reviewing a change someone (or some agent) already produced, before it merges. Adjacent, not overlapping: Verify verdicts are pass/fail evidence in a temp copy, Scope output is a ranked reading pack with a risk view.
- Agent Seatbelt governs actions, Ghost Hands is the body. Scope governs review reading only.

## How it pairs with GhostSlice, concretely
Reuses, does not rebuild:
- Git changed-files and bundle diff: Slice already detects changed files and diffs bundles by manifest. Scope starts from a git range, a PR-style diff file, or staged changes.
- Call graph + import graph: callers (who breaks if this changes), callees (what this depends on), dead-code candidates excluded from risk. Python edges are complete in Slice v1.0.6, other languages are import + outline level and labelled parser-lite.
- Symbol slicing: changed symbols at full, direct callers/callees at signatures, second-degree neighbours at interfaces only. That ladder is Slice modes, applied by graph distance.
- Test mapping: tests that import or call a changed symbol are the covering set. Slice already flags test files and strips tests as a mode; Scope inverts it and treats covering tests as first-class review context.
- Estimator, prices, manifest, check: a Scope pack is a normal Slice bundle plus a `scope.json` sidecar (base, head, per-file graph distance, risk reasons). `ghostslice check` must still validate it.
- Secrets guard + lint: a changed file that introduces a secret shape or a lint error is raised in risk, using Slice rules, not new ones.

## MVP (v0.1) - local CLI, local git only, no hosting API
1. Input: `ghostscope pack <project> --base <ref> --head <ref>` or `--diff <file.diff>` or `--staged`
   - Parses the diff into changed files + changed symbols (Python ast exact, other languages parser-lite by hunk position, labelled).
   - Refuses a diff that does not match the working tree state it claims, with the mismatch named. No silent wrong-base packs.

2. Blast radius and risk ranking
   - Computes for each changed symbol: direct callers, transitive callers (capped depth, cap shown), covering tests, whether it is an entry point or exported API surface (Slice entries + `__all__` / plugin contract signals).
   - Risk reasons are explicit and listed per item, never a bare score: "exported API", "23 callers", "no covering test", "touches auth path in profile", "secret-shaped line added". A single summary score may be shown only next to its reasons.
   - Profile section `scope`: paths the user marks sensitive (auth, payments) always raise risk. No built-in sensitive-path guesses beyond what the profile says.

3. Review pack export
   - Bundle layout: changed files full, distance-1 neighbours signatures, distance-2 interfaces, covering tests full for changed symbols only, plus `REVIEW.md`: change summary by file, risk list in order, reading order (riskiest first), token total vs repo total vs raw diff total, all labelled estimates.
   - Reading order is the product for humans. For agents the same pack is the prompt, via the normal Slice presets.
   - `--fit <tokens>` uses Slice's fit ladder, but changed files are never downgraded. If it cannot fit without touching changed files, pack is written and exit is 1, matching Slice `--fit` behaviour.

4. Review notes, not review decisions
   - Scope can attach factual notes to a pack (a symbol changed signature, a caller was not updated in this diff, a covering test was deleted in this diff). Each note cites file + symbol.
   - Scope does not approve, request changes, comment on a PR, or call any model in v0.1. It prepares reading and states facts.

5. MCP tools
   - `scope_pack`, `scope_explain` (why a file is in the pack, at what mode, with its risk reasons) on the Slice stdio pattern, capped payloads.

## Out of scope for v0.1
- GitHub/GitLab API, PR fetching, posting comments, CI status, merge actions. Local git and diff files only. Hosting integration is a separate gate because it needs credentials.
- Style review, naming opinions, LLM-written review prose.
- Cross-repo changes. One project, one diff.
- Replacing Verify post. Scope does not apply patches or run tests in v0.1; it names covering tests, Verify runs them.

## Build estimate
- Diff parsing + changed-symbol mapping: 3 days
- Graph distance slicing + risk reasons + covering tests: 3-4 days
- Pack export + REVIEW.md + fit + MCP: 2-3 days
- Tests (planted high-blast-radius fixture, signature-change-with-stale-caller fixture, deleted-test fixture), README, demo on a real GhostSlice PR-sized change: 2 days
Total: roughly 1.5 to 2 weeks to a verified v0.1 if built straight through.

## Pricing draft (NOT public, NOT decided)
- MIT core CLI free, same pattern as Slice.
- Paid candidate later only: hosted PR integration for teams. Do not build before a free launch validates demand.

## Verification bar
- Fixture test: a one-line change to a widely-called fixture function must rank above a 200-line change to an isolated fixture file, with the caller count as the stated reason.
- Completeness test: every direct caller of a changed exported symbol in the fixture is in the pack at signatures or better. A missing caller fails the build.
- Honesty test: a change with no covering tests says so in REVIEW.md in plain words, it does not lower the risk silently.
- Pack validates with `ghostslice check`, totals reproduce from the manifest.

## Risks / honest notes
- Test-to-code mapping is heuristic for non-Python languages (import/name based). Label the method per language in the pack, do not present a guessed covering set as proven.
- Risk ranking will be argued with. That is why reasons are mandatory and the score is secondary. A black-box score would kill trust in the tool.
- Large generated or vendored changes swamp a diff. Slice generated/vendored detection carries over and collapses those hunks in the reading order, listed, not hidden.

## Next gate
Ryan's go on: (1) GhostScope as working name, (2) local git only in v0.1, no hosting API, (3) factual notes only, no approval/comment features, (4) build slot: Scope is #5 in the suite, first of the second wave.
