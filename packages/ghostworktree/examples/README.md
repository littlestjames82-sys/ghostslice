# GhostWorktree examples

- `demo.sh` - end-to-end demo. Creates a throwaway git repo in a temp
  dir, then runs the GhostWorktree lifecycle against it:

  1. `create` a worktree for a task named `demo-task`
  2. `list` the managed worktrees
  3. `status` for the task
  4. dirty the worktree and show that `cleanup` refuses by default
  5. `cleanup --force` to remove it anyway

  The demo repo's real `.env` carries a planted marker value
  (`planted-marker-not-a-real-secret`). The demo greps the created
  worktree and the registry for it: it must appear nowhere, because
  GhostWorktree never reads the real `.env` and seeds the worktree
  env from `.env.example` only.

  Run it with:

  ```sh
  bash examples/demo.sh
  ```

  Set `GHOSTWORKTREE_CMD` to override how the CLI is invoked
  (default: `ghostworktree` on PATH, falling back to
  `PYTHONPATH=<repo>/src python3 -m ghostworktree`).

  A successful run ends with `Demo done.` and prints, in order, the
  two checks that matter most:

  ```text
  OK: marker absent; worktree .env was seeded from .env.example only
  OK: cleanup refused the dirty worktree by default
  ```

  The demo is safe to re-run: it works only inside its own temp dir
  (kept afterwards for inspection, and the path is printed), and it
  touches no real repo, worktree, or `.env`.

- `sample-state.json` - one registry file in the shipped schema:
  `{"schema": 1, "worktrees": [ {name, repo, path, branch, base,
  port, env_source, created_at} ]}`. The real registry lives at
  `<repo-parent>/<repo-name>-worktrees/registry.json`. Note what is
  *not* in a record: no file contents and no env values, ever. Only
  the env source file *name* (`env_source`, or `null`) is recorded.

## Trying the `--json` form

Every command accepts `--json` for scripting. For example, after a
`create`, `ghostworktree status <repo> demo-task --json` returns one
object per tree with `name`, `path`, `branch`, `port`, `status`
(`clean`, `dirty`, or `missing`), the staged/unstaged/untracked
counts, and `changed` (the total cleanup would have to account for).
