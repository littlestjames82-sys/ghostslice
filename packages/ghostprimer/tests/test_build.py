"""Build contract: layout, facts, starter selection, manifest honesty."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from conftest import (ENTRY_REL, FANIN_REL, ORPHAN_REL, build, combined,
                      file_entry, load_manifest, manifest_primer_sha,
                      sha256_file)


def test_build_writes_bundle_layout(built_bundle):
    assert (built_bundle / "PRIMER.md").is_file()
    assert (built_bundle / "manifest.json").is_file()
    assert (built_bundle / "files").is_dir()


def test_facts_extracted_from_project(built_bundle):
    primer = (built_bundle / "PRIMER.md").read_text()
    manifest = load_manifest(built_bundle)
    blob = primer + json.dumps(manifest)
    assert "widgetforge" in blob
    assert "0.3.2" in blob
    assert "Widget forging toolkit" in blob  # pyproject description, verbatim


def test_entry_point_included_at_signatures(built_bundle):
    manifest = load_manifest(built_bundle)
    entry = file_entry(manifest, ENTRY_REL)
    assert entry is not None, "entry point missing from manifest"
    assert entry.get("mode") == "signatures", entry
    sliced = built_bundle / "files" / ENTRY_REL
    assert sliced.is_file(), "entry point slice not written under files/"
    text = sliced.read_text()
    assert "def main" in text
    assert "blank-1" not in text  # body statement: signatures strips bodies


def test_highest_fanin_module_included(built_bundle):
    manifest = load_manifest(built_bundle)
    assert file_entry(manifest, FANIN_REL) is not None
    assert (built_bundle / "files" / FANIN_REL).is_file()


def test_orphan_not_sliced_but_named_not_included(built_bundle):
    assert not (built_bundle / "files" / ORPHAN_REL).exists()
    primer = (built_bundle / "PRIMER.md").read_text()
    manifest = json.dumps(load_manifest(built_bundle))
    assert "orphan.py" in primer or "orphan.py" in manifest, (
        "the not-included file must be named somewhere auditable")
    assert "def unused_thing" not in primer
    assert "ORPHAN_MARKER" not in primer


def test_manifest_totals_reconcile(starter_project, tmp_path):
    out = tmp_path / "bundle"
    proc = build(starter_project, out)
    assert proc.returncode == 0, combined(proc)
    manifest = load_manifest(out)
    for key in ("total_original_tokens", "total_sliced_tokens"):
        assert isinstance(manifest.get(key), int), f"{key} missing/not int"
    files = manifest.get("files") or []
    assert files, "no files recorded"
    sliced_sum = sum(e.get("sliced_tokens") or 0 for e in files)
    original_sum = sum(e.get("original_tokens") or 0 for e in files)
    memory_sliced = 0
    for item in manifest.get("memory_items") or manifest.get("memory") or []:
        if isinstance(item, dict):
            memory_sliced += item.get("sliced_tokens") or 0
    assert manifest["total_sliced_tokens"] in (
        sliced_sum, sliced_sum + memory_sliced), (
        f"total_sliced_tokens {manifest['total_sliced_tokens']} != "
        f"files sum {sliced_sum} (+ memory {memory_sliced})")
    assert manifest["total_original_tokens"] >= original_sum
    assert manifest["total_sliced_tokens"] <= manifest["total_original_tokens"]


def test_manifest_file_hashes_match(starter_project, tmp_path):
    out = tmp_path / "bundle"
    proc = build(starter_project, out)
    assert proc.returncode == 0, combined(proc)
    manifest = load_manifest(out)
    checked = 0
    for entry in manifest.get("files") or []:
        rel = entry.get("path")
        recorded = [v for k, v in entry.items()
                    if "sha256" in k and isinstance(v, str)]
        if not rel or not recorded:
            continue
        bundled = out / "files" / rel
        source = starter_project / rel
        digests = set()
        if bundled.is_file():
            digests.add(sha256_file(bundled))
        if source.is_file():
            digests.add(sha256_file(source))
        assert any(r in digests for r in recorded), (
            f"{rel}: recorded sha matches neither bundle file nor source")
        checked += 1
    assert checked >= 2, "too few file hashes were checkable"


def test_primer_md_sha_recorded_in_manifest(built_bundle):
    manifest = load_manifest(built_bundle)
    actual = hashlib.sha256((built_bundle / "PRIMER.md").read_bytes()).hexdigest()
    assert actual in manifest_primer_sha(manifest), (
        "manifest does not record the sha256 of PRIMER.md")


def test_extractive_only_bundle_text(built_bundle):
    primer = (built_bundle / "PRIMER.md").read_text()
    # Verbatim sentences lifted from project memory files.
    assert "Always run the forge tests before committing." in primer
    assert "Ship releases on Fridays after the full suite passes." in primer
    # Every signature line in the sliced core derives from a source line.
    # AST-derived signatures may normalise spacing (``int = 900`` comes
    # back as ``int=900``), so compare with all whitespace removed; names
    # and arguments must still match a real source line exactly.
    sliced = (built_bundle / "files" / FANIN_REL).read_text()
    source = (Path(__file__).parent / "fixtures" / "starter_project"
              / FANIN_REL).read_text()
    squashed = {line.replace(" ", "") for line in source.splitlines()}
    for line in sliced.splitlines():
        if line.strip().startswith(("def ", "class ")):
            assert line.replace(" ", "") in squashed, \
                f"invented line: {line}"
    # Template framing is labelled as template in the manifest (plan rule).
    assert "template" in json.dumps(load_manifest(built_bundle)).lower()


def test_readme_extract_in_primer(built_bundle):
    primer = (built_bundle / "PRIMER.md").read_text()
    assert "Usage" in primer
    assert "Heat the furnace, place the blank" in primer
