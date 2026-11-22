import http.client
import os
import urllib.parse

import helpers
from ghostconsole_app import store

EVIL_TASK = 'Fix <script>alert("xss")</script> totals'


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


def _q(path):
    return urllib.parse.quote(path, safe="")


def test_dashboard_empty_state(live_server):
    status, body = _get(live_server, "/")
    assert status == 200
    assert "No projects registered" in body
    assert "no authentication" in body  # the footer says it plainly
    assert "127.0.0.1" in body  # the bind address is stated


def test_dashboard_shows_latest_run_and_escapes(live_server, project):
    store.add_project(str(project))
    report = helpers.make_report(
        str(project), verdict="attention",
        verification_level="tests-executed", task=EVIL_TASK)
    helpers.write_run(project, "wf-1", report)

    status, body = _get(live_server, "/")
    assert status == 200
    assert "attention" in body
    assert "tests-executed" in body
    assert "&lt;script&gt;" in body
    assert '<script>alert' not in body


def test_project_page_history_and_form(live_server, project):
    store.add_project(str(project))
    report = helpers.make_report(str(project), task=EVIL_TASK)
    helpers.write_run(project, "wf-1", report)

    status, body = _get(live_server, f"/project?path={_q(str(project))}")
    assert status == 200
    assert "Run history" in body
    assert "wf-20261018T120000Z-abc123" in body
    assert 'action="/run"' in body
    assert "&lt;script&gt;" in body
    assert '<script>alert' not in body


def test_project_without_runs_says_so(live_server, project):
    store.add_project(str(project))
    status, body = _get(live_server, f"/project?path={_q(str(project))}")
    assert status == 200
    assert "No runs yet" in body


def test_unknown_project_is_404(live_server, project, tmp_path):
    # An existing but unregistered directory is still unknown here.
    status, _ = _get(live_server, f"/project?path={_q(str(project))}")
    assert status == 404
    status, _ = _get(live_server, f"/project?path={_q(str(tmp_path / 'nope'))}")
    assert status == 404
    status, _ = _get(live_server, f"/run?path={_q(str(project))}&run_id=wf-1")
    assert status == 404
    status, _ = _get(live_server, f"/board?path={_q(str(project))}&run_id=wf-1")
    assert status == 404
    status, _, _ = _post(live_server, "/run", {"path": str(project)})
    assert status == 404


def test_run_detail_renders_report(live_server, project):
    store.add_project(str(project))
    report = helpers.make_report(str(project), task=EVIL_TASK)
    helpers.write_run(project, "wf-1", report)

    status, body = _get(
        live_server, f"/run?path={_q(str(project))}&run_id=wf-1")
    assert status == 200
    assert "sha256:0123456789abcdef" in body
    assert "ghostbench bench-report" in body  # tree hash source stated
    assert "1.0.6" in body  # engine version (ghostslice)
    assert "slice" in body and "console" in body  # steps table
    assert "Verification levels:" in body  # the plain-words legend
    assert "&lt;script&gt;" in body
    assert '<script>alert' not in body
    status, _ = _get(
        live_server, f"/run?path={_q(str(project))}&run_id=wf-nope")
    assert status == 404


def test_board_served_and_traversal_refused(live_server, project):
    store.add_project(str(project))
    report = helpers.make_report(str(project))
    helpers.write_run(project, "wf-1", report, board="<html>REAL BOARD</html>")
    # A file outside .ghostworkflow that traversal would love to reach.
    (project / "secret.html").write_text("TOP-SECRET-FILE")

    status, body = _get(
        live_server, f"/board?path={_q(str(project))}&run_id=wf-1")
    assert status == 200
    assert body == "<html>REAL BOARD</html>"

    for evil in ("../../secret", "..%2f..%2fsecret", "..", ".hidden"):
        status, body = _get(
            live_server,
            f"/board?path={_q(str(project))}&run_id={evil}")
        assert status in (400, 404), evil
        assert "TOP-SECRET-FILE" not in body


def test_add_project_via_post(live_server, project):
    status, _, location = _post(live_server, "/projects",
                                {"path": str(project)})
    assert status == 303
    assert location and location.startswith("/project?path=")
    assert store.list_projects() == [os.path.realpath(str(project))]
    status, body = _get(live_server, "/")
    assert status == 200
    assert "proj" in body


def test_add_project_bad_path_is_400(live_server, tmp_path):
    status, body, _ = _post(live_server, "/projects",
                            {"path": str(tmp_path / "missing")})
    assert status == 400
    assert "no such directory" in body
    assert store.list_projects() == []
