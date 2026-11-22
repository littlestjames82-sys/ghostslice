# Changelog

All notable changes to GhostMCP. Versions follow the package
version in `src/ghostmcp/__init__.py`.

## 0.4.0 (November 2026)

- HTTP servers: per-server `headers` from the config (the
  usual case is an Authorization bearer token) are now sent
  on every request. The HTTP transport previously ignored
  them entirely, so header-authenticated servers could not
  be reached. The `servers` listing reports header names
  only; values are never printed or returned.
- Tool annotations from `tools/list` (`readOnlyHint`,
  `destructiveHint`, `openWorldHint`, and any others) are
  preserved and reported by the CLI verbs and the `serve`
  daemon instead of being silently dropped.
- New tests cover both fixes (21 tests total). These changes
  came out of the GhostIDE D8 MCP polish work, where the
  dropped headers and annotations were found against a
  fixture server.

## 0.3.2 (November 2026)

- Serve daemon refinements from the GhostIDE Cycle 3 work:
  per-server session drop, idle session reaping, and session
  age and idle reporting.
- Package metadata caught up with the code: `pyproject.toml`
  had stayed at 0.1.0 through the 0.2 and 0.3 feature work,
  and the README still described the 0.1.0 scope. Both now
  match the shipped code.

## 0.3.0 (November 2026)

- New `serve` daemon: persistent sessions, one handshaken
  session per configured server kept alive across JSON-line
  requests on stdin, sessions dropped and reopened when the
  config file changes on disk, one retry on a fresh session
  after a dead-session failure.
- GhostIDE routes its MCP list and call traffic through the
  daemon, with the one-shot CLI verbs as automatic fallback
  (3 requests caused exactly 1 server spawn instead of 3 in
  the acceptance test).

## 0.2.0 (November 2026)

- New verbs: `resources`, `resource`, `prompts`, `prompt`
  (`resources/list`, `resources/read`, `prompts/list`,
  `prompts/get`).
- Binary resource contents are reported by base64 size only,
  never dumped.
- Suite grew from 10 to 15 tests.

## 0.1.0 (November 2026)

- First release: MCP client basics (`initialize`,
  `tools/list`, `tools/call`) over stdio and Streamable HTTP,
  from a standard `.mcp.json` config. Verbs: `servers`,
  `tools`, `call`. One JSON object per invocation; env names
  reported, env values never printed. Pure Python stdlib,
  zero dependencies. 10 tests.
