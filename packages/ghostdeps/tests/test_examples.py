"""The shipped examples are working fixture projects, not decoration."""
from __future__ import annotations

from conftest import EXAMPLES, combined, needs_cli, run_pack
from helpers import banned_hits, section_bodies


@needs_cli
def test_python_example_packs_with_planted_gaps(tmp_path):
    project = EXAMPLES / "python_project"
    assert project.is_dir()
    proc, found = run_pack(project, tmp_path / "out")
    assert proc.returncode == 1, combined(proc)  # numpy is a finding
    assert found is not None
    bodies = section_bodies(found[0].read_text())
    assert "colorama" in bodies["declared_not_imported"].lower()
    assert "numpy" in bodies["imported_not_declared"].lower()
    assert "2.31.0" in bodies["pins"]
    assert banned_hits(found[0].read_text(), found[1].read_text()) == []


@needs_cli
def test_node_example_packs_with_planted_gaps(tmp_path):
    project = EXAMPLES / "node_project"
    assert project.is_dir()
    proc, found = run_pack(project, tmp_path / "out")
    assert proc.returncode == 1, combined(proc)  # axios is a finding
    assert found is not None
    bodies = section_bodies(found[0].read_text())
    assert "lodash" in bodies["declared_not_imported"].lower()
    assert "axios" in bodies["imported_not_declared"].lower()
    assert "4.18.2" in bodies["pins"]
    assert banned_hits(found[0].read_text(), found[1].read_text()) == []
