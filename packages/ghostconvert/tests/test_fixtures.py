"""Fixture-validity tests: the golden bundle really is a GhostSlice
bundle with the mixed modes the conversion tests rely on."""
from __future__ import annotations

import hashlib

from conftest import (body_of, files_with_bodies, ghostslice_available,
                      manifest_order, read_manifest)


def test_golden_bundle_built_by_real_ghostslice(golden_bundle):
    assert ghostslice_available()
    manifest = read_manifest(golden_bundle)
    assert manifest["tool"] == "ghostslice"
    assert (golden_bundle / "PROMPT.md").is_file()
    assert (golden_bundle / "files").is_dir()


def test_golden_bundle_has_mixed_modes(golden_bundle):
    modes = {e["path"]: e["mode"] for e in manifest_order(golden_bundle)}
    assert modes["src/app.py"] == "full"
    assert modes["src/util.py"] == "signatures"
    assert modes["vendor/blob.py"] == "exclude"


def test_golden_bundle_has_an_excluded_file_with_no_body(golden_bundle):
    excluded = [e for e in manifest_order(golden_bundle)
                if e["mode"] == "exclude"]
    assert excluded, "golden bundle must contain an excluded file"
    for e in excluded:
        assert body_of(golden_bundle, e["path"]) is None


def test_golden_bundle_bodies_match_manifest_hashes(golden_bundle):
    checked = 0
    for e in files_with_bodies(golden_bundle):
        body = body_of(golden_bundle, e["path"])
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        if e.get("sha256"):
            assert digest == e["sha256"], e["path"]
            checked += 1
    assert checked >= 3, "expected several hashed bodies in the bundle"


def test_golden_bundle_manifest_entries_carry_tokens(golden_bundle):
    for e in manifest_order(golden_bundle):
        assert isinstance(e.get("original_tokens"), int), e["path"]
        assert isinstance(e.get("sliced_tokens"), int), e["path"]
    manifest = read_manifest(golden_bundle)
    assert manifest["total_original_tokens"] > 0
    assert manifest["total_sliced_tokens"] > 0


def test_golden_bundle_prompt_sections_match_manifest(golden_bundle):
    prompt = (golden_bundle / "PROMPT.md").read_text(encoding="utf-8")
    for e in files_with_bodies(golden_bundle):
        header = f"# File: {e['path']} (mode: {e['mode']})"
        assert header in prompt, e["path"]
