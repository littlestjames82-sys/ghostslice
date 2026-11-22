"""GhostConvert: convert a GhostSlice .claude_context bundle into other
agent instruction formats (AGENTS.md, Cursor rules, Copilot instructions,
generic single-file prompt), naming whatever each target cannot carry.

Data-only transformation. The source bundle is read, never written.
Python stdlib only, local only, no network.
"""

__version__ = "0.1.0"
