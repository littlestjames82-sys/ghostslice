# GhostMCP
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE) [![CI](https://github.com/littlestjames82-sys/ghostmcp/actions/workflows/ci.yml/badge.svg)](https://github.com/littlestjames82-sys/ghostmcp/actions/workflows/ci.yml) [![Release](https://img.shields.io/github/v/release/littlestjames82-sys/ghostmcp)](https://github.com/littlestjames82-sys/ghostmcp/releases) [![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

Ghost-native MCP (Model Context Protocol) **client** for Ghost
Developer Studio. GhostIDE shells out to GhostMCP to talk to MCP
servers from a standard MCP config file, the `.mcp.json` shape
used across the ecosystem: listing servers, listing a server's
tools, calling a tool, reading resources, and fetching prompts,
in pure Python stdlib so it runs anywhere GhostIDE runs,
including on-device in the phone APK. A persistent `serve`
daemon mode keeps one session per server alive across calls
for interactive use.

MIT licensed. Dependencies: none. Protocol version
`2024-11-05`; client info `{"name": "ghostmcp", "version":
"0.4.0"}`. JSON-RPC 2.0 throughout.

## Usage

```
python -m ghostmcp servers --config <path>
python -m ghostmcp tools --config <path> --server <name> [--timeout N]
python -m ghostmcp call --config <path> --server <name> --tool <name> --args '<json object>' [--timeout N]
python -m ghostmcp resources --config <path> --server <name> [--timeout N]
python -m ghostmcp resource --config <path> --server <name> --uri <uri> [--timeout N]
python -m ghostmcp prompts --config <path> --server <name> [--timeout N]
python -m ghostmcp prompt --config <path> --server <name> --name <name> --args '<json object>' [--timeout N]
python -m ghostmcp serve --config <path>
```

Every one-shot verb prints ONE JSON object to stdout.
`--timeout` is in seconds, covers the whole invocation, and
defaults to 30. `serve` is the exception: it reads JSON-line
requests on stdin and answers one JSON line per request, for
as long as it runs.

### servers

Lists the config's servers **without connecting to anything**:

```json
{"config": "mcp.json", "servers": [
  {"name": "files", "transport": "stdio",
   "target": "python3 server.py --root /tmp",
   "env_names": ["API_KEY"]},
  {"name": "remote", "transport": "http",
   "target": "https://example.com/mcp", "env_names": []}]}
```

`target` is the command and args joined for a stdio server, or
the url for an HTTP server. `env_names` carries env **names
only** — see Security below.

### tools

Connects, handshakes, and lists the server's tools
(`tools/list`, following `nextCursor` pagination):

```json
{"server": "files", "tools": [
  {"name": "read_file", "description": "Read a file.",
   "inputSchema": {"type": "object",
                   "properties": {"path": {"type": "string"}}}}]}
```

### call

Calls one tool and flattens its content: text blocks joined
with newlines, non-text blocks summarized as `[type: ...]`,
capped at 60,000 characters:

```json
{"server": "files", "tool": "read_file", "isError": false,
 "text": "the file's text"}
```

### resources, resource, prompts, prompt

The 0.2.0 verbs round out the read side of the protocol:
`resources` lists a server's resources (`resources/list`),
`resource` reads one by URI (`resources/read`), `prompts`
lists prompts (`prompts/list`), and `prompt` fetches one
rendered to messages (`prompts/get`). Binary resource contents
are reported by base64 size only, never dumped.

### serve

`serve` is the persistent session daemon added in 0.3.0. It
reads JSON-line requests on stdin (`{"id": 1, "verb": "tools",
"server": "files"}`), answers one JSON line per request, and
keeps one handshaken session per configured server alive
across requests, so interactive callers stop paying a fresh
server spawn for every list or call. The verbs mirror the CLI
(servers, tools, call, resources, resource, prompts, prompt)
plus `sessions` and `shutdown`. Sessions are dropped and
reopened when the config file changes on disk, a request that
fails on a dead session is retried once on a fresh one, and
idle sessions are reaped. GhostIDE routes its MCP traffic
through the daemon and falls back to the one-shot verbs if it
ever dies.

### Errors

Every failure prints `{"error": "..."}` to stdout and exits 2:
a missing or invalid config file, an unknown server name, bad
`--args` JSON, a server process that cannot start or dies
mid-session, a JSON-RPC error reply, an HTTP error status, and
timeouts.

One thing is deliberately **not** an error: a tool result the
server marked `isError: true`. That is the tool's own answer,
so it prints normally with `"isError": true` and exit 0.

## Config format

The standard MCP client config:

```json
{"mcpServers": {
  "files": {"command": "python3", "args": ["server.py"],
            "env": {"API_KEY": "..."}},
  "remote": {"url": "https://example.com/mcp"}}}
```

An entry with a `url` is an HTTP server; an entry with a
`command` is a stdio server. An entry with neither is an error.

## Transports

**Stdio.** The server is spawned as a child process per
invocation; JSON-RPC messages travel newline-delimited over its
stdin/stdout. The client sends `initialize`, then the
`notifications/initialized` notification, then the request. A
background reader matches replies by id; stray non-JSON lines
and server notifications are ignored, `ping` is answered, and
other server-initiated requests get a JSON-RPC method-not-found
reply. The child's stderr is drained and discarded so a chatty
server cannot deadlock on a full pipe. The child is **always**
terminated when the invocation ends — success, error, or
timeout.

**HTTP.** Each JSON-RPC message is a POST to the server `url`
(Streamable HTTP style). If a response carries an
`Mcp-Session-Id` header, the client sends it on every later
request in the same invocation. Bodies are accepted as plain
`application/json` or as `text/event-stream` (the reply is the
`data:` message whose id matches the request). A notification
such as `notifications/initialized` is posted and its (usually
empty, 202) reply ignored.

## Design: two session shapes

The one-shot verbs open a brand-new session per invocation, do
one listing or one call, and tear everything down. That makes
every invocation independent and crash-proof, since a hung or
hostile server can cost at most one timeout, and it is what
lets the same binary serve the desktop server and the phone.

The limit follows directly: **with the one-shot verbs, a
server that keeps state across calls inside its own process
will not keep it.** Anything held in the server's memory (an
in-memory cache, a half-finished multi-call workflow, a stdio
session's working set) resets on every call.

The `serve` daemon exists for exactly that limit. Callers that
need cross-call state or interactive speed hold sessions open
through the daemon; callers that need isolation use the
one-shot verbs. Servers that keep state in files, in a
database, or behind an HTTP session the server itself persists
are unaffected either way.

## Security

- Env **values** from the config are passed to stdio server
  processes (that is what they are for) but are never printed,
  returned, or logged anywhere by GhostMCP. The `servers` verb
  reports env names only, and error messages never quote config
  contents or a server's stderr.
- Tool `--args` are passed to the server and nowhere else; they
  are never logged.
- A config is a program launcher: a stdio entry runs its
  `command` with the invoking user's privileges. Only point
  GhostMCP at configs you trust, exactly as with any MCP host.

## Scope of 0.4.0, honestly

GhostMCP implements the client read-and-call surface:
`initialize`, `tools/list`, `tools/call`, `resources/list`,
`resources/read`, `prompts/list`, and `prompts/get`, over
stdio and HTTP, in one-shot CLI verbs and in the persistent
`serve` daemon. Auth is header-based: per-server `headers`
from the config (the usual case is an Authorization bearer
token) ride every HTTP request, and only the header names
are ever listed, never the values. GhostMCP does not run an
interactive OAuth flow itself; GhostIDE layers OAuth 2.0
with PKCE on top of this header support for servers that
need it. It does **not** implement sampling or elicitation
(server-initiated requests beyond `ping` are refused), or
tool-list change notifications. Those land only if a real
GhostIDE need pulls them in.

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
