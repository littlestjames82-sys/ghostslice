# GhostConsole App - Test Results

Reproducible record of a full-suite run. Regenerate on every
release-grade change; counts quoted anywhere else must match this
file or be removed.

## Run of Oct 18, 2026 (v0.1.0 build)

- Date (UTC): 2026-10-18
- Platform: Linux 7.0.0-39-generic x86_64
- Python: 3.12.3
- pytest: 9.1.1
- Command:

```sh
cd ghostconsole-app
PYTHONPATH=src python3 -m pytest tests -q
```

- Result: **34 passed** (12.66s), 0 skipped, 0 failed

Coverage, by file:

- `tests/test_store.py` (14 tests): registry add/list/remove
  round-trip under an env-overridden app home; rejection of
  missing paths, plain files, blanks, and duplicates; corrupt and
  wrong-shaped registry files read as empty and recover; run
  listing newest-first, non-run and hidden directories skipped;
  report/board loading; eight crafted run ids refused; a symlinked
  run directory pointing outside `.ghostworkflow/` refused.
- `tests/test_server.py` (9 tests): real HTTP against an ephemeral
  port - dashboard empty state with the bind address and
  no-authentication footer stated; dashboard and project page show
  a fabricated run's verdict and level with a `<script>` task
  string rendered escaped everywhere; run detail renders the tree
  hash, its source, engine versions, steps, and Console's
  plain-words level legend; board bytes served as-is; traversal
  run ids (`../../secret`, encoded, `..`) refused with 400/404 and
  the outside file never served; unknown and unregistered projects
  404 on every route; add-project POST round trip and its 400 on a
  bad path.
- `tests/test_runner.py` (11 tests): a fake ghostworkflow (script
  on PATH, and a checkout under a workflow home) - discovery both
  ways, a missing home raising `WorkflowNotFound`; a run completing
  with exit code recorded and its report attached and readable
  through the store; a failing workflow's exit code 1 recorded with
  its report still attached; a second concurrent run for the same
  project refused while the first runs, and allowed after it
  finishes; and a full HTTP round trip: POST /run -> status page ->
  run in history with the fake's verdict -> run detail -> board,
  plus a second POST /run during an active run answered 409.

## Manual smoke checks (same day, outside the suite)

- `python3 -m ghostconsole_app --port 8791` booted, printed the
  URL and bind statement, and served the empty-state dashboard.
- A second instance on the same port failed with a clear message
  ("cannot listen on 127.0.0.1:8792 ... choose another with
  --port") and exit code 2. No silent port change.

## Known limits of this run

- The fake ghostworkflow stands in for the real orchestrator in
  the suite: it writes a canned report and board with the real
  report's shape. The parent's own verification runs a real
  ghostworkflow run through the app separately.
- No browser was driven; pages were verified over HTTP with
  http.client, and board bytes are served artifacts, not app HTML.
