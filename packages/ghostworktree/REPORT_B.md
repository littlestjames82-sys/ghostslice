# GhostWorktree v0.1 - Report B (tests / README / examples)

Agent B deliverable, Oct 14, 2026. Owned only `tests/**`, `README.md`,
`examples/**`, and this report. No `src/**`, `pyproject.toml`, or
`PLAN.md` files were edited by Agent B.

## Core state when the suite ran

Agent A's core HAD landed by the time the suite was verified
(`PLAN.md`, `pyproject.toml`, `src/ghostworktree/` with cli / core /
gitops / ports / registry / envcopy / errors, plus
`IMPLEMENTATION_A.md`). The suite is therefore fully live against the
shipped CLI, not skipped. First drafts of the tests and README were
written before the core landed, against the build-scope description,
then aligned to Agent A's exact interface (see Assumptions) with the
test helpers kept as the single mapping point.

## Assumed / confirmed interface

Confirmed from Agent A's shipped `PLAN.md` and `src/ghostworktree/cli.py`:

- `ghostworktree create <repo> <name> [--branch B] [--base HEAD]
  [--port N] [--port-range S-E] [--path DIR] [--no-env]
  [--root DIR] [--json]` - positional repo and name, not `--name`.
- `ghostworktree list <repo> [--json]`
- `ghostworktree status <repo> [<name>] [--json]`
- `ghostworktree cleanup <repo> <name> [--force] [--delete-branch] [--json]`
- Default worktree root: sibling `<repo-parent>/<repo-name>-worktrees/<name>`;
  registry at `<root>/registry.json`, records with name, repo, path,
  branch, base, port, env_source, created_at.
- Default branch `worktree/<name>`; default port range 4100-4999;
  explicit port already allocated or bound on localhost fails create.
- Exit codes: 0 ok, 1 refused/failed, 2 could not run (not a git repo).
- Env rule (stricter than the original brief's "env-copy" wording,
  and the suite tests the shipped rule): the real `.env` is never
  read or copied; only `.env.example` (fallback `.env.sample`,
  `.env.template`) is copied in, and the worktree `.env` is seeded
  from that example only.

The helpers in `tests/helpers.py` try the shipped form first and one
`--name` spelling as a fallback; created worktrees are located
authoritatively via `git worktree list --porcelain`, never by
guessing a directory layout.

## Files (Agent B owned)

- `README.md` - problem, shipped commands, env rule, dirty cleanup
  rule, safety rules and honest limits, stack position, examples,
  tests, gates.
- `tests/__init__.py`, `tests/conftest.py` (fixture trees not collected)
- `tests/helpers.py` - CLI discovery (env var, console script, or
  `python -m ghostworktree` with `PYTHONPATH=src`), throwaway git
  repo factory, create/list/status/cleanup drivers, registry and
  port lookup.
- `tests/test_create_list_status.py` - 7 tests
- `tests/test_cleanup.py` - 5 tests
- `tests/test_ports_env.py` - 6 tests
- `tests/test_adversarial.py` - 6 tests
- `tests/test_registry_and_status.py` - 6 tests
- `tests/test_fixtures.py` - 6 tests (docs/examples, run standalone)
- `examples/README.md`, `examples/demo.sh`,
  `examples/sample-state.json` (registry schema sample)

## Result

```
python3 -m pytest tests/ -q
36 passed in 41.61s   (Python 3.12.3, pytest 9.1.1)
```

36 passed, 0 failed, 0 skipped, 0 xfail.

Coverage includes every adversarial case named in the task, plus the
PLAN.md verification bar:

- Dirty cleanup refusal (tracked edit): cleanup without `--force`
  leaves the worktree registered, on disk, and the edit intact, by
  effect not just exit code; `--force` then removes it.
- Untracked-file cleanup refusal, same shape.
- Duplicate port allocation: explicit `--port 18741` on a second
  live tree must not produce two trees claiming the same port
  (core refuses, registering nothing); two auto trees differ; a
  port freed by cleanup is reusable.
- Missing git repo: create in a plain directory and in a
  nonexistent path both fail (shipped form reports exit 2,
  "not a git working tree"), creating nothing.
- Planted-secret env test: the fixture repo's real `.env` carries
  `planted-marker-not-a-real-secret`; it appears in no worktree
  file, no registry record, and no CLI output.
- Path traversal name (`../escaped`), duplicate task name,
  empty/whitespace names, cleanup/status of unknown tasks (clean
  errors, no tracebacks), create does not dirty the main tree,
  cleanup never touches the main tree.
- Registry: record contents match git; `--json` status clean then
  dirty; a tree deleted behind the tool's back is reported
  `missing`, never clean, and can be unregistered without
  `--force`; a corrupt registry fails naming the registry, never
  as a silent empty list; branch is kept by default on cleanup;
  isolation (an edit in one tree is invisible in the main tree).

Two early failures during development were defects in Agent B's own
helper fallbacks (a fallback spelling's argparse error masking the
real "not a git working tree" error, and an unnamed-status fallback
masking the unknown-name error), not in Agent A's core; both helpers
were fixed and the suite re-ran fully green, as above.

## Demo example

`examples/demo.sh` was run end-to-end against the shipped core and
passed (throwaway repo under `/tmp`, removed/inspectable after):

```
== create ==  created demo-task: .../repo-worktrees/demo-task
               branch: worktree/demo-task  base: HEAD  port: 4100
               env: .env.example
== list ==    demo-task: ... port=4100 state=present
== status ==  demo-task: clean  changed=0 (staged=0 unstaged=0 untracked=0)
== env rule == OK: marker absent; worktree .env seeded from .env.example only
== dirty cleanup == error: refusing to clean up dirty worktree 'demo-task':
               1 uncommitted entry (0 staged, 1 unstaged, 0 untracked).
               Re-run with --force ... -> OK: refused by default
== cleanup --force == warning: --force used; any uncommitted work ...
               cleaned up demo-task: removed_tree=True
               branch_deleted=False freed_port=4100
```

## Gates honoured

Local only, stdlib + pytest only, git only on throwaway repos under
pytest temp dirs, no network calls in the suite. No push, no publish,
no announcements, no spend.
