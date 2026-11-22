"""Fixture-integrity tests: pure, no core required.

These pin the fixtures to the PLAN.md verification bar so the contract
tests that consume them cannot silently drift:
- planted waste: src/hot.py is Read exactly 5 times; src/legacy.py is
  never mentioned anywhere in the session;
- zero waste: every bundle file is referenced exactly once, nothing more;
- secret fixtures: the planted secret-shaped string is present in the
  INPUT (otherwise the privacy test would be vacuous);
- manifest: totals equal the sum of per-file entries, and every sha256
  matches the bundle file bytes (all fixture modes are `full`).
"""
import hashlib
import json

from conftest import (BUNDLE, HOT, NEVER, PLANTED_SECRET, PROJECT, SESSIONS,
                      manifest)


def read_jsonl(path):
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def read_tool_uses(rows, name="Read"):
    paths = []
    for row in rows:
        content = row.get("message", {}).get("content")
        if isinstance(content, list):
            for block in content:
                if block.get("type") == "tool_use" and block.get("name") == name:
                    paths.append(block.get("input", {}).get("file_path"))
    return paths


def test_manifest_totals_are_internal_sums():
    m = manifest()
    assert m["total_original_tokens"] == sum(f["original_tokens"] for f in m["files"])
    assert m["total_sliced_tokens"] == sum(f["sliced_tokens"] for f in m["files"])
    assert m["total_saved_tokens"] == m["total_original_tokens"] - m["total_sliced_tokens"]


def test_manifest_sha256_matches_bundle_files():
    for entry in manifest()["files"]:
        data = (BUNDLE / "files" / entry["path"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == entry["sha256"], entry["path"]
        assert (PROJECT / entry["path"]).read_bytes() == data, entry["path"]


def test_all_sessions_are_valid_jsonl_with_session_ids():
    for name in ["planted_waste_1", "planted_waste_2", "planted_waste_3",
                 "zero_waste_1", "zero_waste_2", "zero_waste_3",
                 "secret_1", "secret_2", "secret_3"]:
        rows = read_jsonl(SESSIONS / f"{name}.jsonl")
        assert rows, name
        assert all(r.get("sessionId") for r in rows), name
        assert all(r.get("type") in ("user", "assistant") for r in rows), name


def test_planted_waste_hot_file_read_exactly_five_times():
    for i in (1, 2, 3):
        rows = read_jsonl(SESSIONS / f"planted_waste_{i}.jsonl")
        reads = read_tool_uses(rows)
        assert reads.count(HOT) == 5, (i, reads)


def test_planted_waste_never_references_legacy_file():
    for i in (1, 2, 3):
        text = (SESSIONS / f"planted_waste_{i}.jsonl").read_text(encoding="utf-8")
        assert "legacy" not in text, i
        assert NEVER not in read_tool_uses(read_jsonl(SESSIONS / f"planted_waste_{i}.jsonl"))


def test_zero_waste_references_every_bundle_file_exactly_once():
    bundle_paths = {f["path"] for f in manifest()["files"]}
    for i in (1, 2, 3):
        rows = read_jsonl(SESSIONS / f"zero_waste_{i}.jsonl")
        reads = read_tool_uses(rows)
        assert set(reads) == bundle_paths, (i, reads)
        assert len(reads) == len(bundle_paths), (i, reads)  # no re-reads at all


def test_secret_fixtures_actually_contain_the_planted_secret():
    for i in (1, 2, 3):
        text = (SESSIONS / f"secret_{i}.jsonl").read_text(encoding="utf-8")
        assert PLANTED_SECRET in text, i


def test_secret_string_appears_nowhere_else_in_fixtures():
    for path in [SESSIONS / n for n in
                 ("planted_waste_1.jsonl", "zero_waste_1.jsonl")]:
        assert PLANTED_SECRET not in path.read_text(encoding="utf-8")
