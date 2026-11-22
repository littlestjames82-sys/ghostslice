"""GhostMCP: Ghost-native MCP (Model Context Protocol) client.

GhostMCP speaks JSON-RPC 2.0 to MCP servers from a standard MCP
config file (the ``.mcp.json`` shape): stdio servers spawned as
child processes, and HTTP servers over Streamable-HTTP-style
POSTs. It covers the ``initialize`` handshake, ``tools/list``
and ``tools/call``, and (0.2.0) ``resources/list``,
``resources/read``, ``prompts/list`` and ``prompts/get`` — in
pure Python stdlib, so it runs anywhere GhostIDE runs,
including on-device. Binary resource contents are reported by
size only, never dumped.

Design: one fresh session per CLI invocation. A server process
is spawned, used for a single listing or call, and always
terminated; nothing is kept alive between invocations. Env
values from the config are passed to stdio servers but never
printed — only env names are ever reported.
"""

__version__ = "0.4.0"
