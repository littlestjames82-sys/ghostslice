"""Secrets guard: a secret-shaped literal in a project memory file blocks
that memory item. The literal never appears anywhere in the bundle, the
block is recorded, and the rest of the bundle is still built."""
from __future__ import annotations

import json
from pathlib import Path

from conftest import PLANTED_SECRET, build, combined, load_manifest


def test_secret_memory_item_blocked(secret_project, tmp_path):
    out = tmp_path / "bundle"
    proc = build(secret_project, out)
    assert proc.returncode == 0, combined(proc)
    for path in Path(out).rglob("*"):
        if path.is_file():
            assert PLANTED_SECRET not in path.read_bytes().decode(
                errors="ignore"), f"secret leaked into {path}"
    manifest_blob = json.dumps(load_manifest(out)).lower()
    output_blob = combined(proc).lower()
    recorded = any("agents.md" in blob and (
        "block" in blob or "secret" in blob or "exclud" in blob)
        for blob in (manifest_blob, output_blob))
    assert recorded, "blocked memory item was not recorded anywhere"
    primer = (out / "PRIMER.md").read_text()
    assert "secretmem" in primer  # the rest of the pack still built
    assert "rotates whenever the staging box is rebuilt" not in primer
