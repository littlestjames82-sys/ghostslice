# GhostWorktree v0.1 - Implementation A (core)

Agent A deliverable, Oct 14, 2026. Agent B owns tests / README / examples in parallel (REPORT_B.md) - none written here.

## Files (Agent A owned)
- `PLAN.md` - full plan in GhostSlice format (problem, stack position, Slice pairing, MVP, out of scope, estimate, verification bar, risks, gates)
- `pyproject.toml` - setuptools, `ghostworktree = ghostworktree.cli:main`, zero dependencies, Python >=3.10
- `src/ghostworktree/__init__.py` - `__version__ = "0.1.0"`
- `src/ghostworktree/__main__.py` - `python -m ghostworktree`
- `src/ghostworktree/cli.py` - argparse CLI: create / list / status / cleanup, `--json` on every command
- `src/ghostworktree/core.py` - create/list/status/cleanup logic, name validation, registry reconciliation against `git worktree list --porcelain`
- `src/ghostworktree/gitops.py` - local git via subprocess only (worktree add/remove/list/prune, status --porcelain, branch checks, safe `branch -d`); no network git verbs anywhere
- `src/ghostworktree/ports.py` - port allocation: registry uniqueness + localhost bind check, default range 4100-4999, explicit-port collision fails
- `src/ghostworktree/registry.py` - atomic JSON registry at `<worktrees-root>/registry.json` (temp file + os.replace), corrupt registry raises a named error, never a silent empty one
- `src/ghostworktree/envcopy.py` - env seeding from `.env.example` (fallback `.env.sample`, `.env.template`) only
- `src/ghostworktree/errors.py` - WorktreeError (exit 1), CannotRunError (exit 2)

## CLI
```
ghostworktree create <repo> <name> [--branch B] [--base HEAD] [--port N] [--port-range S-E] [--path DIR] [--no-env] [--root DIR] [--json]
ghostworktree list <repo> [--root DIR] [--json]
ghostworktree status <repo> [<name>] [--root DIR] [--json]
ghostworktree cleanup <repo> <name> [--force] [--delete-branch] [--root DIR] [--json]
```
- Default location: sibling `<repo-parent>/<repo-name>-worktrees/<name>`; default branch `worktree/<name>`; existing branch is checked out as-is, otherwise created from `--base`.
- `create` records name/repo/path/branch/base/port/env-source-name/created-at in the registry; it creates and registers nothing on failure (duplicate name, existing path, branch already checked out, bad base, allocated or locally-bound explicit port, exhausted range).
- `status` reports clean/dirty with staged/unstaged/untracked counts per tree; a registered tree git no longer knows is reported `missing`, never clean.
- `cleanup` refuses a dirty tree without `--force` (exit 1, refusal names the counts, tree untouched); `--force` discards uncommitted work and says so in its output. Branch kept by default; `--delete-branch` uses safe `git branch -d` only, after removal. Missing trees can be unregistered without `--force`. Port is freed on cleanup and reusable by the next create.
- Exit codes: 0 ok, 1 refused/failed, 2 could not run (e.g. not a git repo).

## Safety rules implemented
- Stdlib only, local only, no network (only network-adjacent call is a localhost bind probe for port allocation).
- Real `.env` is never opened, copied, parsed, or logged. Only example files are copied byte-for-byte; contents are never printed; registry and reports carry the example file name only.
- Never deletes uncommitted work by default; no branch deletion by default; no force branch delete (`-D`) exists in the code.

## Smoke verification performed by Agent A (temp repo in /tmp, removed after)
- create task-a: port 4100, branch worktree/task-a, `.env` seeded from `.env.example` only; planted real-`.env` marker value found in no created file and no registry/output.
- duplicate name create: exit 1. Explicit `--port 4100` for a second tree: exit 1, nothing registered. Second tree auto-allocated 4101.
- status: clean tree reported clean; tree with 1 unstaged edit + 1 untracked file reported dirty with correct counts.
- cleanup on dirty tree without `--force`: exit 1, dirty files preserved. With `--force`: removed. Clean tree cleanup without `--force`: removed, branch kept, list empty, `git worktree list` back to main only.
- All modules compile (`py_compile` clean) on Python 3.12.

## How to run tests (Agent B's suite)
```
cd ~/workspace/ghostworktree
pip install -e .          # or PYTHONPATH=src
python -m pytest tests/ -q
# manual smoke:
git init /tmp/demo && cd /tmp/demo && git add -A && git commit -m init
ghostworktree create /tmp/demo task-a --json
ghostworktree status /tmp/demo
ghostworktree cleanup /tmp/demo task-a
```

## Known v0.1 limits (from PLAN.md)
- Worktree shares the repo object store/refs; branch ops are visible across trees. Not a security sandbox.
- Port allocation is registry + bind-at-create; it cannot OS-reserve a port against non-registered programs.
- Linux verified only; an env-seeding failure after tree creation is recorded as `env_source: null` rather than rolling back the tree.
