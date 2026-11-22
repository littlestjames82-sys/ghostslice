# GhostMCP Doctor v0.1 - Implementation A (core)

Agent A (core owner). Agent B owns tests / README / examples.
Built Oct 14, 2026 per PLAN.md in this folder. Gates honoured: stdlib only,
local only, read-only, NO push, NO publish, NO announcements, NO spend,
NO network.

## What was built

- `PLAN.md` - full plan in Slice format (name rationale, problem, position in
  the Ghost stack, pairing with GhostSlice, the secret rule, MVP, out of
  scope, estimate, pricing draft NOT decided, verification bar, risks, gate).
- `pyproject.toml` - package `ghostmcpdoctor` 0.1.0, MIT, `requires-python
  >=3.10`, zero dependencies, console script `ghostmcpdoctor`.
- `src/ghostmcpdoctor/__init__.py` / `__main__.py`
- `src/ghostmcpdoctor/scanner.py` - discovery, parsing, safe normalisation.
- `src/ghostmcpdoctor/checks.py` - all finding checks.
- `src/ghostmcpdoctor/reports.py` - report dict, Markdown renderer, writers.
- `src/ghostmcpdoctor/cli.py` - `scan` and `report` commands.

## CLI

```
ghostmcpdoctor scan [--config <path> ...] [--project <dir>] [--home <dir>]
                    [--out-dir <dir>] [--no-report] [--json] [paths ...]
ghostmcpdoctor report <mcpdoctor-report.json> [--out-dir <dir>] [--markdown]
```

Exit codes: 0 = scanned, no findings above info; 1 = warnings/errors found;
2 = could not scan (no configs found, or an explicitly named path missing).
`scan` writes `mcpdoctor-report.json` + `MCPDOCTOR.md` to `--out-dir`
(default: cwd) unless `--no-report`. `report` re-renders both from a prior
scan JSON without re-scanning.

## Discovery

Explicit paths win: a path may be a config file, or a directory (known
filenames `mcp.json`, `.mcp.json`, `.claude.json` plus `.cursor/mcp.json`
and `.vscode/mcp.json` under it are scanned). With no paths, default local
paths are used only when they exist (home/project roots overridable, which
is also the fixture-testing seam): `~/.claude.json`, `~/.claude/settings.json`,
`~/.config/claude/claude_desktop_config.json`, `~/.cursor/mcp.json`,
`~/.config/mcp/mcp.json`, `~/.mcp.json`, `./.mcp.json`, `./.claude.json`,
`./.cursor/mcp.json`, `./mcp.json`, `./.vscode/mcp.json`.

Containers understood: `mcpServers` (Claude Code / Cursor / generic) and
`servers` (VS Code), top-level and nested under Claude Code
`projects.<path>.mcpServers`. Client kind is inferred from the path.

## Checks (findings are server name + path + issue only)

- `DUPLICATE` warn - same server name in 2+ definitions (across files or
  across scopes of one file); one finding per extra definition.
- `MISSING-COMMAND` error / stale - path command does not exist, or bare
  command not on PATH (`shutil.which`).
- `MISSING-FILE` error / stale - a path-like argument or `cwd` that does not
  exist relative to the config directory (or the entry `cwd`).
- `EMPTY-SERVER` error - neither `command` nor `url`.
- `DISABLED` info / stale - entry marked disabled.
- `BROAD-FILESYSTEM` warn - a path argument is `/`, home, `~`, `$HOME`, a
  drive root, `..`, or ends `/*` (checked for every server, filesystem-shaped
  or not; narrow project paths are not flagged).
- `BROAD-ENV` warn - env key `*`, an env value that is a bare wildcard
  (checked internally at parse time, value discarded), or an
  `alwaysAllow` / `autoApprove` list containing `*`.
- `SHELL-WRAPPER` warn - command is `sh`/`bash`/`zsh`/`cmd`/`powershell`/`pwsh`.
- `PARSE-ERROR` error - config is not valid JSON or not an object; scanning
  continues with the other configs.

## The secret rule, implemented

Redaction happens at parse time in `scanner.py`, not at print time. The
normalised `Server` record stores env *key names* only (sorted) and a bool
for the bare-wildcard case; values are never stored, so checks, reports and
the CLI cannot leak them. Full argument lists are not stored (count only,
plus referenced file paths, skipping tokens that look secret-bearing). URL
userinfo and query strings are stripped (host only). Parse errors never echo
file content. Reports render env as `{key: "present"}` plus key-name lists.

## Verification performed by Agent A (own fixtures in /tmp, since removed)

- Messy fixture (Claude shape): filesystem server rooted at `/` flagged
  BROAD-FILESYSTEM; nonexistent binary flagged MISSING-COMMAND by name;
  nonexistent script arg flagged MISSING-FILE; `bash` flagged SHELL-WRAPPER;
  disabled entry flagged DISABLED; env wildcard flagged BROAD-ENV; empty
  entry flagged EMPTY-SERVER; exit 1.
- Secret canary: fixture env values (unique canary strings) appeared in NO
  stdout, JSON, or Markdown output; env key names did appear, as `present`.
  A URL with userinfo + token query produced `url_host` of host only, and
  the canary appeared in no output file.
- Duplicates: same name in Claude + Cursor fixtures -> 1 DUPLICATE finding;
  directory scan of a duplicates tree found both files (mcp.json +
  .cursor/mcp.json).
- Clean fixture (narrow paths, existing command/files): exit 0, 0 findings.
- Invalid JSON fixture: PARSE-ERROR, scanning continued, no file content echoed.
- No-configs case: exit 2 with a plain error.
- Default discovery via `--home`/`--project` fixture roots: found exactly
  the existing default-path configs.
- `report` re-render from a scan JSON reproduced both files and exit code.
- Agent B's fixtures (landed in parallel): messy / clean / empty / vscode /
  duplicates_across_files / duplicate_scopes all scan with the expected
  findings. `python3 -m py_compile` passes on all core modules.

## Known gaps / notes for parent verification

- B's `tests/conftest.py` as landed during A's run has a Python 3.12
  SyntaxError at line 143 (f-string brace escaping in `discover_subcommand`),
  so `pytest` currently fails at collection. That file is Agent B's surface;
  A did not edit it. A's core was verified manually against B's fixtures
  instead (results above).
- `pip install -e .` is blocked in this sandbox by PEP 668
  (externally-managed environment); the package runs via
  `PYTHONPATH=src python3 -m ghostmcpdoctor`, which is how all verification
  above was run. pyproject is standard setuptools, same shape as GhostVerify.
- Bare-name `MISSING-COMMAND` uses the scanning process PATH, which may
  differ from the client app's PATH; the report states this plainly.
- JSONC / TOML / YAML configs are out of scope in v0.1 (named in PLAN.md).
- Broad-env detection is deliberately narrow in v0.1 (wildcard key/value or
  wildcard allow-list). Passing many ordinary credential keys to a server is
  inventoried by key name, not flagged - a policy call for Ryan, not a bug.
