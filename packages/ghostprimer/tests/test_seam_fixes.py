"""Regression tests for the Oct 14, 2026 ecosystem seam fixes.

Seam 1: GhostSlice's canonical AWS access-key shape covers ASIA
temporary session keys as well as AKIA keys. A canary of that shape in
project memory blocks the memory item, and in code excludes the file.

Seam 2: a GhostHandoff pack supplied explicitly with --handoff-pack
carries the previous session's state, open loops and next steps into
the next Primer bundle, under the same secret scan and memory budget.
"""
from __future__ import annotations

import json
from pathlib import Path

from conftest import (FANIN_REL, build, combined, load_manifest, run_cli)


def asia_canary() -> str:
    # Assembled at runtime so the contiguous synthetic shape lives in
    # the generated fixture, not as a literal in this test source. It
    # is ASIA plus exactly 16 key characters, and it is not a real key.
    return "ASIA" + "1234567890ABCDEF"


def bundle_blob(bundle: Path) -> str:
    parts = []
    for path in Path(bundle).rglob("*"):
        if path.is_file():
            parts.append(path.read_bytes().decode(errors="ignore"))
    return "\n".join(parts)


def write_handoff_pack(tmp_path: Path, project: Path, *,
                       loop_detail: str | None = None,
                       step_text: str | None = None) -> Path:
    pack = tmp_path / "previous-handoff"
    pack.mkdir()
    data = {
        "tool": "ghosthandoff",
        "version": "0.1.0",
        "generated_at": "2026-10-14T08:00:00Z",
        "project": {"path": str(project), "name": "widgetforge"},
        "session_window": "last 2 hours",
        "git": {
            "available": True,
            "branch": "feature/session-loop",
            "head_short": "abc1234",
            "status": {
                "staged": ["src/widgetforge/core.py"],
                "unstaged": [],
                "untracked": ["notes.txt"],
                "staged_count": 1,
                "unstaged_count": 0,
                "untracked_count": 1,
            },
            "stash_count": 0,
            "commit_count": 2,
            "files_changed_total": 3,
            "commits": [{"short": "abc1234",
                         "subject": "Wire the session loop"}],
        },
        "reports": [{
            "kind": "pytest-lastfailed",
            "path": ".pytest_cache/v/cache/lastfailed",
            "modified": "2026-10-14T08:00:00Z",
            "summary": "1 test(s) recorded failing",
        }],
        "markers": {"total": 1, "code_total": 1, "docs_total": 0},
        "open_loops": [{
            "kind": "recorded-test-failures",
            "detail": loop_detail or "One parser test is recorded failing",
            "source": ".pytest_cache/v/cache/lastfailed",
        }],
        "next_steps": [{
            "text": step_text or
                    "Fix the recorded parser failure before slicing again",
            "source": ".pytest_cache/v/cache/lastfailed",
        }],
    }
    (pack / "handoff.json").write_text(json.dumps(data, indent=2))
    return pack


# --------------------------------------------------------------- seam 1

def test_asia_key_in_memory_blocks_the_item(starter_project, tmp_path):
    canary = asia_canary()
    agents = starter_project / "AGENTS.md"
    agents.write_text(
        agents.read_text()
        + "\n## Temporary access note\n\n"
        + f"The temporary session key is {canary} for this drill.\n")
    out = tmp_path / "bundle"
    proc = build(starter_project, out)
    assert proc.returncode == 0, combined(proc)
    assert canary not in bundle_blob(out)
    assert canary not in combined(proc)
    assert "Temporary access note" not in (out / "PRIMER.md").read_text()
    # The clean items from the same file still made the pack.
    assert "Always run the forge tests before committing." in \
        (out / "PRIMER.md").read_text()
    blocked = load_manifest(out).get("memory_blocked") or []
    assert any("AGENTS.md" in str(entry.get("path", ""))
               and "aws-access-key" in str(entry.get("reason", ""))
               for entry in blocked), blocked


def test_asia_key_in_code_excludes_the_file(starter_project, tmp_path):
    canary = asia_canary()
    core = starter_project / FANIN_REL
    core.write_text(
        core.read_text()
        + f'\nTEMPORARY_SESSION_KEY = "{canary}"\n')
    out = tmp_path / "bundle"
    proc = build(starter_project, out)
    assert proc.returncode == 0, combined(proc)
    assert canary not in bundle_blob(out)
    assert canary not in combined(proc)
    assert not (out / "files" / FANIN_REL).exists()
    manifest = load_manifest(out)
    assert all(entry.get("path") != FANIN_REL
               for entry in manifest.get("files") or [])
    not_included = manifest.get("not_included") or []
    assert any(entry.get("path") == FANIN_REL
               and "aws-access-key" in str(entry.get("reason", ""))
               for entry in not_included), not_included


# --------------------------------------------------------------- seam 2

def test_handoff_pack_directory_feeds_the_next_primer(
        starter_project, tmp_path):
    pack = write_handoff_pack(tmp_path, starter_project)
    out = tmp_path / "bundle"
    proc = build(starter_project, out, "--handoff-pack", pack)
    assert proc.returncode == 0, combined(proc)
    primer = (out / "PRIMER.md").read_text()
    assert "## Previous session handoff (source: GhostHandoff pack)" in primer
    assert "feature/session-loop" in primer
    assert "abc1234" in primer
    assert "One parser test is recorded failing" in primer
    assert "Fix the recorded parser failure before slicing again" in primer

    manifest = load_manifest(out)
    handoff_input = manifest.get("handoff_input") or {}
    assert handoff_input.get("input") == str(pack.resolve())
    assert handoff_input.get("input_kind") == "directory"
    assert handoff_input.get("json_path") == str(
        (pack / "handoff.json").resolve())
    assert handoff_input.get("items_included") == 3
    handoff_items = [item for item in manifest.get("memory_items") or []
                     if item.get("source_type") == "handoff"]
    assert {item.get("title") for item in handoff_items} == {
        "Previous session state",
        "Previous session open loops",
        "Previous session next steps",
    }
    check = run_cli("check", out)
    assert check.returncode == 0, combined(check)


def test_handoff_json_file_is_accepted_directly(starter_project, tmp_path):
    pack = write_handoff_pack(tmp_path, starter_project)
    out = tmp_path / "bundle"
    proc = build(starter_project, out,
                 "--handoff-pack", pack / "handoff.json")
    assert proc.returncode == 0, combined(proc)
    assert "One parser test is recorded failing" in \
        (out / "PRIMER.md").read_text()
    handoff_input = load_manifest(out).get("handoff_input") or {}
    assert handoff_input.get("input_kind") == "file"
    assert handoff_input.get("json_path") == str(
        (pack / "handoff.json").resolve())


def test_secret_inside_handoff_pack_blocks_only_that_item(
        starter_project, tmp_path):
    canary = asia_canary()
    pack = write_handoff_pack(
        tmp_path, starter_project,
        loop_detail=f"One parser test is recorded failing; "
                    f"the drill used {canary}")
    out = tmp_path / "bundle"
    proc = build(starter_project, out, "--handoff-pack", pack)
    assert proc.returncode == 0, combined(proc)
    assert canary not in bundle_blob(out)
    assert canary not in combined(proc)
    primer = (out / "PRIMER.md").read_text()
    assert "Previous session open loops" not in primer
    # The unflagged handoff items still carried forward.
    assert "feature/session-loop" in primer
    assert "Fix the recorded parser failure before slicing again" in primer
    manifest = load_manifest(out)
    assert (manifest.get("handoff_input") or {}).get("items_blocked") == 1
    blocked = manifest.get("memory_blocked") or []
    assert any(str((pack / "handoff.json").resolve()) == str(entry.get("path", ""))
               and "aws-access-key" in str(entry.get("reason", ""))
               for entry in blocked), blocked


def test_no_handoff_input_leaves_no_handoff_section(starter_project, tmp_path):
    out = tmp_path / "bundle"
    proc = build(starter_project, out)
    assert proc.returncode == 0, combined(proc)
    assert "Previous session handoff" not in (out / "PRIMER.md").read_text()
    assert "handoff_input" not in load_manifest(out)


def test_handoff_items_compete_for_the_memory_share(tmp_path):
    project = tmp_path / "tiny"
    (project / "src" / "tiny").mkdir(parents=True)
    (project / "pyproject.toml").write_text(
        '[project]\nname = "tiny"\nversion = "0.1.0"\n'
        'description = "Tiny drill project"\n')
    (project / "README.md").write_text("# Tiny\n\nA tiny drill project.\n")
    (project / "src" / "tiny" / "main.py").write_text(
        'def main():\n    return "tiny"\n')
    long_step = "Review the recorded failure path in full. " * 30
    pack = write_handoff_pack(tmp_path, project, step_text=long_step)
    # The pack helper names the project widgetforge in its state facts;
    # the tiny project's own name in the JSON project record is what
    # the mismatch check reads, so rewrite it to this project.
    data = json.loads((pack / "handoff.json").read_text())
    data["project"]["name"] = "tiny"
    (pack / "handoff.json").write_text(json.dumps(data, indent=2))

    out = tmp_path / "bundle"
    proc = build(project, out, "--budget", "400",
                 "--handoff-pack", pack)
    assert proc.returncode == 0, combined(proc)
    primer = (out / "PRIMER.md").read_text()
    assert "Previous session state" in primer
    assert long_step.strip() not in primer
    manifest = load_manifest(out)
    dropped = manifest.get("not_included") or []
    assert any(entry.get("path") == "handoff.json"
               and "memory budget share spent" in str(entry.get("reason", ""))
               for entry in dropped), dropped
