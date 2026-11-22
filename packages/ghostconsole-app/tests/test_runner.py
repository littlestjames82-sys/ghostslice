import http.client
import os
import threading
import urllib.parse

import pytest

import helpers
from ghostconsole_app import store
from ghostconsole_app.runner import (Runner, RunInProgress,
                                     WorkflowNotFound, find_workflow)
from ghostconsole_app.server import make_server


def _wait_done(runner, project, timeout=15):
    return helpers.wait_for(
        lambda: (runner.status(str(project)) is not None
                 and runner.status(str(project)).status != "running"),
        timeout=timeout)


def test_find_workflow_via_path(app_home, project, tmp_path, monkeypatch):
    bin_dir = helpers.make_fake_path_script(tmp_path / "fake1")
    helpers.prepend_path(monkeypatch, bin_dir)
    argv, _env, how = find_workflow()
    assert argv == [str(bin_dir / "ghostworkflow")]
    assert "PATH" in how


def test_find_workflow_via_home_checkout(app_home, tmp_path, monkeypatch):
    home = helpers.make_fake_checkout(tmp_path / "fakehome")
    argv, env, _how = find_workflow(str(home))
    assert argv[-2:] == ["-m", "ghostworkflow"]
    assert env["PYTHONPATH"].endswith(
        os.path.join("ghostworkflow", "src"))


def test_find_workflow_missing_home_raises(app_home, tmp_path):
    with pytest.raises(WorkflowNotFound):
        find_workflow(str(tmp_path / "empty-home"))


def test_run_completes_and_attaches_report(app_home, project, tmp_path,
                                           monkeypatch):
    bin_dir = helpers.make_fake_path_script(tmp_path / "fake2")
    helpers.prepend_path(monkeypatch, bin_dir)
    store.add_project(str(project))
    runner = Runner()
    record = runner.start(str(project), "do the thing", "python3 -m pytest -q")
    assert record.status == "running"
    assert _wait_done(runner, project)
    assert record.status == "done"
    assert record.exit_code == 0
    assert record.run_dir == "wf-fake-0001"
    assert record.run_id == "wf-fake-0001"
    # The run is now durable evidence on disk, readable via the store.
    runs = store.list_runs(str(project))
    assert len(runs) == 1
    assert runs[0]["verdict"] == "attention"
    assert runs[0]["verification_level"] == "tests-executed"
    assert runs[0]["task"] == "do the thing"


def test_failing_workflow_exit_code_recorded(app_home, project, tmp_path,
                                             monkeypatch):
    bin_dir = helpers.make_fake_path_script(tmp_path / "fake3")
    helpers.prepend_path(monkeypatch, bin_dir)
    monkeypatch.setenv("FAKE_GW_EXIT", "1")
    store.add_project(str(project))
    runner = Runner()
    record = runner.start(str(project), "task", None)
    assert _wait_done(runner, project)
    assert record.status == "done"
    assert record.exit_code == 1
    # ghostworkflow still wrote its report; the run attaches.
    assert record.run_dir == "wf-fake-0001"


def test_concurrent_run_refused(app_home, project, tmp_path, monkeypatch):
    bin_dir = helpers.make_fake_path_script(tmp_path / "fake4")
    helpers.prepend_path(monkeypatch, bin_dir)
    monkeypatch.setenv("FAKE_GW_SLEEP", "2")
    store.add_project(str(project))
    runner = Runner()
    runner.start(str(project), "first", None)
    with pytest.raises(RunInProgress):
        runner.start(str(project), "second", None)
    assert _wait_done(runner, project)
    # And once finished, a new run may start.
    runner.start(str(project), "third", None)
    assert _wait_done(runner, project)


def test_start_with_missing_workflow_raises(app_home, project, tmp_path):
    store.add_project(str(project))
    runner = Runner(workflow_home=str(tmp_path / "nowhere"))
    with pytest.raises(WorkflowNotFound):
        runner.start(str(project), "task", None)
    assert not runner.is_running(str(project))


# -- End to end through HTTP -----------------------------------------


def _get(server, path):
    conn = http.client.HTTPConnection(
        "127.0.0.1", server.server_address[1], timeout=10)
    conn.request("GET", path)
    resp = conn.getresponse()
    body = resp.read().decode("utf-8")
    conn.close()
    return resp.status, body


def _post(server, path, fields):
    conn = http.client.HTTPConnection(
        "127.0.0.1", server.server_address[1], timeout=10)
    conn.request("POST", path, body=urllib.parse.urlencode(fields),
                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    resp = conn.getresponse()
    body = resp.read().decode("utf-8")
    location = resp.getheader("Location")
    conn.close()
    return resp.status, body, location


@pytest.fixture
def http_app(app_home, project, tmp_path, monkeypatch):
    bin_dir = helpers.make_fake_path_script(tmp_path / "fakehttp")
    helpers.prepend_path(monkeypatch, bin_dir)
    store.add_project(str(project))
    server = make_server("127.0.0.1", 0, Runner(), quiet=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


def test_http_run_round_trip(http_app, project):
    q = urllib.parse.quote(str(project), safe="")
    status, _body, location = _post(
        http_app, "/run",
        {"path": str(project), "task": "ship it",
         "test_command": "python3 -m pytest -q"})
    assert status == 303
    assert location == f"/run-status?path={q}"

    done = helpers.wait_for(
        lambda: "View run" in _get(http_app, f"/run-status?path={q}")[1],
        timeout=15)
    assert done

    status, body = _get(http_app, f"/project?path={q}")
    assert status == 200
    assert "attention" in body  # the fake's verdict, in the history
    assert "wf-fake-0001" in body

    status, body = _get(
        http_app, f"/run?path={q}&run_id=wf-fake-0001")
    assert status == 200
    assert "tests-executed" in body
    assert "sha256:fakecafe" in body

    status, body = _get(
        http_app, f"/board?path={q}&run_id=wf-fake-0001")
    assert status == 200
    assert body == "<html><body>fake board</body></html>"


def test_http_second_run_refused_while_running(http_app, project,
                                               monkeypatch):
    monkeypatch.setenv("FAKE_GW_SLEEP", "2.5")
    q = urllib.parse.quote(str(project), safe="")
    status, _b, _l = _post(http_app, "/run", {"path": str(project),
                                              "task": "one"})
    assert status == 303
    status, body, _l = _post(http_app, "/run", {"path": str(project),
                                                "task": "two"})
    assert status == 409
    assert "already" in body
    # Let the first run finish so the fixture tears down clean.
    helpers.wait_for(
        lambda: "View run" in _get(http_app, f"/run-status?path={q}")[1],
        timeout=15)
