# GhostWorktree
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/littlestjames82-sys/ghostworktree/actions/workflows/ci.yml/badge.svg)](https://github.com/littlestjames82-sys/ghostworktree/actions/workflows/ci.yml/actions)

Isolated git worktree + port + env-copy manager per agent task.

Ghost Developer Studio, Wave 3 companion to GhostSlice. Python standard
library only, local only. No network, no accounts, no telemetry.

## The problem

Parallel agents working in one checkout collide: same files, same
lockfiles, same dev-server port, same env. GhostShard plans the split
into tasks; GhostWorktree enforces the split on disk. Each agent task
gets:

- its own `git worktree` (its own checkout and branch),
- its own allocated port (no two live registered worktrees share one),
- its own throwaway env, seeded only from `.env.example` (see the env
  rule below).

Default location: a sibling of the repo,
`<repo-parent>/<repo-name>-worktrees/<name>`, recorded in a registry
at `<repo-parent>/<repo-name>-worktrees/registry.json`.

## Quick start

Prerequisites: Python 3.10 or newer and `git` on `PATH`. There is
nothing to install from a package index and nothing to configure:
run the CLI from a source checkout with the module form below.

```sh
# Short-hand for the module form (skip this if the `ghostworktree`
# console script is installed, and just call `ghostworktree`):
gw() { PYTHONPATH=/path/to/ghostworktree/src python3 -m ghostworktree "$@"; }

gw create /path/to/repo fix-parser   # creates <repo-parent>/<repo>-worktrees/fix-parser,
                                     # branch worktree/fix-parser, a free port
gw list /path/to/repo                # name, path, branch, port, state
gw status /path/to/repo fix-parser   # clean, or dirty with per-kind counts
# ... an agent works in the new tree; commit or discard its work ...
gw cleanup /path/to/repo fix-parser  # refuses if the tree is dirty (see below)
```

A successful `create` prints the tree path, branch, base, allocated
port, and the env source file name, for example:

```text
created fix-parser: /path/to/repo-worktrees/fix-parser
  branch: worktree/fix-parser  base: HEAD  port: 4100
  env: .env.example
```

Add `--json` to any command for the same information as JSON, for
scripts. Run `ghostworktree --help` (or
`ghostworktree <command> --help`) for the full flag list per command.

## Commands (v0.1, as shipped)

```sh
# Create a worktree for one agent task
ghostworktree create <repo> <name> [--branch <branch>] [--base <ref>]
                     [--port <n>] [--port-range <start>-<end>]
                     [--path <dir>] [--no-env] [--root <dir>] [--json]

# List the registered worktrees for a repo
ghostworktree list <repo> [--root <dir>] [--json]

# Status: clean / dirty with staged, unstaged, untracked counts
ghostworktree status <repo> [<name>] [--root <dir>] [--json]

# Doctor: read-only audit reconciling registry, git, disk, and ports
ghostworktree doctor <repo> [--root <dir>] [--json]

# Clean up a finished task
ghostworktree cleanup <repo> <name> [--force] [--delete-branch]
                      [--root <dir>] [--json]
```

Module form works too, from a source checkout:

```sh
PYTHONPATH=src python -m ghostworktree create <repo> <name>
```

Defaults: branch `worktree/<name>` created from `HEAD`; ports are the
lowest free port in 4100-4999 that is neither already registered nor
currently bound on localhost. An explicitly requested port that is
already allocated or in use fails the create; nothing is created or
registered on a failed create.

### Exit codes

| Code | Meaning | Typical causes |
| --- | --- | --- |
| 0 | ok | the command did what it asked |
| 1 | refused or failed | dirty cleanup without `--force`, duplicate name or port, unknown worktree name, corrupt registry |
| 2 | could not run | the repo argument is not a git working tree, or `git` is not on `PATH` |

### Common refusals (all are deliberate, nothing is changed)

- `refusing to clean up dirty worktree ...` - the tree holds
  uncommitted work. Commit it, or re-run with `--force` only if you
  really want that work discarded. See the dirty cleanup rule below.
- `worktree name ... is already registered` - names address trees in
  `list`, `status`, and `cleanup`, so pick a different name or clean
  up the existing tree first.
- `port ... is already allocated / in use` - pick another `--port`,
  or omit it and let the tool allocate the lowest free port.
- `no free port in range ...` - clean up a finished tree to free its
  port, or pass a wider `--port-range START-END`.
- `not a git working tree` (exit 2) - the repo argument must be an
  existing git checkout, not a plain directory or a bare repo.
- `registry is corrupt ...` / `registry record ... is missing ...` -
  the registry is never guessed at or treated as empty. Fix or
  restore `registry.json`; no trees were touched by the failed run.
- `status` says `missing` - the tree is registered but not on disk.
  That is not `clean`; `cleanup` on it just unregisters the record
  and needs no `--force`, because there is no work on disk to lose.

## The env rule (non-negotiable)

The real `.env` is never opened, copied, parsed, or logged, in any
command. The only env source ever used is `.env.example` (falling back
to `.env.sample`, then `.env.template`):

- the example file is copied into the worktree byte-for-byte, and
- a throwaway `.env` in the worktree is seeded from that example only
  (skip the seeding with `--no-env`).

Reports and the registry name the env source file only, never any
contents. Secret values from a real `.env` therefore appear in no
created file, no registry record, and no output.

## The dirty cleanup rule

Cleanup refuses a dirty worktree by default. Dirty means tracked files
modified, or untracked files present, inside the worktree: that is
uncommitted agent work, and deleting it silently is the worst failure
this tool can have.

- `ghostworktree cleanup <repo> <name>` on a dirty worktree exits
  non-zero, names how many entries are dirty, and leaves the worktree
  and its files untouched.
- `ghostworktree cleanup <repo> <name> --force` is the explicit
  override, and its output says uncommitted work was discarded.
- The branch is kept by default. `--delete-branch` deletes it only
  after the tree is removed, and only with a safe `git branch -d`,
  never `-D`. If `git branch -d` refuses (for example the branch has
  unmerged commits), the cleanup still succeeds, the branch is kept,
  and a warning names that outcome.
- A registered tree that is missing from disk may be unregistered
  without `--force` (there is no work on disk to lose), and status
  reports such a tree as `missing`, never as clean.

## The doctor audit

`list` and `status` look from the registry outward, so they cannot
see a worktree the registry has lost. `ghostworktree doctor` reconciles
all four sources of truth (registry, `git worktree list`, the disk,
and the managed root) and reports, as problems:

- registered trees that are `missing`, or that git marks `prunable`,
- git worktrees that are not registered (doctor does not adopt,
  manage, or remove them; cleanup will not touch them either),
- directories inside the managed root that are neither registered
  nor git worktrees (leftovers squatting on a name `create` would
  refuse),
- duplicate names or duplicate ports in the registry, a recorded
  repo that does not match, and a recorded branch that has vanished
  or drifted from the branch actually checked out.

Doctor is strictly read-only: it never prunes, removes, unregisters,
or rewrites the registry, and it never reads a real `.env`. A dirty
tree is a note, not a problem: uncommitted work in progress is
normal, and doctor never discards it (the dirty cleanup rule below
still protects it). Exit code is 0 when no problems are found and
1 when any are; a corrupt registry still fails with a named error,
exactly as in the other commands.

## Safety rules in v0.1

- The source repo must be a git working tree. Creating a worktree
  from a plain directory or a missing path fails (exit 2), and
  creates nothing.
- Task names must be a safe single path component (letters, digits,
  `-`, `_`, `.`; no slashes, no `..`). A name containing path
  traversal is rejected, so a worktree can never be created outside
  the managed root by way of its name.
- A duplicate task name is refused rather than silently duplicated,
  because list, status, and cleanup all address trees by name.
- Creating a worktree never modifies files in the main checkout, and
  cleanup never touches the main checkout.
- A corrupt registry fails with a named error. It is never treated
  as an empty registry, which would orphan every recorded tree. A
  registry whose records are missing required fields (name, path,
  branch, or a non-integer port) also fails with a named error
  identifying the record and field, never a traceback.
- Concurrent creates and cleanups are serialised by an advisory
  lock on the registry, so two processes cannot allocate the same
  port or overwrite each other's records. If registering a new
  tree fails after the tree was created on disk, the create rolls
  the tree back rather than leaving it orphaned.
- Status counts every untracked file individually, including files
  inside a brand-new directory, so the counts in a dirty cleanup
  refusal are the real number of entries at risk.
- All git work is local `git` subprocess calls only: no fetch, pull,
  push, clone, or any other network operation in v0.1.
- Honest limit: a worktree shares the repo object store and refs. It
  isolates the working directory and checked-out branch, nothing
  else, and it is not a security sandbox. Port allocation is a
  registry promise plus a localhost bind check at create time; it
  cannot reserve a port with the OS against other programs.

## How it fits the Ghost stack

- GhostSlice: what an agent reads (context bundles).
- GhostShard: how a big task is planned into ordered shards (planner
  only, no dispatch).
- GhostWorktree: where each shard runs (isolated checkout, port, env).
- GhostVerify: whether the result holds, before the worktree is
  cleaned up.
- Agent Seatbelt: what an agent may do while it runs there.

Lifecycle: Shard plans -> Worktree creates -> agent runs -> Verify
checks -> cleanup removes the clean worktree.

## Examples

See `examples/`:

- `examples/demo.sh` walks the full lifecycle against a throwaway
  demo repo it creates itself (create, list, status, dirty-refusal,
  forced cleanup, and a planted real-`.env` marker that must appear
  nowhere in the worktree).
- `examples/sample-state.json` shows one registry file in the shipped
  schema (`schema` + `worktrees` records with name, repo, path,
  branch, base, port, env_source, created_at).

## Tests

```sh
python -m pytest tests/ -q
```

Black-box suite (stdlib + pytest only, git only on throwaway repos
under temp dirs). Adversarial coverage includes dirty-tree cleanup
refusal, untracked-file cleanup refusal, duplicate port allocation,
duplicate task names, path-traversal names, the missing git repo
case, a corrupt registry, a missing tree reported as missing, and
the planted real-`.env` marker that must leak nowhere. See
`REPORT_B.md` for the current pass/fail state and the interface the
suite was written against.

## Gates

Local only. No push, no publish, no announcements, no spend. Those are
separate decisions for Ryan, same as the rest of the GhostSlice
companion suite.

---
<!-- ghost-studio-footer -->
## More from Ghost Developer Studio

Ghost Developer Studio builds developer tools, AI-agent safety software, and practical apps, and sells by showing working software, not slide decks.

- [Roadmap board](https://github.com/littlestjames82-sys/ghost-roadmaps): where every studio product stands
- [Agent Seatbelt](https://github.com/littlestjames82-sys/agent-seatbelt): deterministic guardrails for AI coding agents
- [Ghost Hands](https://github.com/littlestjames82-sys/ghost-hands): governed, recorded, replayable agent hands
- [GhostSlice](https://github.com/littlestjames82-sys/ghostslice): agent context and prompt optimizer
- [GhostIDE](https://github.com/littlestjames82-sys/ghostide-android): fully offline AI code editor for Android
- [All studio projects](https://github.com/littlestjames82-sys?tab=repositories)
