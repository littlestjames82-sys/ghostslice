"""Doctor exit codes, the no-manifest case, and read-only behaviour."""
from __future__ import annotations

import hashlib
from pathlib import Path

from conftest import combined, needs_cli, run_ghostdeps, run_pack
from helpers import banned_hits


def _tree_hashes(root: Path) -> dict[str, str]:
    out = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            out[str(path.relative_to(root))] = hashlib.sha256(
                path.read_bytes()).hexdigest()
    return out


@needs_cli
def test_doctor_flags_imported_not_declared(python_gap_project):
    """Plan: exit 1 = findings present; imported-not-declared is a finding."""
    proc = run_ghostdeps(["doctor", str(python_gap_project)])
    assert proc.returncode == 1, combined(proc)
    assert "traceback" not in combined(proc).lower()
    assert "pyproject" in combined(proc).lower()


@needs_cli
def test_doctor_clean_project_exits_zero(clean_project):
    proc = run_ghostdeps(["doctor", str(clean_project)])
    assert proc.returncode == 0, combined(proc)


@needs_cli
def test_no_manifest_project_is_reported_not_crashed(no_manifest_project,
                                                     tmp_path):
    """Task rule: no manifests -> reported as such, no traceback, no pack
    pretending to know anything."""
    proc, found = run_pack(no_manifest_project, tmp_path / "out")
    out = combined(proc).lower()
    assert "traceback" not in out
    assert proc.returncode in (0, 2), (
        f"pack on a manifest-less project exited {proc.returncode}; "
        "expected a reported outcome, not a failure")
    assert "no manifest" in out or (found and "no manifest" in
                                    found[0].read_text().lower()), (
        "the absence of manifests was not reported anywhere")
    if found is not None:
        hits = banned_hits(found[0].read_text(), found[1].read_text())
        assert hits == []

    doc = run_ghostdeps(["doctor", str(no_manifest_project)])
    doc_out = combined(doc).lower()
    assert "traceback" not in doc_out
    assert "no manifest" in doc_out, (
        "doctor did not report that no manifests were found")
    # Plan: exit 2 = could not parse, which includes no manifests found.
    assert doc.returncode == 2, combined(doc)


@needs_cli
def test_pack_is_read_only(python_gap_project, tmp_path):
    before = _tree_hashes(python_gap_project)
    proc, found = run_pack(python_gap_project, tmp_path / "out")
    assert proc.returncode in (0, 1), combined(proc)
    after = _tree_hashes(python_gap_project)
    assert before == after, (
        "pack modified the project tree; GhostDeps is read-only "
        f"(changed: {sorted(set(before.items()) ^ set(after.items()))})")


@needs_cli
def test_doctor_reports_parser_labels(python_gap_project, node_gap_project):
    """Doctor names what was found and the confidence per language; the
    JS/TS side must carry its parser-lite label (plan rule)."""
    proc = run_ghostdeps(["doctor", str(node_gap_project)])
    out = combined(proc).lower()
    assert "package.json" in out
    assert "parser-lite" in out or "parser lite" in out, (
        "JS/TS extraction was not labelled parser-lite in doctor output")
    proc2 = run_ghostdeps(["doctor", str(python_gap_project)])
    assert "pyproject" in combined(proc2).lower()
