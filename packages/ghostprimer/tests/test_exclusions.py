"""Hard rule: project-local sources only. Memory files that resolve
outside the project root are refused, and the user's private memory
locations are refused even when a project file points straight at them.
Sentinels must never reach the bundle, and the refusal must be recorded.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from conftest import (FIXTURES, build, bundle_blob, combined,
                      load_manifest)

OUTSIDE_SENTINEL = "OUTSIDE_SENTINEL_TEXT_42"
PRIVATE_SENTINEL = "PRIVATE_MEMORY_SENTINEL_99"


def _copy_starter(dest):
    shutil.copytree(FIXTURES / "starter_project", dest)
    return dest


def _refusal_recorded(bundle, proc, filename):
    haystacks = [combined(proc).lower()]
    if (Path(bundle) / "manifest.json").exists():
        haystacks.append(json.dumps(load_manifest(bundle)).lower())
    return any(filename in h and any(
        word in h for word in ("refus", "exclud", "outside", "block",
                               "skip", "not included", "not_included"))
        for h in haystacks)


def test_outside_root_memory_source_refused(tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text(f"# Outside notes\n\n{OUTSIDE_SENTINEL}\n")
    project = _copy_starter(tmp_path / "proj")
    agents = project / "AGENTS.md"
    agents.unlink()
    os.symlink(outside, agents)
    out = tmp_path / "bundle"
    proc = build(project, out)
    if out.exists():
        assert OUTSIDE_SENTINEL not in bundle_blob(out)
    assert _refusal_recorded(out, proc, "agents.md"), (
        "outside-root AGENTS.md was silently used or silently dropped")


def test_private_memory_location_refused(tmp_path):
    fake_home = tmp_path / "fakehome"
    (fake_home / "memory").mkdir(parents=True)
    private = fake_home / "MEMORY.md"
    private.write_text(f"# Private memory\n\n{PRIVATE_SENTINEL}\n")
    project = _copy_starter(tmp_path / "proj")
    decisions = project / "DECISIONS.md"
    decisions.unlink()
    os.symlink(private, decisions)
    out = tmp_path / "bundle"
    proc = build(project, out, env_extra={"HOME": str(fake_home)})
    if out.exists():
        assert PRIVATE_SENTINEL not in bundle_blob(out)
    assert _refusal_recorded(out, proc, "decisions.md"), (
        "a memory source resolving into the private memory location was "
        "not visibly refused")
