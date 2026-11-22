# Examples

Sample MCP configs for trying GhostMCP Doctor. **Every value in
these files is fake.** Env values are labelled
`FAKE-EXAMPLE-...-not-a-real-secret`, commands point at example
module names, and the one "missing" command is a deliberately
invented name. Nothing here is a real credential, a real server,
or a real path.

| File | Shape | What it shows |
|---|---|---|
| `claude-code.mcp.json` | Claude Code (`mcpServers`) | A clean config: two narrow servers, one env key (fake) reported by name only. Scans with 0 findings. |
| `cursor.mcp.json` | Cursor (`mcpServers`) | Defines `project-docs` again, the same name as in the Claude Code sample: scanning both files together reports a `DUPLICATE`. |
| `antigravity.mcp_config.json` | Generic (`mcpServers`, `mcp_config` filename) | Another client shape carrying an env key (fake) that is reported present/absent only. |
| `vscode.mcp.json` | VS Code (`servers`) | The VS Code container shape: top-level `servers`, not `mcpServers`. |
| `messy.mcp.json` | Generic (`mcpServers`) | The findings showcase: a filesystem server granted `/` under two names, a command that does not exist, and a key-holder server whose fake env values must never appear in any report. |

## Try one now

From the GhostMCP Doctor folder (no install needed):

```bash
PYTHONPATH=src python3 -m ghostmcpdoctor scan examples/messy.mcp.json --out-dir /tmp/gmd-messy
```

Expect 4 servers, 3 findings, and exit code 1: two
`BROAD-FILESYSTEM` warnings for the servers granted `/`, and one
`MISSING-COMMAND` error. The fourth server, `key-holder`, produces
no finding, and its fake env values appear in no report: check with
`grep -rn "FAKE-EXAMPLE" /tmp/gmd-messy/` (no matches).

See [WALKTHROUGH.md](WALKTHROUGH.md) for the full set of commands
to run and the verified output to expect, including the clean
config, the cross-file duplicate, and re-rendering a report without
re-scanning.
