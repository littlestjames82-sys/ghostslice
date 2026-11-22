"""Hardening regressions (Oct 18 improve pass, lane: harden).

Each test pins a bug found by probing the previous build:
- code/README/metadata files that are symlinks out of the project were
  read and copied into the bundle without the resolved-path check the
  memory path already used;
- a GhostRecall bundle's ``exported_file`` was joined unchecked, so a
  ``../`` traversal or an absolute path read any file on disk;
- a directory (or otherwise unreadable file) in a memory slot crashed
  the build with IsADirectoryError instead of being blocked;
- an unresolvable path (symlink loop) escaped the path check as a raw
  RuntimeError and the private-memory check failed open on it;
- ``check`` accepted a forged manifest whose file entry pointed out of
  the bundle / project at a real file with a matching hash;
- writing a bundle followed pre-planted symlinks in the output tree
  and overwrote the link targets;
- the MCP server died on a syntactically valid non-object JSON line.
"""
from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ghostprimer.bundle import build_bundle, check_bundle, sha256_text
from ghostprimer import tokens
from ghostprimer.mcp_server import serve
from ghostprimer.memory import fallback_memory, recall_bundle_memory
from ghostprimer.scan import assert_project_local, is_private_memory


def _tiny_project(tmp_path: Path) -> Path:
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.1.0"\n'
        'description = "demo project"\n')
    (proj / "main.py").write_text("def main():\n    pass\n")
    return proj


def test_symlinked_code_file_outside_root_is_refused_not_copied(tmp_path):
    proj = _tiny_project(tmp_path)
    outside = tmp_path / "outside.py"
    outside.write_text('LEAKED = 1\n\n\ndef leaked_fn():\n    pass\n')
    (proj / "main.py").write_text("import evil\n\n\ndef main():\n    pass\n")
    os.symlink(outside, proj / "evil.py")
    out = tmp_path / "bundle"
    manifest = build_bundle(proj, out)
    assert "evil.py" not in [f["path"] for f in manifest["files"]]
    assert "leaked_fn" not in (out / "PRIMER.md").read_text()
    assert not (out / "files" / "evil.py").exists()
    assert any(e["path"] == "evil.py" and "outside" in e["reason"]
               for e in manifest["not_included"])


def test_symlinked_readme_outside_root_is_blocked(tmp_path):
    proj = _tiny_project(tmp_path)
    outside = tmp_path / "outside_readme.md"
    outside.write_text("# Outside\n\nOUTSIDE_README_SENTINEL paragraph.\n")
    os.symlink(outside, proj / "README.md")
    out = tmp_path / "bundle"
    manifest = build_bundle(proj, out)
    assert "OUTSIDE_README_SENTINEL" not in (out / "PRIMER.md").read_text()
    assert any(b["path"] == "README.md" for b in manifest["memory_blocked"])


def test_symlinked_pyproject_facts_are_not_used(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "main.py").write_text("def main():\n    pass\n")
    outside = tmp_path / "pyproject.toml"
    outside.write_text('[project]\nname = "OUTSIDE_NAME_SENTINEL"\n'
                       'version = "9.9.9"\n')
    os.symlink(outside, proj / "pyproject.toml")
    out = tmp_path / "bundle"
    manifest = build_bundle(proj, out)
    assert manifest["facts"]["name"] is None
    assert "OUTSIDE_NAME_SENTINEL" not in (out / "PRIMER.md").read_text()


def test_recall_exported_file_traversal_and_absolute_are_blocked(tmp_path):
    proj = _tiny_project(tmp_path)
    secret = tmp_path / "secret.txt"
    secret.write_text("RECALL_TRAVERSAL_SENTINEL")
    bundle = tmp_path / "recall"
    (bundle / "files").mkdir(parents=True)
    for exported in ("../secret.txt", str(secret)):
        (bundle / "manifest.json").write_text(json.dumps({"items": [{
            "id": "x", "status": "current", "title": "evil",
            "provenance": {"path": "a.md", "line": 1},
            "exported_file": exported}]}))
        items, blocked = recall_bundle_memory(proj, bundle)
        assert items == []
        assert blocked, f"exported_file={exported!r} was not blocked"


def test_recall_bundle_internal_export_still_consumed(tmp_path):
    proj = _tiny_project(tmp_path)
    bundle = tmp_path / "recall"
    (bundle / "files").mkdir(parents=True)
    (bundle / "files" / "item.md").write_text("Legit recall item text.")
    (bundle / "manifest.json").write_text(json.dumps({"items": [{
        "id": "x", "status": "current", "title": "ok",
        "provenance": {"path": "a.md", "line": 1},
        "exported_file": "files/item.md"}]}))
    items, blocked = recall_bundle_memory(proj, bundle)
    assert [i["text"] for i in items] == ["Legit recall item text."]
    assert blocked == []


def test_recall_malformed_manifest_raises_valueerror(tmp_path):
    proj = _tiny_project(tmp_path)
    bundle = tmp_path / "recall"
    bundle.mkdir()
    (bundle / "manifest.json").write_text("{ not json")
    with pytest.raises(ValueError):
        recall_bundle_memory(proj, bundle)


def test_memory_source_that_is_a_directory_is_blocked_not_a_crash(tmp_path):
    proj = _tiny_project(tmp_path)
    (proj / "AGENTS.md").mkdir()
    items, blocked = fallback_memory(proj)
    assert items == []
    assert any(b["path"] == "AGENTS.md" for b in blocked)
    # The whole build must survive it too.
    manifest = build_bundle(proj, tmp_path / "bundle")
    assert any(b["path"] == "AGENTS.md" for b in manifest["memory_blocked"])


def test_symlink_loop_path_check_fails_closed_with_valueerror(tmp_path):
    loop = tmp_path / "loop.py"
    os.symlink(loop, loop)
    assert is_private_memory(loop) is True  # fail closed, never fail open
    with pytest.raises(ValueError):
        assert_project_local(tmp_path, loop)


def test_check_rejects_forged_file_entry_escaping_bundle(tmp_path):
    proj = _tiny_project(tmp_path)
    outside = tmp_path / "outside.py"
    outside.write_text("def evil():\n    pass\n")
    out = tmp_path / "bundle"
    build_bundle(proj, out)
    text = outside.read_text()
    for forged in (os.path.relpath(outside, out / "files"), str(outside)):
        manifest = json.loads((out / "manifest.json").read_text())
        manifest["files"] = [{
            "path": forged, "mode": "signatures",
            "sliced_tokens": tokens.estimate(text, "python"),
            "sha256": sha256_text(text), "original_tokens": 1}]
        manifest["total_sliced_tokens"] = manifest["files"][0]["sliced_tokens"]
        (out / "manifest.json").write_text(json.dumps(manifest))
        code, report = check_bundle(out)
        assert code == 1 and not report["ok"], forged


def test_check_tolerates_malformed_manifest_entries(tmp_path):
    proj = _tiny_project(tmp_path)
    out = tmp_path / "bundle"
    build_bundle(proj, out)
    manifest = json.loads((out / "manifest.json").read_text())
    manifest["files"] = ["oops", 42, {"no_path": True}]
    manifest["memory_items"] = ["oops", {"provenance": "not-a-dict"}]
    (out / "manifest.json").write_text(json.dumps(manifest))
    code, report = check_bundle(out)  # must report, not raise
    assert code == 1 and report["errors"]


def test_build_does_not_follow_preplanted_output_symlinks(tmp_path):
    proj = _tiny_project(tmp_path)
    victim = tmp_path / "victim.txt"
    victim.write_text("ORIGINAL VICTIM")
    victim2 = tmp_path / "victim2.txt"
    victim2.write_text("ORIGINAL VICTIM 2")
    out = tmp_path / "bundle"
    (out / "files").mkdir(parents=True)
    os.symlink(victim, out / "files" / "main.py")
    os.symlink(victim2, out / "PRIMER.md")
    build_bundle(proj, out)
    assert victim.read_text() == "ORIGINAL VICTIM"
    assert victim2.read_text() == "ORIGINAL VICTIM 2"
    assert not (out / "files" / "main.py").is_symlink()
    assert not (out / "PRIMER.md").is_symlink()
    assert "def main" in (out / "files" / "main.py").read_text()


def test_mcp_server_survives_non_object_json_lines():
    bad_lines = "".join(line + "\n" for line in ("[]", "123", '"hi"'))
    inp = io.StringIO(bad_lines + '{"method": "tools/list", "id": 99}\n')
    out = io.StringIO()
    assert serve(stdin=inp, stdout=out) == 0
    responses = [json.loads(line) for line in out.getvalue().splitlines()]
    assert any(r.get("id") == 99 and "tools" in r.get("result", {})
               for r in responses)
