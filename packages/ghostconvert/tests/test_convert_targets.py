"""Per-target conversion tests against the golden bundle.

Hard rules pinned here:
- converted artifacts keep the manifest's file order;
- full file bodies from the bundle appear verbatim in every target;
- mode labels stay visible in section headers;
- excluded file bodies never appear;
- every target directory carries a LOSSES.md.
"""
from __future__ import annotations

import re

import pytest

from conftest import (body_of, combined, files_with_bodies, manifest_order,
                      run_gc)

TARGET_ARTIFACT = {
    "agents": "AGENTS.md",
    "copilot": ".github/copilot-instructions.md",
    "generic": "prompt.md",
}


def convert_ok(bundle, target, out):
    proc = run_gc("convert", str(bundle), "--to", target, "-o", str(out))
    assert proc.returncode == 0, combined(proc)
    return proc


def section_positions(text: str, paths: list[str]) -> list[int]:
    positions = []
    for path in paths:
        idx = text.find(f"File: {path} (mode:")
        assert idx >= 0, f"no section header for {path}"
        positions.append(idx)
    return positions


def assert_order_and_bodies(text: str, bundle):
    entries = files_with_bodies(bundle)
    paths = [e["path"] for e in entries]
    positions = section_positions(text, paths)
    assert positions == sorted(positions), (
        f"sections out of manifest order: {list(zip(paths, positions))}")
    for e in entries:
        body = body_of(bundle, e["path"]).rstrip("\n")
        assert body in text, f"body of {e['path']} not carried verbatim"
        header = f"File: {e['path']} (mode: {e['mode']})"
        assert header in text, f"mode label missing for {e['path']}"


@pytest.mark.parametrize("target", ["agents", "copilot", "generic"])
def test_single_file_targets_keep_order_bodies_and_modes(
        golden_bundle, tmp_path, target):
    out = tmp_path / "out"
    convert_ok(golden_bundle, target, out)
    artifact = out / TARGET_ARTIFACT[target]
    assert artifact.is_file()
    text = artifact.read_text(encoding="utf-8")
    assert_order_and_bodies(text, golden_bundle)
    assert (out / "LOSSES.md").is_file()


@pytest.mark.parametrize("target", ["agents", "copilot"])
def test_document_targets_open_with_conversion_header(
        golden_bundle, tmp_path, target):
    out = tmp_path / "out"
    convert_ok(golden_bundle, target, out)
    text = (out / TARGET_ARTIFACT[target]).read_text(encoding="utf-8")
    head = text[:600]
    assert "GhostConvert" in head
    assert "GhostSlice" in head


def test_agents_md_is_named_agents_md_at_outdir_root(golden_bundle, tmp_path):
    out = tmp_path / "out"
    convert_ok(golden_bundle, "agents", out)
    assert (out / "AGENTS.md").is_file()
    assert not (out / "prompt.md").exists()


def test_generic_uses_prompt_style_file_headers(golden_bundle, tmp_path):
    out = tmp_path / "out"
    convert_ok(golden_bundle, "generic", out)
    text = (out / "prompt.md").read_text(encoding="utf-8")
    for e in files_with_bodies(golden_bundle):
        assert f"# File: {e['path']} (mode: {e['mode']})" in text


def test_excluded_file_body_never_appears(golden_bundle, tmp_path):
    out = tmp_path / "out"
    convert_ok(golden_bundle, "all", out)
    for artifact in out.rglob("*"):
        if artifact.is_file() and artifact.name != "LOSSES.md":
            text = artifact.read_text(encoding="utf-8")
            assert "VENDORED = True" not in text, artifact
            assert "File: vendor/blob.py" not in text, artifact


def test_cursor_groups_rules_with_frontmatter(golden_bundle, tmp_path):
    out = tmp_path / "out"
    convert_ok(golden_bundle, "cursor", out)
    rules = sorted((out / ".cursor" / "rules").glob("*.mdc"))
    assert rules, "no .mdc rule files written"
    assert (out / "LOSSES.md").is_file()

    entries = files_with_bodies(golden_bundle)
    # Every file with a body appears in exactly one rule file.
    seen: dict[str, str] = {}
    for rule in rules:
        text = rule.read_text(encoding="utf-8")
        assert text.startswith("---"), rule
        frontmatter = text.split("---", 2)[1]
        assert "globs:" in frontmatter, rule
        for e in entries:
            if f"File: {e['path']} (mode:" in text:
                assert e["path"] not in seen, e["path"]
                seen[e["path"]] = rule.name
                # globs in the frontmatter name the original paths.
                assert e["path"] in frontmatter, (rule, e["path"])
                body = body_of(golden_bundle, e["path"]).rstrip("\n")
                assert body in text, (rule, e["path"])
    assert set(seen) == {e["path"] for e in entries}


def test_cursor_keeps_manifest_order_inside_each_group(
        golden_bundle, tmp_path):
    out = tmp_path / "out"
    convert_ok(golden_bundle, "cursor", out)
    entries = files_with_bodies(golden_bundle)
    for rule in (out / ".cursor" / "rules").glob("*.mdc"):
        text = rule.read_text(encoding="utf-8")
        members = [e["path"] for e in entries
                   if f"File: {e['path']} (mode:" in text]
        positions = [text.find(f"File: {p} (mode:") for p in members]
        assert positions == sorted(positions), rule


def test_cursor_groups_by_top_level_directory(golden_bundle, tmp_path):
    out = tmp_path / "out"
    convert_ok(golden_bundle, "cursor", out)
    rules = {r.name: r.read_text(encoding="utf-8")
             for r in (out / ".cursor" / "rules").glob("*.mdc")}
    src_rules = [t for t in rules.values() if "File: src/app.py" in t]
    assert len(src_rules) == 1
    assert "File: src/util.py" in src_rules[0]
    docs_rules = [t for t in rules.values() if "File: docs/guide.md" in t]
    assert len(docs_rules) == 1
    assert "File: src/app.py" not in docs_rules[0]


def test_convert_all_writes_four_subdirectories(golden_bundle, tmp_path):
    out = tmp_path / "out"
    convert_ok(golden_bundle, "all", out)
    for target, artifact in TARGET_ARTIFACT.items():
        assert (out / target / artifact).is_file(), target
        assert (out / target / "LOSSES.md").is_file(), target
    assert list((out / "cursor" / ".cursor" / "rules").glob("*.mdc"))
    # Each single-file target inside `all` matches its standalone output.
    solo = tmp_path / "solo"
    convert_ok(golden_bundle, "agents", solo)
    assert (out / "agents" / "AGENTS.md").read_text(encoding="utf-8") == \
        (solo / "AGENTS.md").read_text(encoding="utf-8")


def test_cli_output_summarises_losses(golden_bundle, tmp_path):
    proc = convert_ok(golden_bundle, "agents", tmp_path / "out")
    assert re.search(r"loss", combined(proc), re.IGNORECASE)
