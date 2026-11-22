import json
import os

import pytest

import helpers
from ghostconsole_app import store


def test_add_list_remove_round_trip(app_home, project):
    canonical = store.add_project(str(project))
    assert canonical == os.path.realpath(str(project))
    assert store.list_projects() == [canonical]
    assert store.is_registered(str(project))
    # The registry file really is under the (env-overridden) app home.
    data = json.loads((app_home / "projects.json").read_text())
    assert data == {"projects": [canonical]}

    removed = store.remove_project(str(project))
    assert removed == canonical
    assert store.list_projects() == []
    assert not store.is_registered(str(project))


def test_add_rejects_missing_file_and_duplicate(app_home, project, tmp_path):
    with pytest.raises(store.StoreError):
        store.add_project(str(tmp_path / "no-such-place"))
    a_file = tmp_path / "afile.txt"
    a_file.write_text("hi")
    with pytest.raises(store.StoreError):
        store.add_project(str(a_file))
    with pytest.raises(store.StoreError):
        store.add_project("   ")
    store.add_project(str(project))
    with pytest.raises(store.StoreError):
        store.add_project(str(project))
    with pytest.raises(store.StoreError):
        store.remove_project(str(tmp_path / "other"))


def test_corrupt_registry_reads_empty_and_recovers(app_home, project):
    app_home.mkdir(parents=True)
    (app_home / "projects.json").write_text("{ not json at all")
    assert store.list_projects() == []
    canonical = store.add_project(str(project))
    assert store.list_projects() == [canonical]


def test_wrong_shape_registry_reads_empty(app_home):
    app_home.mkdir(parents=True)
    (app_home / "projects.json").write_text('{"projects": "not-a-list"}')
    assert store.list_projects() == []


def test_list_runs_newest_first_and_skips_non_runs(project):
    older = helpers.make_report(
        str(project), run_id="wf-old", timestamp="2026-10-17T09:00:00+00:00",
        verdict="ok", verification_level="static-analysis")
    newer = helpers.make_report(
        str(project), run_id="wf-new", timestamp="2026-10-18T09:00:00+00:00",
        verdict="attention", verification_level="tests-executed",
        task="newer task")
    helpers.write_run(project, "wf-old", older)
    helpers.write_run(project, "wf-new", newer)
    # A directory with no report is not a run; a hidden dir is ignored.
    stray = project / ".ghostworkflow" / "stray"
    stray.mkdir(parents=True)
    (stray / "board.html").write_text("<html></html>")
    hidden = project / ".ghostworkflow" / ".hidden"
    hidden.mkdir(parents=True)
    (hidden / "workflow-report.json").write_text("{}")

    runs = store.list_runs(str(project))
    assert [r["run_id"] for r in runs] == ["wf-new", "wf-old"]
    assert runs[0]["verdict"] == "attention"
    assert runs[0]["verification_level"] == "tests-executed"
    assert runs[0]["task"] == "newer task"
    assert runs[0]["dir"] == "wf-new"
    assert store.latest_run(str(project))["run_id"] == "wf-new"


def test_no_runs_means_no_latest(project):
    assert store.list_runs(str(project)) == []
    assert store.latest_run(str(project)) is None


def test_load_report_and_board(project):
    report = helpers.make_report(str(project))
    helpers.write_run(project, "wf-1", report, board="<html>BOARD</html>")
    loaded = store.load_report(str(project), "wf-1")
    assert loaded["run_id"] == report["run_id"]
    board = store.board_path(str(project), "wf-1")
    assert board is not None and board.read_text() == "<html>BOARD</html>"
    assert store.load_report(str(project), "wf-missing") is None
    assert store.board_path(str(project), "wf-missing") is None


@pytest.mark.parametrize("bad_id", ["..", ".", "../evil", "..\\evil",
                                    "a/b", "a\\b", ".hidden", ""])
def test_crafted_run_ids_are_refused(project, bad_id):
    helpers.write_run(project, "wf-1", helpers.make_report(str(project)))
    with pytest.raises(store.StoreError):
        store.run_dir(str(project), bad_id)
    with pytest.raises(store.StoreError):
        store.load_report(str(project), bad_id)
    with pytest.raises(store.StoreError):
        store.board_path(str(project), bad_id)


def test_symlinked_run_dir_cannot_escape(project, tmp_path):
    helpers.write_run(project, "wf-1", helpers.make_report(str(project)))
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "board.html").write_text("SECRET-BOARD")
    link = project / ".ghostworkflow" / "wf-link"
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(store.StoreError):
        store.board_path(str(project), "wf-link")
