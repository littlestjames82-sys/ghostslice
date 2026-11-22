"""Repeated lines collapse to one exemplar with the correct count.
The exemplar text appears exactly once in the readable pack, and its
true multiplicity from the fixture is stated with it (in the pack text
or the manifest)."""
import json
import re

from conftest import (
    CACHE_WARN,
    CACHE_WARN_COUNT,
    ERROR_LINE,
    ERROR_COUNT,
    HEARTBEAT,
    HEARTBEAT_COUNT,
    build_pack,
    load_manifest,
    pack_text,
)


def _count_stated_near(text, needle, count):
    """True if some line containing `needle` also states `count`,
    or the following line does (count rendered as e.g. x40, (40), 40x)."""
    lines = text.splitlines()
    pat = re.compile(rf"(?<![0-9]){count}(?![0-9])")
    for i, ln in enumerate(lines):
        if needle in ln:
            window = ln + "\n" + (lines[i + 1] if i + 1 < len(lines) else "")
            if pat.search(window):
                return True
    return False


def _count_in_manifest(manifest, needle, count):
    blob = json.dumps(manifest)
    # look for an object-ish pairing: needle text and the count both
    # present is weak, so require them within 200 chars of each other
    idx = blob.find(needle.split()[0])
    while idx != -1:
        if re.search(rf"(?<![0-9]){count}(?![0-9])", blob[idx : idx + 400]):
            return True
        idx = blob.find(needle.split()[0], idx + 1)
    return False


def _assert_single_exemplar(log_copy, tmp_path, needle, count, label):
    proc, out = build_pack(log_copy, tmp_path / "pack")
    assert proc.returncode == 0, proc.stderr
    text = pack_text(out)
    occurrences = text.count(needle)
    assert occurrences == 1, (
        f"{label}: exemplar text appears {occurrences} times in the pack, "
        "expected exactly 1 (repeats must collapse to one exemplar)"
    )
    manifest = load_manifest(out)
    stated = _count_stated_near(text, needle, count) or _count_in_manifest(
        manifest, needle, count
    )
    assert stated, (
        f"{label}: true count {count} is not stated with the exemplar "
        "in the pack text or the manifest"
    )


def test_heartbeat_collapses_to_one_exemplar_with_count(log_copy, tmp_path):
    _assert_single_exemplar(log_copy, tmp_path, HEARTBEAT, HEARTBEAT_COUNT, "heartbeat")


def test_cache_warn_collapses_to_one_exemplar_with_count(log_copy, tmp_path):
    _assert_single_exemplar(log_copy, tmp_path, CACHE_WARN, CACHE_WARN_COUNT, "cache warn")


import pytest


# D1 fixed Oct 14, 2026 (see FIX_REPORT.md): window-claimed lines now
# carry per-signature occurrence accounting and the manifest/pack state
# exact counts for repeats inside error windows. The former
# strict-xfail marker was removed by the parent on the fix landing, so
# this test is now a permanent pass requirement.
def test_error_line_true_count_is_stated(log_copy, tmp_path):
    """The repeated ERROR also opens windows, so its text may appear in
    a window as well as in an exemplar; the hard rule pinned here is
    that its true count (5) is stated with it somewhere in pack or
    manifest, never shown as 5 raw copies with no count."""
    proc, out = build_pack(log_copy, tmp_path / "pack")
    assert proc.returncode == 0, proc.stderr
    text = pack_text(out)
    manifest = load_manifest(out)
    stated = _count_stated_near(
        text, "db connection failed", ERROR_COUNT
    ) or _count_in_manifest(manifest, "db connection failed", ERROR_COUNT)
    assert stated, "true count 5 of the repeated ERROR is not stated anywhere"
