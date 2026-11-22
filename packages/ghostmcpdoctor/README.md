# GhostMCP Doctor
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/littlestjames82-sys/ghostmcpdoctor/actions/workflows/ci.yml/badge.svg)](https://github.com/littlestjames82-sys/ghostmcpdoctor/actions/workflows/ci.yml/actions)

**What tools are your agent clients wired to, and is any of that wiring stale, duplicated, or over-broad?**

Every agent client on a machine grows its own MCP config, and nobody
audits the union of them. Claude Code keeps servers in `~/.claude.json`
and project `.mcp.json` files, Cursor in `~/.cursor/mcp.json`, VS Code
in `.vscode/mcp.json`, and the same machine quietly accumulates the
same server defined twice and drifting apart, entries pointing at
commands uninstalled months ago, a filesystem server granted `/` once
and forgotten, and env blocks carrying credentials nobody remembers
adding. The only manual alternative is opening every config by hand,
which prints the secrets inside them into scrollback and screenshots.

GhostMCP Doctor is a **read-only** scanner for those configs. It
reports, it does not operate: it never edits, fixes, installs,
removes, or starts anything, and it does not even launch an MCP
server to test it. There is no `--fix` in v0.1, on purpose.

By Ghost Developer Studio. MIT core (see PLAN.md for the pricing
posture: free core, paid layer not decided). Zero dependencies:
Python standard library only, local-first, no network calls, no
telemetry.

Position in the Ghost stack: GhostSlice governs what an agent
*reads*, GhostVerify governs whether what it read was *enough*,
Agent Seatbelt governs what an agent *does*, GhostExposure governs
what sensitive *code* is in or out of a bundle, and GhostMCP Doctor
governs what *tools* the agent clients on this machine are wired to.

## At a glance

Doctor **does**:

- Read MCP config files you name, or the default local locations
  listed under Commands, and inventory every server defined in them.
- Report duplicate names, missing commands and files, empty or
  disabled entries, broad filesystem or env grants, shell wrappers,
  and unparseable configs, as findings of server name + path + issue.
- Write a redacted `mcpdoctor-report.json` + `MCPDOCTOR.md` pair you
  can share, and give CI a usable exit code (0, 1, or 2, below).

Doctor **does not**:

- Edit, fix, deduplicate, or delete any config entry. There is no
  `--fix`, by design. Every fix is a manual edit you make yourself.
- Start, ping, install, or uninstall any MCP server, or make any
  network call. URL servers are parsed, never contacted.
- Judge whether a server is safe or trustworthy. It reports breadth
  and staleness as evidence, not as a verdict.
- Show you a secret. Env values are discarded at parse time; see
  the secret rule below.

## The secret rule (non-negotiable)

Env blocks in MCP configs carry API keys and tokens, so Doctor treats
every env **value** as a secret:

- Values are discarded at parse time. They are never stored on the
  normalised server record, never written to the JSON or Markdown
  report, never printed to stdout or stderr, and never included in
  an error message. A parse error never echoes file content.
- Reports list env **key names** only, as `present` / absent. That is
  the whole report: *a key exists here*, never *what it is*.
- The same discipline applies elsewhere: full argument lists are not
  reported (only a count, plus any referenced file paths needed for
  a missing-file finding), and URL userinfo and query strings are
  stripped (only the host is kept).

This is gated by a canary test, not by good intentions: the test
fixtures plant unique fake secret strings, and the suite fails if
any of them appears in any output surface. See
`tests/test_redaction.py`.

## Install

```bash
cd ghostmcpdoctor
pip install .
ghostmcpdoctor --help
```

Or run from a checkout without installing:

```bash
PYTHONPATH=src python3 -m ghostmcpdoctor --help
```

Requires Python 3.10 or newer.

## Quickstart

```bash
# Scan configs you name explicitly (files or directories)
ghostmcpdoctor scan ~/.claude.json ~/.cursor/mcp.json ./.mcp.json

# Scan with no paths: the default local locations below are used,
# but only the ones that actually exist on this machine
ghostmcpdoctor scan

# Full redacted report as JSON on stdout
ghostmcpdoctor scan ~/.claude.json --json

# Print-only scan for scripts and CI: no report files are written
ghostmcpdoctor scan ~/.claude.json --no-report

# Re-render the Markdown + JSON reports from a previous scan,
# without re-scanning (safe to share: it is already redacted)
ghostmcpdoctor report mcpdoctor-report.json --out-dir ./share
```

What a scan prints looks like this: a one-line summary (counts and
the exit code), one line per finding, then three standing `note:`
lines about the read-only and redaction guarantees:

```text
ghostmcpdoctor scan: <n> server(s) in <n> config(s), <n> finding(s) (exit <code>)
  [<severity>] <server name> - <config path> - <ISSUE-CODE>: <plain reason>
```

(The exact, verified output for the bundled samples is in
[`examples/WALKTHROUGH.md`](examples/WALKTHROUGH.md).)

Two quickstart gotchas:

- `ghostmcpdoctor scan` with no paths only scans default locations
  that actually exist. If none exist, it exits 2 rather than
  reporting a false clean pass.
- `scan` writes its two report files into the current directory by
  default. Pass `--out-dir <dir>` to put them somewhere deliberate,
  or `--no-report` to write nothing.

A worked walkthrough with sample configs lives in
[`examples/`](examples/README.md).

## Commands

| Command | What it does |
|---|---|
| `ghostmcpdoctor scan [paths ...] [--config <path> ...] [--home <dir>] [--project <dir>] [--out-dir <dir>] [--json] [--no-report]` | Scan config files or directories (read-only). Explicit paths win. A directory is searched for the known filenames (`mcp.json`, `.mcp.json`, `.claude.json`, `.cursor/mcp.json`, `.vscode/mcp.json`). With no paths, the default local locations are used where they exist. Writes `mcpdoctor-report.json` + `MCPDOCTOR.md` to the output directory (default: current directory, never next to a scanned config by default) and prints a short summary: counts plus one `name - path - issue` line per finding. `--json` prints the full report to stdout instead. `--no-report` writes no files. |
| `ghostmcpdoctor report <mcpdoctor-report.json> [--out-dir <dir>] [--markdown]` | Re-render Markdown + JSON from a previous scan's JSON report without re-scanning. Default output directory is the directory holding the input report. `--markdown` also prints the Markdown report to stdout. The exit code is recomputed from the stored findings, not copied from the stored value. |

Both container shapes are understood: `mcpServers` (Claude Code,
Cursor, generic) and `servers` (VS Code), at the top level and, for
Claude Code, nested under `projects.<path>.mcpServers`.

Default locations scanned when no path is given (existing files
only): `~/.claude.json`, `~/.claude/settings.json`,
`~/.config/claude/claude_desktop_config.json`, `~/.cursor/mcp.json`,
`~/.config/mcp/mcp.json`, `~/.mcp.json`, `./.mcp.json`,
`./.claude.json`, `./.cursor/mcp.json`, `./mcp.json`,
`./.vscode/mcp.json`. `--home` and `--project` re-root those defaults.

### Findings

| Code | Severity | Meaning |
|---|---|---|
| `DUPLICATE` | warn | The same server name is defined in two or more configs, or twice in one config's scopes. One finding per extra definition. |
| `MISSING-COMMAND` | error, stale | A stdio server whose command path does not exist, or whose bare command name is not found on `PATH`. |
| `MISSING-FILE` | error, stale | An argument or `cwd` that is a file/directory path and does not exist (resolved relative to the config's directory or the entry's `cwd`). |
| `EMPTY-SERVER` | error | An entry with neither `command` nor `url`. |
| `DISABLED` | info, stale | An entry marked disabled. Reported so a human can decide to remove it; Doctor never removes it. |
| `BROAD-FILESYSTEM` | warn | A path argument grants `/`, the home directory, `~`, `$HOME`, a drive root, `..`, or a trailing `/*`. Narrow project paths are not flagged. |
| `BROAD-ENV` | warn | An env key named `*`, an env value that is a bare wildcard (checked internally, never reported), or an `alwaysAllow` / `autoApprove` list containing `*`. |
| `SHELL-WRAPPER` | warn | The command is a shell (`sh`, `bash`, `zsh`, `cmd`, `powershell`, `pwsh`): the real program is hidden behind a shell invocation, so the entry can run anything the shell can. |
| `PARSE-ERROR` | error | A discovered config is not valid JSON, or its server container is not an object. Path + issue only, no content echoed. Scanning continues with the other configs. |

`MISSING-COMMAND`, `MISSING-FILE`, and `DISABLED` are also counted
as **stale evidence** in the report summary.

### What to do with a finding

Doctor never fixes anything, so each finding ends in a manual edit
you make in the named config file, or a deliberate decision to keep
the entry as it is:

| Code | Suggested manual follow-up |
|---|---|
| `DUPLICATE` | Open both definitions, keep the one the client should use, and remove or rename the other. Check for drift before deleting: the two copies may no longer be identical. |
| `MISSING-COMMAND` | Reinstall the tool, fix the command path, or remove the entry. For a bare command name, first check whether the client app sees a different `PATH` than your shell (see Limits). |
| `MISSING-FILE` | Restore the missing script or directory, correct the path (relative paths resolve against the config's directory or the entry's `cwd`), or remove the entry. |
| `EMPTY-SERVER` | Give the entry a `command` or a `url`, or remove it. As written, no client can start it. |
| `DISABLED` | Re-enable it if it is still wanted, or remove it so the config only lists live wiring. |
| `BROAD-FILESYSTEM` | Narrow the granted path to the specific project directory the server actually needs. |
| `BROAD-ENV` | Replace the `*` wildcard with the specific key names or allowed tools the server needs. |
| `SHELL-WRAPPER` | Point `command` at the real program directly where you can, so the entry shows what will actually run. |
| `PARSE-ERROR` | Fix the JSON syntax, or make the server container an object (`"mcpServers": { ... }`), then re-scan. The rest of your configs were still scanned. |

After editing, re-run the same scan. A clean re-scan (exit 0, or
only info findings you have decided to keep) is the confirmation
that the fix landed.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Scanned, and no findings above info level. A config whose only findings are info (for example one disabled server) exits 0. |
| 1 | Warnings or errors found. A `report` re-render returns the code recomputed from the stored findings under this same rule (not the stored value verbatim), so reports written by older builds render with the corrected code. |
| 2 | Could not scan: no configs found, or an explicitly named config path does not exist. A scan that found nothing to scan never exits 0. |

## Troubleshooting

- **Exit 2, "no MCP config files found".** No default location
  exists on this machine and no path was supplied. Name the config
  files or directories explicitly, or use `--home` / `--project` to
  re-root the defaults.
- **Exit 2, "config path not found".** A path you named explicitly
  does not exist. A typo fails the scan on purpose: silently
  skipping a file you asked for would look like a clean result.
- **A config you expected is missing from the report.** Directory
  scans only pick up the known filenames listed under Commands, so
  name an unusually named file directly. A file that parses but has
  no `mcpServers` or `servers` container is listed with 0 servers.
- **`MISSING-COMMAND` for a tool you know is installed.** The
  client's `PATH` may differ from the scanning shell's `PATH`; the
  finding is evidence to check, not proof (see Limits).
- **You need to share a result.** Share the report pair, not your
  config files. The reports are redacted by construction; the raw
  configs contain the env values Doctor exists to keep out of
  scrollback and screenshots.

## Reports

- `mcpdoctor-report.json`: tool + version, UTC timestamp, the
  configs scanned (path, client kind, server count, parse status),
  the server inventory (the safe record only: name, config path,
  client, transport, command *basename*, argument count, referenced
  paths, env key names with present/absent, URL host only, disabled
  flag), the findings (server, config path, referenced path, issue
  code, severity, stale flag, plain reason), and a summary (totals
  by severity and issue code, stale count, duplicate count).
- `MCPDOCTOR.md`: the same data as a readable report: summary,
  per-config inventory, findings.

## Limits (honest notes)

- `PATH` on the scanning machine is not `PATH` inside the client
  app, so a `MISSING-COMMAND` for a bare name is **evidence, not
  proof** the client cannot launch it. The report says so.
- Doctor reports breadth and staleness as evidence. It does not
  judge whether a server is *safe* or trustworthy beyond those
  mechanical permission checks.
- Plain JSON and JSONC in v0.1 (a UTF-8 BOM at the start of a file is
  tolerated, as editor-written configs often carry one). JSONC means
  `//` and `/* */` comments plus trailing commas, as written by VS
  Code and Cursor: strict JSON is tried first, comments and trailing
  commas outside strings are stripped only as a fallback, and a
  commented-out server is not inventoried. Comment text is discarded
  at parse time, so a secret pasted into a comment never reaches a
  report. TOML/YAML configs and remote registries remain out of
  scope, not silent gaps. Unknown shapes degrade to "no
  servers found in this file" or a `PARSE-ERROR`, never to a crash
  or a guessed parse. A server container that is present but not an
  object is a `PARSE-ERROR`, and the rest of the file (and the other
  files in the same scan) are still read.
- Client config formats move: Claude Code has already used both
  top-level and per-project `mcpServers`. The default location list
  is a starting point, not a hard truth; explicit paths always win.

## Tests

```bash
python3 -m pytest tests -q
```

The suite is behavioural: it drives the CLI against fixture configs
planted with a duplicate name (across two files, and across the
scopes of one file), a missing command, a missing script file, a
filesystem server granted `/`, a shell wrapper, an invalid JSON
config, a disabled-only config (pins exit 0 for info-only findings),
a non-object server container (pins the `PARSE-ERROR`), and fake
secret canaries that must never appear in any output. It also proves the read-only guarantee (fixture bytes and
mtimes unchanged after scans) and the clean-config bar (a valid,
narrow, enabled config scans with exit 0 and an empty findings
list; false positives there are a release blocker).

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
