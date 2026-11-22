# GhostConsole App
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE) [![CI](https://github.com/littlestjames82-sys/ghostconsole-app/actions/workflows/ci.yml/badge.svg)](https://github.com/littlestjames82-sys/ghostconsole-app/actions/workflows/ci.yml)

**The local web front end for the Ghost ecosystem.**

GhostSlice builds context, GhostVerify checks it, GhostBench
measures it, and [GhostWorkflow](https://github.com/littlestjames82-sys/ghostworkflow)
runs the chain and keeps the receipt. This app is what you open in
a browser to use all of that on your own projects: register a
project, give it a task, watch the workflow run, and read the
evidence - the verdict, the verification level, and the GhostConsole
board - when it lands.

```sh
ghostconsole-app
# GhostConsole app listening on http://127.0.0.1:8760/
```

**Local only. No authentication.** The server binds `127.0.0.1` by
default and says so on start and in the page footer. Anyone who can
reach this port can register projects and start workflow runs on
this machine, so do not expose it beyond your own machine. Changing
`--host` is possible and explicit, and the UI states the bind
address either way - but in v0.1 there is never a login.

By Ghost Developer Studio. MIT licensed. **Zero dependencies**
(Python standard library only, `http.server` based), no telemetry.

## Install

Requires Python 3.10 or newer, and ghostworkflow (installed, or in
a checkout next to this one).

```sh
pip install .
ghostconsole-app --help
```

Without installing, run it from a source checkout as a module:

```sh
PYTHONPATH=src python3 -m ghostconsole_app
```

## What it does

- **Project registry.** Add project directories by absolute path
  (stored in `~/.ghostconsole-app/projects.json`; override with
  `GHOSTCONSOLE_APP_HOME`). Remove unregisters only - files are
  never touched.
- **Dashboard.** Every registered project with its latest workflow
  run: verdict, verification level, timestamp, task, read live from
  `<project>/.ghostworkflow/*/workflow-report.json`. A project with
  no runs says "no runs yet". Nothing is invented.
- **Run workflow.** From a project page: a task and an optional
  test command. The app starts `ghostworkflow run` in the
  background - it never runs an engine directly - and one run per
  project at a time is enforced. When the workflow writes its
  report, the run appears in the project's history.
- **Run detail.** The workflow report rendered readably: verdict,
  verification level with the plain-words legend GhostConsole uses,
  engine versions, tree hash and where it came from, and the
  per-step table.
- **Board.** Each run's `board.html`, served as-is. It is a
  self-contained GhostConsole artifact; the app serves its bytes
  and does not generate or edit it. GhostConsole stays read-only,
  and so does this app with respect to engine reports: it reads
  them, full stop.

## Finding ghostworkflow

The app invokes the ghostworkflow CLI only, located in this order:

1. `--workflow-home <dir>` or `GHOSTCONSOLE_APP_WORKFLOW_HOME`:
   the ghostworkflow checkout itself, or a directory containing
   one (invoked as `python3 -m ghostworkflow` with its `src/` on
   PYTHONPATH);
2. a `ghostworkflow` console script on PATH;
3. a sibling checkout at `~/workspace/ghostworkflow` (or next to
   this app's own checkout).

`--engine-home <dir>` is passed through to `ghostworkflow run` for
finding the four engines.

## Options

```sh
ghostconsole-app [--host 127.0.0.1] [--port 8760]
                 [--workflow-home DIR] [--engine-home DIR]
```

If the port is taken, the app fails with a clear message and exit
code 2. It never silently picks another port.

## Exit codes

- `0`: clean shutdown (Ctrl+C).
- `2`: usage error, or the bind failed (for example, port in use).

Test state: [RESULTS.md](RESULTS.md). Design notes and honest
limits: [BUILD.md](BUILD.md).

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
