"""Marker-context polish (Oct 14, 2026): markers in documentation or
fixture files are listed and subtotalled, but they no longer count
as open loops or generate next steps. Only code-context markers do.
Also pins the marker scan's file-list cap honesty fields, which the
plan promises ("the pack says when a cap was hit") and the first
v0.1 build dropped silently.

The CLI tests here are black-box like the rest of the suite; the two
cap/classifier tests import the scan module directly because the
file-list cap (20,000 files) cannot be reached through the CLI in
reasonable test time.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pytest  # noqa: E402

import helpers  # noqa: E402

pytestmark = pytest.mark.skipif(
    not helpers.cli_available(),
    reason="ghosthandoff CLI not discoverable (see REPORT_B.md)")


def build_pack(project: Path, tmp_path: Path, name: str = "pack-out"):
    outdir = tmp_path / name
    proc = helpers.run_cli(
        ["pack", str(project), "-o", str(outdir)], cwd=tmp_path)
    assert proc.returncode == 0, (
        f"pack exited {proc.returncode}\n{proc.stdout}\n{proc.stderr}")
    return outdir


def write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture()
def docs_only_project(tmp_path):
    """No code markers at all: every marker lives in documentation
    or fixture files, including a docs page quoting marker syntax."""
    proj = tmp_path / "docs-only"
    write(proj, "main.py",
          '"""Finished module."""\n\n\ndef done():\n    return True\n')
    write(proj, "docs/guide.md",
          "# Guide\n\nWrite TODO items on their own line.\n"
          "TODO: an example marker quoted in the docs\n"
          "FIXME: another example marker quoted in the docs\n")
    write(proj, "README.md",
          "# Demo\n\nTODO: documentation prose, not code work\n")
    write(proj, "fixtures/sample.py",
          "# TODO: sample data marker for scanner exercises\nVALUE = 1\n")
    return proj


@pytest.fixture()
def mixed_project(tmp_path):
    """One real code TODO, plus a TODO and a FIXME in docs."""
    proj = tmp_path / "mixed"
    write(proj, "app.py",
          '"""App."""\n\n# TODO: real unfinished work in code\n')
    write(proj, "docs/guide.md",
          "# Guide\nTODO: example marker quoted in docs\n"
          "FIXME: another docs example\n")
    return proj


def marker_loops(data) -> list:
    return [lp for lp in data.get("open_loops", [])
            if isinstance(lp, dict) and "marker" in str(lp.get("kind", ""))]


def test_docs_only_markers_make_no_loop_and_no_steps(
        docs_only_project, tmp_path):
    outdir = build_pack(docs_only_project, tmp_path)
    data = helpers.load_pack_json(outdir)
    assert marker_loops(data) == [], (
        f"documentation markers produced an open loop: {data['open_loops']}")
    step_text = " ".join(s.get("text", "") for s in data.get("next_steps", []))
    assert "TODO" not in step_text and "FIXME" not in step_text, (
        f"documentation markers produced next steps: {data['next_steps']}")
    markers = data["markers"]
    assert markers["total"] == 5
    assert markers["code_total"] == 0
    assert markers["docs_total"] == 5


def test_docs_only_markers_are_still_listed_with_the_split_stated(
        docs_only_project, tmp_path):
    outdir = build_pack(docs_only_project, tmp_path)
    text = helpers.pack_text(outdir)
    # Nothing is hidden: every docs marker is listed with file + line,
    # and the pack states the split and the counting rule on its face.
    assert "docs/guide.md" in text and "README.md" in text
    assert "fixtures/sample.py" in text
    assert "documentation or fixture" in text
    assert "not counted as open loops" in text.lower() or \
        "only the code ones are counted" in text.lower()


def test_mixed_project_loop_counts_code_only_and_step_points_at_code(
        mixed_project, tmp_path):
    outdir = build_pack(mixed_project, tmp_path)
    data = helpers.load_pack_json(outdir)
    loops = marker_loops(data)
    assert len(loops) == 1, f"expected one marker loop, got {loops}"
    detail = loops[0]["detail"]
    assert "1 open marker(s) in code" in detail
    assert "2 more marker(s)" in detail
    markers = data["markers"]
    assert (markers["total"], markers["code_total"],
            markers["docs_total"]) == (3, 1, 2)
    steps = data.get("next_steps", [])
    todo_steps = [s for s in steps if "TODO" in s.get("text", "")]
    assert len(todo_steps) == 1
    assert "(1 open)" in todo_steps[0]["text"]
    assert "app.py:3" in todo_steps[0]["text"]
    # The docs FIXME must not generate an "Address FIXME" step.
    assert not any("Address FIXME" in s.get("text", "") for s in steps), (
        f"a documentation FIXME generated a step: {steps}")


def test_fixture_repo_markers_all_count_as_code(fixture_repo, tmp_path):
    """Regression anchor: the PLAN fixture's 3 markers are all in
    code files, so the polish must not change its loop arithmetic
    (the no-invention suite pins exactly 5 loops there)."""
    outdir = build_pack(fixture_repo, tmp_path)
    data = helpers.load_pack_json(outdir)
    markers = data["markers"]
    assert markers["code_total"] == 3 and markers["docs_total"] == 0
    loops = marker_loops(data)
    assert len(loops) == 1
    assert "3 open marker(s) in code" in loops[0]["detail"]


# ------------------------------------------------------- unit-level

def _scan_module():
    src = Path(__file__).resolve().parents[1] / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    import ghosthandoff.scan as scan
    return scan


def test_marker_context_classifier_is_conservative():
    scan = _scan_module()
    ctx = scan.marker_context
    assert ctx("docs/guide.txt") == "docs"        # docs/ segment, any ext
    assert ctx("guide.md") == "docs"              # doc extension at root
    assert ctx("CHANGELOG.md") == "docs"
    assert ctx("tests/testdata/x.py") == "docs"   # fixture segment
    assert ctx("src/docs.py") == "code"           # code file named "docs"
    assert ctx("notes.txt") == "code"             # plain .txt not down-weighted
    assert ctx("app.py") == "code"
    assert ctx("Documentation/notes.py") == "docs"  # segment match, any case


def test_scan_records_file_list_cap_instead_of_dropping_silently(tmp_path):
    scan = _scan_module()
    proj = tmp_path / "many"
    proj.mkdir()
    names = []
    for i in range(5):
        name = f"f{i}.py"
        (proj / name).write_text(f"# TODO: item {i}\n", encoding="utf-8")
        names.append(name)
    res = scan.scan_markers(str(proj), names, max_files=3)
    assert res["files_considered"] == 5
    assert res["files_limit"] == 3
    assert res["files_truncated"] is True
    assert res["total"] == 3  # only the capped prefix was scanned
    res_full = scan.scan_markers(str(proj), names)
    assert res_full["files_truncated"] is False
    assert res_full["total"] == 5
