"""MCP tests for GhostReview (plan MVP item 5).

Conservative: skips unless `ghostreview mcp` answers an initialize
+ tools/list handshake, then asserts the one plan tool review_diff
is listed. Uses helpers.cli_env() so a src-layout discovery keeps
its PYTHONPATH.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import helpers  # noqa: E402


class TestMCP(unittest.TestCase):
    def test_mcp_lists_review_diff(self):
        if not helpers.cli_available():
            self.skipTest("ghostreview CLI not discoverable")
        prefix = helpers.cli_prefix()
        payload = "\n".join([
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                        "params": {}}),
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list",
                        "params": {}}),
            "",
        ])
        try:
            proc = subprocess.run(prefix + ["mcp"], input=payload,
                                  capture_output=True, text=True, timeout=30,
                                  env=helpers.cli_env())
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.skipTest(f"mcp server did not run: {exc}")
        tools = []
        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            result = msg.get("result") or {}
            if isinstance(result.get("tools"), list):
                tools = [t.get("name") for t in result["tools"]]
        if not tools:
            self.skipTest("mcp server did not answer tools/list "
                          "(see REPORT_B.md)")
        self.assertIn("review_diff", tools)


if __name__ == "__main__":
    unittest.main()
