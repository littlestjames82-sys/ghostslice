"""Check contract: fresh bundle passes, tampering fails, a missing bundle
cannot be checked, and a Python-fixture bundle passes ghostslice check."""
from __future__ import annotations

import json

import pytest

from conftest import (ENTRY_REL, build, combined, ghostslice_available,
                      run_cli, run_ghostslice_check)


def test_check_passes_on_fresh_bundle(built_bundle):
    proc = run_cli("check", built_bundle)
    assert proc.returncode == 0, combined(proc)


def test_check_fails_after_primer_tamper(built_bundle):
    primer = built_bundle / "PRIMER.md"
    primer.write_text(primer.read_text() + "\nOne quiet extra line.\n")
    proc = run_cli("check", built_bundle)
    assert proc.returncode == 1, combined(proc)


def test_check_fails_after_sliced_file_tamper(built_bundle):
    target = built_bundle / "files" / ENTRY_REL
    target.write_text(target.read_text() + "\n# quiet extra comment\n")
    proc = run_cli("check", built_bundle)
    assert proc.returncode == 1, combined(proc)


def test_check_missing_bundle_is_could_not_check(tmp_path):
    proc = run_cli("check", tmp_path / "no-such-bundle")
    assert proc.returncode == 2, combined(proc)


@pytest.mark.skipif(not ghostslice_available(),
                    reason="GhostSlice checkout not found")
def test_bundle_passes_ghostslice_check(built_bundle):
    proc = run_ghostslice_check(built_bundle)
    try:
        result = json.loads(proc.stdout)
    except ValueError:
        raise AssertionError(
            f"ghostslice check gave no JSON: {combined(proc)}")
    assert result.get("ok") is True, result
