# GhostShard examples

Everything here is runnable locally, no network, nothing is
dispatched or executed by any of it. GhostShard is a planner:
its only outputs are files.

Prerequisites: Python 3.10 or newer, a checkout of this repo, and
a shell. Run every command from the repo root (`ghostshard/`, the
folder containing `src/` and `tests/`), exactly as written: the
commands use relative paths and `PYTHONPATH=src`, so no install
step is needed. Each example writes only under `/tmp`; re-running
an example overwrites its previous plan folder.

Work through them in order: example 1 is the happy path, 2 shows
sequencing around a shared file, 3 shows configuration, 4 shows
an honest failure (a partial plan), and 5 shows the GhostBus
manifest boundary.

## 1. Auto-clustered plan (start here)

Uses the disjoint test fixture as the demo project (two
independent packages, `alpha/` and `beta/`):

```bash
cd ghostshard
mkdir -p /tmp/shard-demo/project
cp -r tests/fixtures/disjoint/alpha tests/fixtures/disjoint/beta /tmp/shard-demo/project/
PYTHONPATH=src python3 -m ghostshard plan /tmp/shard-demo/project \
  --task "$(cat examples/auto-task.txt)" -o /tmp/shard-demo/out
PYTHONPATH=src python3 -m ghostshard check /tmp/shard-demo/out
```

Expected shape: two shards (`shard-01-cluster-alpha-py`,
`shard-02-cluster-beta-py`), both in parallel group 0,
max useful parallelism 2, exit code 0. Then `check` prints
`check OK: 2 shard bundle(s), ownership unique, acyclic`.

What to look at afterwards: `PLAN.md` in the output folder for
the human view, `shards.json` for the machine view, and one
shard folder (for example `shard-01-cluster-alpha-py/`) for a
bundle: `PROMPT.md`, `manifest.json`, and `files/`.

`sample-output/` in this folder is a real captured run of exactly
that command (Oct 14, 2026): `shards.json`, `PLAN.md`,
`bus-manifest.json`, and both per-shard bundles with manifests.
Totals there: 354 + 329 = 683 estimated tokens. Estimates are
from the GhostSlice-style raw estimator, not exact tokenizer
counts.

## 2. User-split plan (shared symbol)

Uses the shared test fixture, where `report.py` and `export.py`
both import `normalize_records` from `shared_core.py`:

```bash
mkdir -p /tmp/shard-shared/project
cp tests/fixtures/shared/*.py /tmp/shard-shared/project/
PYTHONPATH=src python3 -m ghostshard plan /tmp/shard-shared/project \
  --task-file examples/user-split.tasks.md -o /tmp/shard-shared/out
```

Expected shape: `shared_core.py` is owned by exactly one shard,
the other shard depends on the owner and carries the shared file
as read-only signatures context, and the near-tie claim is named
in `conflicts`. Mode is labelled `user-split` in `shards.json`
and `PLAN.md`. The task file format: one `## Heading` per
subtask, free text under it; see `user-split.tasks.md`.

## 3. Profile

Copy `profile.ghostshard.json` into a project root as
`.ghostshard.json` to set the per-shard budget and caps without
flags. Precedence: CLI flags over the profile over the defaults
(60000 tokens, 12 shards, fan-out 8). The `shard` section is
optional; flat top-level keys work too.

## 4. Partial plan: an unfittable shard

Uses the unfittable test fixture: one large hub module planned
with a deliberately tiny 250-token budget. A single file cannot
be split below file granularity, so the honest result is a
partial plan, not a clean-looking one:

```bash
mkdir -p /tmp/shard-unfit/project
cp tests/fixtures/unfittable/hub.py /tmp/shard-unfit/project/
PYTHONPATH=src python3 -m ghostshard plan /tmp/shard-unfit/project \
  --task "$(cat tests/fixtures/unfittable/TASK.txt)" \
  --budget 250 -o /tmp/shard-unfit/out
echo "exit code: $?"   # expect 1
PYTHONPATH=src python3 -m ghostshard check /tmp/shard-unfit/out
```

Expected shape: `plan` exits 1, prints `partial: True`, and
`shards.json` names the reason in `conflicts` (`unfittable: ...
single file(s) ['hub.py'] exceed per-shard budget 250 ...`) with
the shard flagged `unfittable`. Nothing is dropped: `hub.py`
still appears whole in exactly one bundle, so `check` still
passes: partial describes the fit, not structural validity.

## 5. Bus manifest (file only)

Every plan already writes `bus-manifest.json` next to
`shards.json`. `ghostshard export-bus <shards-folder> [-o file]`
re-writes it. Every job in it carries `"dispatch": false` and a
Seatbelt approval-class placeholder. GhostShard never sends it:
handing it to GhostBus is a separate, later gate.

Try it on the example 1 output and inspect the result:

```bash
PYTHONPATH=src python3 -m ghostshard export-bus /tmp/shard-demo/out \
  -o /tmp/shard-demo/custom-bus.json
grep '"dispatch"' /tmp/shard-demo/custom-bus.json
# one '"dispatch": false' line per shard, never true
```

Common mistakes: running the commands from outside the repo
root (the relative fixture paths will not resolve), pointing
`--task-file` at a file inside the project being scanned (the
scanner reads `.md`/`.txt` files as project text, which pollutes
the graph), and hand-editing bundle files (a later `check` will
fail on the sha256 mismatch; re-run `plan` instead).
