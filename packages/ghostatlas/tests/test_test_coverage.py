"""Static test linkage ("covering shape") tests.

PLAN.md promises the brief carries "test layout and covering
shape"; the original _test_lines only counted test files. These
tests pin the deepened behaviour: per-source direct / indirect /
unlinked classification from the same run's import graph and test
naming conventions, labelled everywhere as static linkage, never
as measured coverage (tests are not executed).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from conftest import requires_core, run_atlas, section_after

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ghostatlas.data import build_atlas_data  # noqa: E402
from ghostatlas.data import test_linkage as compute_linkage  # noqa: E402


def _f(path, language="python", is_test=False, **kw):
    d = {"path": path, "language": language, "is_test": is_test,
         "tokens": 10, "importer_count": 0}
    d.update(kw)
    return d


def _by_path(cov):
    return {s["path"]: s for s in cov["sources"]}


# ---------------------------------------------------------------------------
# Pure linkage logic
# ---------------------------------------------------------------------------

def test_direct_link_from_test_import_edge():
    files = [_f("engine.py"), _f("test_engine.py", is_test=True)]
    graph = {"test_engine.py": {"imports": ["engine.py"], "external": []},
             "engine.py": {"imports": [], "external": []}}
    cov = compute_linkage(files, graph)
    assert cov["summary"] == {"source_files": 1, "direct": 1, "indirect": 0,
                              "unlinked": 0, "test_files": 1}
    src = _by_path(cov)["engine.py"]
    assert src["status"] == "direct"
    assert src["test_files"] == ["test_engine.py"]


def test_direct_link_from_naming_convention_without_import_edge():
    files = [_f("widget.ts", language="typescript"),
             _f("widget.test.ts", language="typescript", is_test=True),
             _f("util.py"), _f("util_test.py", is_test=True)]
    cov = compute_linkage(files, {})
    by = _by_path(cov)
    assert by["widget.ts"]["status"] == "direct"
    assert by["widget.ts"]["test_files"] == ["widget.test.ts"]
    assert by["util.py"]["status"] == "direct"
    assert by["util.py"]["test_files"] == ["util_test.py"]


def test_ambiguous_stem_name_links_nothing_by_name():
    files = [_f("a/util.py"), _f("b/util.py"),
             _f("tests/test_util.py", is_test=True)]
    cov = compute_linkage(files, {})
    by = _by_path(cov)
    assert by["a/util.py"]["status"] == "unlinked"
    assert by["b/util.py"]["status"] == "unlinked"


def test_mirror_directory_disambiguates_same_stem():
    files = [_f("pkg/util.py"), _f("other/util.py"),
             _f("tests/pkg/test_util.py", is_test=True)]
    cov = compute_linkage(files, {})
    by = _by_path(cov)
    assert by["pkg/util.py"]["status"] == "direct"
    assert by["other/util.py"]["status"] == "unlinked"


def test_indirect_link_is_transitive_with_shortest_distance():
    files = [_f("a.py"), _f("b.py"), _f("c.py"), _f("test_a.py", is_test=True)]
    graph = {"test_a.py": {"imports": ["a.py"], "external": []},
             "a.py": {"imports": ["b.py"], "external": []},
             "b.py": {"imports": ["c.py"], "external": []},
             "c.py": {"imports": [], "external": []}}
    by = _by_path(compute_linkage(files, graph))
    assert by["b.py"]["status"] == "indirect"
    assert by["b.py"]["distance"] == 1
    assert by["b.py"]["direct_source"] == "a.py"
    assert by["c.py"]["status"] == "indirect"
    assert by["c.py"]["distance"] == 2
    assert by["c.py"]["via"] == "b.py"
    assert by["c.py"]["direct_source"] == "a.py"


def test_import_cycle_terminates_and_classifies():
    files = [_f("a.py"), _f("b.py"), _f("test_a.py", is_test=True)]
    graph = {"test_a.py": {"imports": ["a.py"], "external": []},
             "a.py": {"imports": ["b.py"], "external": []},
             "b.py": {"imports": ["a.py"], "external": []}}
    cov = compute_linkage(files, graph)
    assert cov["summary"]["direct"] == 1
    assert cov["summary"]["indirect"] == 1
    assert cov["summary"]["unlinked"] == 0


def test_non_sources_are_excluded():
    files = [
        _f("app.py"),
        _f("test_app.py", is_test=True),
        _f("vendor/lib.py", is_vendored=True),
        _f("gen.py", is_generated=True),
        _f("README.md", language="markdown"),
        _f("settings.json", language="json"),
    ]
    cov = compute_linkage(files, {})
    assert [s["path"] for s in cov["sources"]] == ["app.py"]
    assert cov["summary"]["test_files"] == 1


def test_unlinked_sorted_by_importer_count_then_tokens():
    files = [_f("small.py", tokens=5, importer_count=0),
             _f("hub.py", tokens=5, importer_count=3),
             _f("mid.py", tokens=50, importer_count=1)]
    cov = compute_linkage(files, {})
    assert [s["path"] for s in cov["sources"]] == ["hub.py", "mid.py", "small.py"]
    assert all(s["status"] == "unlinked" for s in cov["sources"])


def test_method_label_says_not_measured_coverage():
    cov = compute_linkage([], {})
    assert "not" in cov["method"] and "measured coverage" in cov["method"]
    assert cov["summary"]["source_files"] == 0


# ---------------------------------------------------------------------------
# Integration over the ground-truth fixture
# ---------------------------------------------------------------------------

def test_fixture_linkage_matches_known_shape(ground_truth: Path):
    data = build_atlas_data(ground_truth)
    cov = data.test_coverage
    assert cov["summary"] == {"source_files": 4, "direct": 1, "indirect": 1,
                              "unlinked": 2, "test_files": 1}
    by = _by_path(cov)
    assert by["engine.py"]["status"] == "direct"
    assert by["engine.py"]["test_files"] == ["test_engine.py"]
    assert by["util.py"]["status"] == "indirect"
    assert by["util.py"]["via"] == "engine.py"
    assert by["util.py"]["direct_source"] == "engine.py"
    assert by["main.py"]["status"] == "unlinked"
    assert by["dead.py"]["status"] == "unlinked"
    # The structured run data carries the same shape.
    assert data.to_dict()["test_coverage"]["summary"] == cov["summary"]


def test_hidden_paths_stay_out_of_linkage(ground_truth: Path):
    (ground_truth / ".ghostslice.json").write_text(
        json.dumps({"atlas": {"hidden_paths": ["util.py"]}}), encoding="utf-8")
    data = build_atlas_data(ground_truth)
    paths = [s["path"] for s in data.test_coverage["sources"]]
    assert "util.py" not in paths
    assert data.test_coverage["summary"]["source_files"] == 3


@requires_core
def test_brief_carries_covering_shape(build, ground_truth: Path):
    built = build(ground_truth)
    assert built.result.returncode == 0, built.result.stderr
    section = section_after(built.atlas_md, "test layout", span=6000)
    assert "Covering shape" in section
    assert "not measured coverage" in section
    assert "`engine.py`: directly linked from test file(s) `test_engine.py`" in section
    assert "`util.py`: indirectly linked via `engine.py`" in section
    assert "`main.py`" in section and "no test link found" in section


@requires_core
def test_html_and_json_carry_linkage(build, ground_truth: Path):
    built = build(ground_truth)
    assert built.result.returncode == 0, built.result.stderr
    assert "Test layout" in built.html
    assert "not measured coverage" in built.html
    assert built.data is not None
    summary = built.data["test_coverage"]["summary"]
    assert summary["direct"] == 1 and summary["indirect"] == 1
    assert summary["unlinked"] == 2


@requires_core
def test_diligence_brief_summarises_linkage(build, ground_truth: Path):
    built = build(ground_truth, extra_args=["--audience", "diligence"])
    assert built.result.returncode == 0, built.result.stderr
    assert ("Test linkage (static, not measured coverage): 2 of 4 "
            "source file(s)") in built.atlas_md


@requires_core
def test_scan_json_carries_linkage(tmp_path: Path, ground_truth: Path):
    result = run_atlas(["scan", str(ground_truth)], cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["test_coverage"]["summary"]["source_files"] == 4
