"""Recall consumption: with --recall-bundle, memory comes from the Recall
bundle's current items only; the superseded decision never appears, and
the manifest records the recall-bundle path."""
from __future__ import annotations

import json

import pytest

from conftest import (build, combined, ghostrecall_available,
                      load_manifest, run_ghostrecall_bundle)

pytestmark = pytest.mark.skipif(
    not ghostrecall_available(),
    reason="GhostRecall checkout not found; cannot generate a Recall bundle")


@pytest.fixture()
def recall_bundle(recall_project, tmp_path):
    out = tmp_path / "recall-bundle"
    proc = run_ghostrecall_bundle(
        recall_project, "releases ship once the test suite passes", out)
    assert proc.returncode == 0, combined(proc)
    return out


def test_primer_consumes_recall_bundle(recall_project, recall_bundle, tmp_path):
    out = tmp_path / "bundle"
    proc = build(recall_project, out, "--recall-bundle", recall_bundle)
    assert proc.returncode == 0, combined(proc)
    primer = (out / "PRIMER.md").read_text()
    assert "Release hold lifted. Ship releases once the test suite passes." \
        in primer
    assert "Hold all releases until the security review is complete." \
        not in primer
    blob = json.dumps(load_manifest(out)).lower()
    assert "recall" in blob, "manifest must record the recall-bundle path"
