# GhostMCP Doctor - Read-Only MCP Config Auditor for Agent Clients
Working name, prepared Oct 14, 2026. Wave 3 paired tool for GhostSlice.
Decision: NOT Goliath. Goliath stays reserved for a non-agent product (Ryan, Oct 11-12, 2026).

## Why this name
- GhostMCP Doctor: plain job, plain name. It diagnoses the MCP servers wired into
  your agent clients the way a doctor checks vitals - it reports, it does not operate.
- Checked against the family: sits next to GhostExposure (which checks code) by
  checking the *tool layer itself*. No claim of a live product search yet. Treat as a
  working name until a name check runs at build gate, same as GhostSlice did Oct 12.
- Alternatives held in reserve: GhostMCPCheck (too close to Slice's `check`),
  GhostToolbox (implies it manages / installs servers, which v0.1 must not do).

## The problem
Every agent client on a developer machine grows its own MCP config, and nobody
audits the union of them:

- Claude Code keeps servers in `~/.claude.json` (top-level and per-project) and in
  project `.mcp.json` files.
- Cursor keeps servers in `~/.cursor/mcp.json` and project `.cursor/mcp.json`.
- VS Code and generic clients keep servers in `.vscode/mcp.json` (key `servers`,
  not `mcpServers`) and various `mcp.json` files.

So the same machine quietly accumulates:
- The same server name defined twice, in two clients, drifting apart.
- Entries pointing at commands that were uninstalled months ago (stale).
- Entries pointing at script files that no longer exist on disk.
- A filesystem server granted `/`, the home directory, or a parent path - broad
  filesystem permission granted once and forgotten.
- Env blocks carrying credentials nobody remembers adding, plus wildcard or
  shell-wrapper entries that widen what a server can reach.
- Disabled entries left in place forever, indistinguishable from live ones.

Today the only way to see any of this is to open every config by hand - and opening
them by hand prints the secrets inside them into scrollback, screenshots, and chat.

## Position in the Ghost stack
- GhostSlice governs what an agent READS.
- GhostVerify governs whether what it read was ENOUGH.
- Agent Seatbelt governs what an agent DOES.
- GhostExposure governs what sensitive CODE surface is in or out of a bundle.
- GhostMCP Doctor governs what TOOLS the agent clients on this machine are wired
  to, and whether that wiring is stale, duplicated, or over-broad.

Story: Doctor audits the tool layer -> Slice prepares context -> agent runs under
Seatbelt. No overlap: Doctor never scans project source, never judges a bundle,
and never edits a config.

## How it pairs with GhostSlice, concretely
Reuses, does not rebuild:
- House conventions from Slice: zero-dependency Python stdlib only, local-first,
  no network, findings are name + path + type only (Slice v0.4 secrets-guard
  behaviour), estimates/labels never presented as live facts.
- The Slice profile idea: default locations are a starting list, not a hard-coded
  truth - the user can always supply explicit config paths and override discovery.
- Report shape: a machine-readable JSON report plus a human Markdown report,
  the same two-artifact pattern as Verify's `verify-report.json` + `VERIFY.md`
  and Bench-ready by construction (summary counts + per-finding rows).

Integration contract:
- Input: zero or more config paths (files or directories) supplied by the user,
  and/or default local paths (see MVP) used only when they exist on disk.
- Output: `mcpdoctor-report.json` + `MCPDOCTOR.md` in an output directory the
  user chooses (default: current directory), never written into or next to a
  scanned config by default, and never modifying any scanned file.
- Findings are name + path + issue only: the server name, the config path (or
  the referenced file path for a missing-file finding), and an issue code +
  short plain reason. Nothing else about the entry is reported.

## The secret rule (non-negotiable, inherited and strengthened)
- Env blocks in MCP configs carry API keys and tokens. GhostMCP Doctor treats
  every env *value* as a secret.
- The scanner reads an env block only to record its *key names* and, internally,
  whether a value is a bare wildcard (`*`). Values are never stored on the
  normalised server record, never written to JSON or Markdown, never printed to
  stdout/stderr, and never included in an error message.
- The same redaction applies elsewhere: full argument lists are not stored or
  reported (only a count, plus any referenced *file paths* needed for a
  missing-file finding), URL userinfo and query strings are stripped (only the
  host is kept), and a parse error never echoes file content.
- Reports say an env key is `present` or `absent` / listed by name only. If a
  future version ever needs more, it needs a new Ryan gate, not a flag.

## MVP (v0.1) - local CLI, read-only scanner + reporter
Rationale: same as Slice v0.1. CLI proves the auditor on real machines in days.
It never edits, installs, removes, or launches anything. It does not even start
an MCP server to test it (that would execute the very commands it is auditing).

1. Discovery: `ghostmcpdoctor scan [--config <path> ...] [paths ...]`
   - Explicit paths win. A path may be a config file, or a directory, in which
     case the known filenames under it are scanned (`mcp.json`, `.mcp.json`,
     `.claude.json`, `.cursor/mcp.json`, `.vscode/mcp.json`).
   - Default local paths, used only when they exist (home = `~`):
     - Claude Code: `~/.claude.json`, `~/.claude/settings.json`,
       `~/.config/claude/claude_desktop_config.json` (read as a generic
       `mcpServers` config), `./.mcp.json`, `./.claude.json`
     - Cursor: `~/.cursor/mcp.json`, `./.cursor/mcp.json`
     - Generic / VS Code: `~/.config/mcp/mcp.json`, `~/.mcp.json`,
       `./mcp.json`, `./.vscode/mcp.json`
   - `--home <dir>` and `--project <dir>` override where defaults are rooted
     (also what makes the scanner testable against fixtures).
   - Configs that exist but do not parse, or parse to a non-object, produce a
     `PARSE-ERROR` finding (path + issue only, no content echoed) and scanning
     continues with the other configs. Exit code reflects it (see below).
   - Both container shapes are understood: `mcpServers` (Claude Code, Cursor,
     generic) and `servers` (VS Code), at the top level and, for Claude Code,
     nested under `projects.<path>.mcpServers`.

2. Normalisation (the safe record)
   Each server entry becomes one record holding only:
   server name, config path, client kind (claude-code / cursor / vscode /
   generic), transport (stdio when a `command` is present, http/sse when a
   `url` is present, unknown otherwise), command *basename* only, argument
   count, referenced file paths extracted from arguments, `cwd` when present,
   env key names (sorted, values discarded at parse time), URL host only,
   and `disabled` when the entry says so.
   No other field survives normalisation.

3. Checks (each produces findings of name + path + issue only)
   - `DUPLICATE` (warn): the same server name defined in two or more configs,
     or twice in one config's scopes. One finding per extra definition.
   - `MISSING-COMMAND` (error, also stale evidence): a stdio server whose
     command is an absolute/relative path that does not exist, or a bare
     command name not found on `PATH` (`shutil.which`).
   - `MISSING-FILE` (error, also stale evidence): an argument or `cwd` that
     is a file/directory path and does not exist relative to the config's
     directory (or the entry's `cwd`).
   - `EMPTY-SERVER` (error): an entry with neither `command` nor `url`.
   - `DISABLED` (info, stale evidence): an entry marked disabled - reported
     so a human can decide to remove it; Doctor never removes it.
   - `BROAD-FILESYSTEM` (warn): a filesystem-shaped server (name, command, or
     package argument mentions `server-filesystem` / `filesystem`) - or any
     server - whose path arguments include `/`, the home directory, `~`,
     `$HOME`, a drive root, `..`, or a trailing `/*`. Narrow project paths
     are not flagged.
   - `BROAD-ENV` (warn): an env key named `*`, an env value that is a bare
     wildcard (checked internally, value never reported), or an
     `alwaysAllow` / `autoApprove` list containing `*`.
   - `SHELL-WRAPPER` (warn): the command is a shell (`sh`, `bash`, `zsh`,
     `cmd`, `powershell`, `pwsh`) - the real program is hidden behind `-c`,
     so the entry can run anything the shell can.
   - `PARSE-ERROR` (error): a discovered config that is not valid JSON or
     whose server container is not an object.
   - Stale is a label, not a separate scan: `MISSING-COMMAND`, `MISSING-FILE`,
     and `DISABLED` findings are counted as stale evidence in the summary.

4. Reports: `ghostmcpdoctor scan ... [--out-dir <dir>] [--json] [--no-report]`
   and `ghostmcpdoctor report <mcpdoctor-report.json> [--out-dir <dir>]`
   - `scan` scans and, unless `--no-report`, writes both reports to the
     output directory, and prints a short human summary (counts and one
     `name - path - issue` line per finding). `--json` prints the full JSON
     report to stdout instead (the report itself is already redacted).
   - `report` re-renders Markdown + JSON from a previous scan's JSON report
     without re-scanning - useful for sharing a redacted report safely.
   - `mcpdoctor-report.json`: tool + version, UTC timestamp, configs scanned
     (path, client kind, server count, parse status), server inventory (the
     safe record only), findings (server, config path, referenced path,
     issue code, severity, stale flag, reason), and a summary (totals by
     severity, by issue code, stale count, duplicate count).
   - `MCPDOCTOR.md`: the same data as a readable report: summary table,
     per-config inventory, findings grouped by config.
   - Exit codes: 0 = scanned, no findings above info; 1 = warnings or errors
     found; 2 = could not scan (no configs found, or an explicit config path
     does not exist). Never exit 0 when nothing was scanned.

## Out of scope for v0.1
- Editing, fixing, deduplicating, or deleting any config entry. Read-only means
  read-only: Doctor does not even offer a `--fix`.
- Starting, pinging, installing, updating, or uninstalling any MCP server, and
  any network access of any kind (URL servers are parsed, never contacted).
- Judging whether a server is *safe* beyond the mechanical permission checks
  above. Doctor reports breadth and staleness as evidence, not a verdict on a
  server's trustworthiness.
- Scanning project source code (that is Exposure / Slice), agent transcripts
  (that is Replay), or Seatbelt policy.
- TOML/YAML configs, JSONC comment stripping, and remote registries. Plain JSON
  only in v0.1; other formats are a named v0.2 candidate, not a silent gap.
- Cloud, accounts, telemetry, paid layer.

## Build estimate
- Discovery + JSON parsing + safe normalisation (redaction at parse time): 2-3 days
- Checks (duplicates, missing command/file, broad fs/env, shell wrapper, stale): 2 days
- JSON + Markdown reports + `report` re-render command: 1-2 days
- Tests (fixture configs incl. a secret-canary fixture that must never appear in
  any output), README, demo on this machine's real configs: 2 days
Total: roughly 1 to 1.5 weeks to a verified v0.1 if built straight through.

## Pricing draft (NOT public, NOT decided)
- MIT core CLI free, same pattern as Slice / Seatbelt / Ghost Hands.
- Paid candidate later only: team config-policy packs / CI gate. Do not build a
  paid layer before a free launch validates demand.

## Verification bar
- Secret-canary test: a fixture config whose env values are unique canary strings
  must produce reports and stdout in which no canary string appears anywhere,
  while the env key *names* do appear.
- Duplicate test: the same server name in a Claude-shaped and a Cursor-shaped
  fixture is reported once per extra definition, by name and config path.
- Missing test: a fixture with a nonexistent command and a nonexistent script
  argument fails with `MISSING-COMMAND` and `MISSING-FILE` naming the server.
- Broad test: a filesystem fixture rooted at `/` and one rooted at a narrow
  project path - the first is flagged `BROAD-FILESYSTEM`, the second is not.
- Clean test: a valid, narrow, enabled fixture config scans with exit 0 and an
  empty findings list. False positives on a clean config are a release blocker.
- Read-only test: fixture config bytes and mtimes are unchanged after a scan.

## Risks / honest notes
- Client config formats move: Claude Code has already used both top-level and
  per-project `mcpServers`. Unknown shapes must degrade to "no servers found in
  this file" or a `PARSE-ERROR`, never to a crash or a guessed parse.
- `PATH` on the scanning machine is not `PATH` inside the client app, so a
  `MISSING-COMMAND` for a bare name is evidence, not proof the client cannot
  launch it. Report copy must say so.
- Redaction is the whole product: a single leaked env value in a report would
  destroy trust in a tool whose job is auditing credential-bearing files. The
  canary test gates every release, not just v0.1.

## Next gate
Ryan's go on: (1) GhostMCP Doctor as working name, (2) read-only with no `--fix`
in v0.1, (3) default path list above, (4) Wave 3 build order relative to the
other Wave 3 tools.
