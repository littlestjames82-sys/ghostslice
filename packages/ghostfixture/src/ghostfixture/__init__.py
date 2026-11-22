"""GhostFixture: minimal repro project generator for GhostSlice.

Turns a GhostSlice bundle back into a small, real directory tree:
the files the bundle references, copied from the original project,
plus the local files those files import, and nothing else.
Flagged secrets are excluded by default, and everything left out
is named in the fixture manifest with a reason.

Public entry points: ``ghostfixture.cli.main`` (the command line),
``ghostfixture.build.build_fixture`` / ``check_fixture`` (the
library API), and ``ghostfixture mcp`` (the stdio MCP server).
"""

__version__ = "0.1.0"
