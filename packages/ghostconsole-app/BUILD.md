# GhostConsole App - build notes (v0.1.0, Oct 18, 2026)

## Shape

Four small modules, standard library only:

- `store.py` - the project registry (`~/.ghostconsole-app/
  projects.json`, atomic-ish write via temp file + replace) and all
  read access to run evidence. A corrupt or wrong-shaped registry
  reads as empty and the app still starts; the next successful add
  rewrites the file.
- `runner.py` - ghostworkflow discovery and background execution.
- `render.py` - every page. All file- and form-derived strings go
  through `html.escape`; there is no raw-HTML path for content.
- `server.py` - a `ThreadingHTTPServer` handler that is only
  routing: registry and evidence from the store, bodies from
  render, execution from the runner.

## Key decisions

**The app executes exactly one thing: the ghostworkflow CLI.** It
never imports or shells to GhostSlice, GhostVerify, GhostBench, or
GhostConsole. That keeps the ecosystem's trust story intact:
engines write reports, the workflow orchestrates, Console renders,
and this app is a shell over the workflow's own evidence. Discovery
mirrors ghostworkflow's own engine discovery (explicit home, then
PATH, then sibling checkout) so the two tools feel like one family.

**Boards are served, never generated here.** `/board` returns the
bytes of the run's `board.html` exactly as GhostConsole wrote them.
Board lookup goes through `store.board_path`, which validates the
run id as a single path component and proves with realpath that the
resolved directory stays inside the project's `.ghostworkflow/` -
a crafted id (`../`, separators, dot segments) is refused, and a
symlinked run directory pointing outside is refused too. Only
registered projects are addressable at all; everything else 404s.

**Run state is in memory; evidence is on disk.** The runner tracks
the active run per project (status, exit code, output tail) in a
dict guarded by a lock, and enforces one run per project: a second
submission is refused with 409 and the reason stated, not queued
silently. Which run a finished invocation produced is detected by
diffing `.ghostworkflow/` directory names from before the start
and attaching the newest new report. If the app restarts mid-run,
the in-flight tracking is gone - but the run's report, once
written, shows up in the project's history like any other, because
history is read from disk every time.

**Verdicts and levels are shown, never derived.** The dashboard
and history display the workflow report's own `verdict` and
`verification_level` fields. The app adds no scoring of its own,
and a project with no runs is shown as having no evidence, in
grey, never as a pass.

**The bind is a stated fact.** Default `127.0.0.1:8760`; the
startup message and every page footer state the bind address and
the absence of authentication. A taken port is a hard failure
(exit 2 with the reason), never a silent hop to another port -
a user who thinks the app is on 8760 should never find it on 8761.

## Limitations (v0.1, deliberate)

- **No authentication, localhost by default.** Do not expose it.
  `--host` exists for the user's own explicit choice only.
- **One run per project at a time.** Different projects may run
  concurrently; the same project may not.
- **Board serving is synchronous** - `board.html` is read and
  written in the request handler. Boards are single small files;
  this is fine locally and is not a streaming design.
- **Run tracking does not survive an app restart** (see above).
  No run queue, no cancellation button, no workflow timeout of
  its own (ghostworkflow's per-engine timeouts apply).
- **The registry stores paths only.** No project metadata, no
  renaming, no grouping in v0.1.
- The dashboard reads each project's run reports on every page
  load. That is honest and simple; it is not a cache, and a
  project with hundreds of runs will feel it.

## Tests

`tests/test_store.py` (registry round-trip, corrupt-registry
recovery, run listing order, crafted run ids, symlink escape),
`tests/test_server.py` (ephemeral-port HTTP: dashboard content and
escaping, project/run/board routes, traversal refusal, unknown
project 404s, add-project POST), `tests/test_runner.py` (fake
ghostworkflow on PATH and as a checkout: completion, exit-code
recording, concurrent-run refusal, and a full HTTP run round
trip). Counts in RESULTS.md.
