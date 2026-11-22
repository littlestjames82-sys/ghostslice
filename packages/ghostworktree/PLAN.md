# GhostWorktree - Isolated Worktree, Port, and Env Manager for Parallel Agents
Working name, prepared Oct 14, 2026. Paired tool for GhostSlice, Wave 3 #1.
Decision: NOT Goliath. Goliath stays reserved for a non-agent product (Ryan, Oct 11-12, 2026).

## Why this name
- GhostWorktree: plain job, plain name. It manages git worktrees, the isolation primitive parallel agent work already depends on.
- Checked against the family: sits next to GhostShard the way a workbench sits next to a plan. Shard plans the split, Worktree enforces it on disk. No claim of a live product search yet. Treat as a working name until a name check runs at build gate, same as GhostSlice did Oct 12.
- Alternatives held in reserve: GhostSandbox (implies OS-level sandboxing and security isolation, which v0.1 must not claim - a worktree is filesystem and branch isolation only), GhostBench already taken by the proof harness and means something else, GhostIsolate (vague).

## The problem
GhostSlice and its companions let many agents work one codebase at once - GhostShard even plans that split - but nothing enforces the split on disk.

When two agents share one checkout:
- They collide on the same files, lockfiles, and generated output, and one agent's half-finished edit becomes another agent's context.
- They collide on local ports: two dev servers, test servers, or GhostProxy instances pick the same port and the failure looks like a code bug.
- They collide on environment: an agent copies or edits the real `.env`, risks leaking secret values into a bundle, a log, or a commit, and there is no clean per-task env to throw away.
- Cleanup is manual and dangerous: nobody remembers which checkout is dirty, and `git worktree remove` by hand is exactly how uncommitted work gets deleted.

Today this is handled by convention and by the A/B file-ownership split used for the Oct 14 companion builds. Convention does not scale past a handful of parallel tasks and it leaves no record of who owned which tree, branch, or port.

## Position in the Ghost stack
- GhostSlice governs what an agent READS (scanner, AST slicer, token estimator, `.claude_context` bundle).
- GhostShard governs how a large task is PLANNED into ordered shards (planner only, no dispatch in its v0.1).
- GhostWorktree governs where an agent WRITES: one isolated worktree, one branch, one allocated local port, and one throwaway env copy per task.
- Agent Seatbelt governs what an agent DOES (consequential actions, approvals).
- GhostVerify governs whether what it wrote back HOLDS.

Story: Slice prepares context -> Shard plans the split -> Worktree creates one isolated tree per shard -> agent runs under Seatbelt -> Verify checks the patch -> Worktree cleans the tree up, refusing to delete uncommitted work by default.
No overlap: Worktree does not slice, plan, dispatch agents, run code, or judge patches. It creates, lists, reports on, and removes worktrees.

## How it pairs with GhostSlice, concretely
Reuses, does not rebuild:
- Profile convention: respects `.ghostslice.json` if present (for example a protected branch or base ref recorded there) but never requires it and never rewrites it. Worktree keeps its own registry, it does not rewrite Slice history or profiles.
- Naming and ledger discipline: a local JSON registry with one record per worktree (name, repo, path, branch, base, port, created time), in the same spirit as Slice's `.ghostslice-history.jsonl`. No network, no telemetry.
- Secrets guard behaviour from Slice v0.4: secret values are never shown. Worktree goes further - it never reads the real `.env` at all, see the env rule below.
- Demo tree: GhostBus is the standing demo repo, and the GhostSlice companion builds themselves are the motivating multi-agent workload.

Integration contract:
- Input: a local git repository path, a task name, and optionally a branch name, a base ref, and a port or port range.
- Output: a worktree directory (default a sibling of the repo: `<repo-parent>/<repo-name>-worktrees/<name>`), a registry record, and a machine-readable JSON summary when `--json` is passed. Human output by default.
- Env rule (non-negotiable): the only env source ever copied is `.env.example` (falling back to `.env.sample`, then `.env.template`). The real `.env` is never opened, copied, or logged. Secret values are never printed: reports name the env source file only, never its contents.
- Git rule (non-negotiable): all git work is local `git` via `subprocess` only. No network git operations (`fetch`, `pull`, `push`, `clone`, `ls-remote`) in v0.1.

## MVP (v0.1) - local CLI first, dashboard panel later
Rationale: same as Slice v0.1. CLI proves the manager on real repos in days. A panel showing live trees is v0.2 once the registry shape is trusted.

1. Create: `ghostworktree create <repo> <name> [--branch <branch>] [--base <ref>] [--port <n>] [--port-range <start>-<end>] [--path <dir>] [--no-env]`
   - Validates the repo is a git working tree and the name is a safe single path component (letters, digits, `-`, `_`, `.`; no slashes, no `..`).
   - Branch defaults to `worktree/<name>`; base defaults to `HEAD`. If the branch already exists it is checked out as-is, otherwise it is created from the base ref with `git worktree add -b`.
   - Allocates a unique local port: an explicitly requested port must be free in the registry and not currently bindable on localhost, otherwise allocation fails rather than stealing it. Without `--port`, the lowest free port in the range (default 4100-4999) that is neither registered nor bindable is chosen. Allocation is recorded in the registry, so ports stay unique across trees even when no server is running yet.
   - Copies the env example (see env rule) into the new tree as `.env.example`, and seeds a throwaway `.env` from that example only. `--no-env` copies the example file but does not seed `.env`.
   - Fails cleanly, creating nothing and registering nothing, if the path already exists, the name is already registered, the branch is already checked out elsewhere, or no port is free.
   - Exit codes: 0 = created, 1 = refused or failed (reason shown), 2 = could not run (not a git repo, git missing).

2. List: `ghostworktree list [<repo>] [--json]`
   - Lists registered worktrees with name, path, branch, port, and created time, reconciled against `git worktree list --porcelain`: a registered tree git no longer knows about is marked `missing`, never silently dropped.
   - With no repo, lists every repo in the default registry location if one is in scope, otherwise requires a repo. (v0.1 implementation scopes the registry per worktree root, so a repo argument is the normal path.)

3. Status: `ghostworktree status [<repo>] [<name>] [--json]`
   - Per tree, reports clean or dirty from `git status --porcelain`: counts of staged, unstaged, and untracked entries, current branch, and the registered port.
   - One named tree, or every registered tree when no name is given. A missing tree is reported as `missing`, not as clean.

4. Cleanup: `ghostworktree cleanup <repo> <name> [--force] [--delete-branch] [--json]`
   - The safety core. Refuses to remove a dirty tree unless `--force` is explicitly passed. Never deletes uncommitted work by default, and the refusal names how many entries are dirty.
   - On a clean tree, runs `git worktree remove`, unregisters the record, and frees its port for reuse.
   - A missing tree may be unregistered without `--force` (there is no work on disk to lose).
   - Branch deletion is never the default: the branch is kept unless `--delete-branch` is explicitly passed, and even then it is deleted with `git branch -d` (safe delete), never `-D`, after the tree is removed.
   - Exit codes: 0 = cleaned up, 1 = refused (dirty without `--force`, or git refused), 2 = could not run.

5. Registry
   - One JSON file at `<worktrees-root>/registry.json`, written atomically (write to a temp file, then replace) so a crash mid-write cannot corrupt it.
   - Record: name, repo (absolute), path (absolute), branch, base, port, env source file name or null, created-at timestamp (UTC, ISO 8601).
   - No secret values, no file contents, no env contents are ever written to the registry or printed in any report.

## Out of scope for v0.1
- Dispatching, starting, stopping, or supervising agents, dev servers, or any process. Worktree allocates a port number, it does not run anything on it.
- OS-level sandboxing, containers, VMs, user accounts, or filesystem permissions beyond a normal worktree directory. A worktree is not a security boundary and copy must never claim it is.
- Any network operation: no fetch, pull, push, clone, remote checks, or port checks against anything but localhost bindability.
- Copying, reading, parsing, or logging a real `.env` or any secret value, in any command, including status and cleanup.
- Deleting branches by default, force-deleting branches at all, deleting the main checkout, or removing trees it did not register (except reporting them via `git worktree list` reconciliation).
- Merging, rebasing, committing, or resolving conflicts between trees. Verify and the developer own what happens to the work after cleanup.
- Cloud, accounts, telemetry, paid layer.

## Build estimate
- Registry (atomic JSON, validation, reconciliation with `git worktree list`): 2 days
- Port allocation (registry uniqueness plus localhost bind check): 1 day
- Env copy (example-only rule, `--no-env`): 0.5 days
- Create / list / status / cleanup CLI over local git subprocess: 2-3 days
- Tests (temp git repos, dirty-cleanup refusal, port collision, env secret exclusion), README, demo on GhostBus: 2 days
Total: roughly 1 to 1.5 weeks to a verified v0.1 if built straight through. Smallest tool in Wave 3 by design.

## Pricing draft (NOT public, NOT decided)
- MIT core CLI free, same pattern as Slice / Seatbelt / Ghost Hands.
- Paid candidate later only: team registry / dashboard across machines. Do not build a paid layer before a free launch validates demand.

## Verification bar
- Isolation test: create two trees for one temp repo, edit the same file differently in each, both edits survive and the main checkout is untouched.
- Port test: create three trees, all ports differ; request an already-allocated port explicitly, create must fail and register nothing; free a port via cleanup, the next create may reuse it.
- Env test: a temp repo with a real `.env` containing a planted marker value and a `.env.example` without it - the marker must appear in no created file except the untouched example copy, in no registry record, and in no CLI output.
- Cleanup safety test: dirty a tree, cleanup without `--force` must refuse and the dirty file must still exist; cleanup with `--force` removes it; clean-tree cleanup succeeds without `--force` and keeps the branch by default.
- Registry test: kill a create mid-way is hard to stage, so at minimum corrupt-registry handling must fail with a named error, never with a silent empty registry that orphans records.

## Risks / honest notes
- A git worktree shares the repository's object store and refs with the main checkout. It isolates the working directory and the checked-out branch, nothing else. Branch operations in one tree are visible in all of them, and copy must say so.
- Port allocation is a registry promise plus a bind check at create time. Another program can still take the port before the agent's server starts; Worktree reduces collisions between registered trees, it cannot reserve a port with the OS.
- `--force` cleanup is deliberately one flag away and deliberately destructive. Its help text and its output must both say it discards uncommitted work.
- Windows and non-POSIX path handling are untested in v0.1; developed and verified on Linux like the rest of the suite.

## Next gate
Ryan's go on: (1) GhostWorktree as working name, (2) CLI-first, dashboard panel deferred, (3) sibling default location `<repo-parent>/<repo-name>-worktrees/<name>`, or trees inside the repo, (4) default port range 4100-4999, (5) branch kept by default on cleanup, (6) build order within Wave 3.
