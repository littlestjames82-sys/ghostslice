# GhostShard - Multi-Agent Task Sharder for GhostSlice and GhostBus
Working name, prepared Oct 14, 2026. Paired tool #8 for GhostSlice.
Decision: NOT Goliath. Goliath stays reserved for a non-agent product (Ryan, Oct 11-12, 2026). Note: the rejected Goliath hunt item "agent fleet runner pivot" stays rejected. Shard is not a fleet runner, see the boundary section below.

## Why this name
- GhostShard: it shards one large task into packets. Each shard is a self-contained Slice bundle plus instructions for one job.
- Reserve alternative: GhostSplit (plain, but reads as a file splitter). Shard keeps the distributed-work meaning.
- Treat as a working name until a name check runs at build gate, same discipline as GhostSlice Oct 12.

## The boundary that keeps this honest
GhostBus owns transport and coordination between agents (hosted relay, per-workspace pricing decided Oct 11, 2026: Starter $15/mo, Pro $29/mo, Studio $99/mo, execution still gated on Ryan's Stripe + Hetzner signups). Agent Seatbelt owns governing agent actions. Ghost Hands owns the browser body.

Shard owns exactly one thing: **planning the packets**. It reads a project and a large task, and produces an ordered set of shard bundles with dependencies. It does not run agents, dispatch work, host a relay, approve actions, or merge results in v0.1. Dispatch, when it happens, is GhostBus's job, run under Seatbelt, and is a separate Ryan gate after Shard's plan format is proven by hand.

## The problem
A large task on a large repo breaks single-agent work two ways:
- One agent with the whole repo context pays full price and still loses the thread across a long job.
- Hand-splitting the work is slow and error-prone: people split by folder, not by dependency, so parallel jobs collide on shared files and shared symbols.

The split should come from the dependency graph: jobs that touch disjoint call subgraphs can run in parallel, jobs that share a symbol must be sequenced, and each job should carry only its own subgraph as context.

## Position in the Ghost stack
- GhostSlice: one bundle for one task.
- GhostShard: many bundles for one large task, ordered, with collisions named up front.
- GhostVerify: can check each shard bundle (pre) and each shard's returned patch (post) using its existing commands, per shard.
- GhostBench: can score sharded vs single-agent runs in Tier B, once Shard exists.
- GhostBus + Seatbelt: the future execution layer, gated, not part of Shard v0.1.

## How it pairs with GhostSlice, concretely
Reuses, does not rebuild:
- Task selection (TF-IDF) to find the task-relevant symbol set, then call graph + import graph expansion to grow it into subgraphs.
- Clustering by graph: shards are formed around graph communities / workspace packages (Slice monorepo detection gives package boundaries as natural shard seams), not by directory listing.
- Per-shard bundle: an ordinary Slice bundle per shard (own manifest, own fit ladder against a per-shard budget) plus a top-level `shards.json` plan: shard id, task slice (the sub-prompt for that shard, written by the user or split from a task file, never invented), depends-on, shared symbols, files owned, files read-only-shared.
- Ownership rule: a file or symbol is *owned* by exactly one shard. Other shards that need it get it at signatures/interfaces as read-only context and are sequenced after the owner if they depend on its output. Collisions that cannot be resolved by ordering are reported as plan conflicts, not papered over.
- Estimator + prices: plan shows per-shard estimated tokens and a total, compared against the single-bundle estimate for the same task, labelled estimates with the same price table date.
- Recall + Verify hooks: a combined plan can attach the same GhostRecall memory items to every shard (pinned rules in each) and record a GhostVerify pre verdict per shard bundle in the plan file when Verify is present.

## MVP (v0.1) - planner only, files out, no execution
1. Plan: `ghostshard plan <project> --task "..."` or `--task-file <file>`
   - Task-file format for pre-split work: a simple documented format where the user lists sub-tasks. Auto-splitting a freeform task into sub-tasks without a model is heuristic (graph clustering of the relevant symbol set) and the plan labels which mode produced it: user-split or auto-clustered.
   - Output: `shards/` folder with one Slice bundle per shard, `shards.json`, and `PLAN.md` for humans: shard table (job, owns, depends on, estimated tokens, parallel group), the dependency diagram as a text/Mermaid graph, conflicts list.
   - Parallel groups: shards with no dependency path between them are grouped. The plan states the max useful parallelism (largest group size) rather than implying infinite agents help.

2. Fit and limits
   - Per-shard budget from profile (default suggestion: the same budget a user would give one agent run, stated as a default, not a finding). A shard that cannot fit is split further by graph or reported unfittable with its graph reason, following Slice `--fit` exit discipline.
   - Hard caps in profile: max shards, max shared-symbol fan-out. Hitting a cap produces a partial plan marked partial, never a silently truncated complete-looking plan.

3. Check: `ghostshard check <shards-folder>`
   - Validates every shard bundle with Slice check logic, validates `shards.json` (ownership uniqueness, dependency graph is acyclic, every depends-on target exists).
   - A cycle in shard dependencies is a plan failure with the cycle printed, not a scheduling problem to solve at run time.

4. Handoff export (format only, no sending)
   - Emits a GhostBus-shaped job manifest (documented JSON, one entry per shard: bundle path, sub-task, depends-on, approval class placeholder for Seatbelt) that a person can inspect and, at a later gate, hand to GhostBus.
   - v0.1 does not contact the GhostBus relay, hosted or local. The manifest is a file.

## Out of scope for v0.1
- Running, dispatching, retrying, or merging agent jobs. Merging shard patches is future work that belongs with Verify post, not Shard.
- Any LLM call to split tasks, judge shard quality, or write sub-prompts. User-split or graph-clustered only, labelled.
- Hosted planning, shared plans, accounts, telemetry.
- Cross-repo sharding. One project (monorepos count as one project via Slice workspaces).

## Build estimate
- Graph clustering + ownership/dependency planner: 4-5 days (the core algorithm, estimate reflects that)
- Per-shard bundle generation + fit + plan artifacts: 3 days
- Check command + Bus-shaped manifest export: 2 days
- Tests (disjoint fixture that must parallelise, shared-symbol fixture that must sequence, cycle fixture that must fail, unfittable fixture): 2-3 days
Total: roughly 2 to 2.5 weeks to a verified v0.1 if built straight through.

## Pricing draft (NOT public, NOT decided)
- MIT core planner free, same pattern as Slice.
- Monetisation, if any, belongs to the execution layer (GhostBus hosted pricing is already decided separately). Do not attach a second price to the planner before the gated Bus execution even exists.

## Verification bar
- Disjoint test: a fixture with two independent subgraphs yields two shards in one parallel group, zero shared owned files.
- Collision test: a fixture where two sub-tasks touch one shared symbol yields sequencing or a named conflict, never two owners.
- Reproduction test: plan totals equal the sum of the shard bundle manifests, and every shard bundle passes `ghostslice check`.
- Honesty test: auto-clustered plans are labelled auto-clustered in PLAN.md and shards.json, user-split plans are labelled user-split. No plan presents a heuristic split as a designed one.

## Risks / honest notes
- Bad splits are worse than no split: a wrong seam creates merge pain that eats the token saving. Conservative rule for v0.1: when the graph is ambiguous, sequence shards (safe, slower) rather than parallelise (fast, risky), and say which rule fired.
- Graph quality bounds plan quality: parser-lite languages give import-level seams only, plans for those projects must state the seam basis per shard.
- The temptation to build the runner is the scope risk. The v0.1 gate is files out. If a plan cannot be executed by hand comfortably, the plan format is wrong and that is the finding to fix first.

## Next gate
Ryan's go on: (1) GhostShard as working name, (2) planner-only v0.1, no dispatch, no merging, with GhostBus execution as a separate later gate, (3) conservative sequencing over parallelism when the graph is ambiguous, (4) build slot: Shard is #8 in the suite, after the single-agent companions are proven.
