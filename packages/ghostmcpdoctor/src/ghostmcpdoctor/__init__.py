"""GhostMCP Doctor: read-only auditor for local MCP / agent-client configs.

Zero-dependency Python stdlib only. Local only, no network, never edits
a scanned config. Env values from config files are secrets: they are
discarded at parse time and never appear in any report or message.
Findings are server name + path + issue only.
"""

__version__ = "0.1.0"
