"""HTTP server for the GhostConsole app.

http.server based, standard library only. The handler is a thin
routing layer: registry and run evidence come from store.py, page
bodies from render.py, and workflow execution from runner.py. Board
files are served only through store.board_path, which proves the
requested run lives inside the registered project's .ghostworkflow/
directory before a single byte is read.
"""

from __future__ import annotations

import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from . import render, store
from .runner import RunInProgress, Runner, WorkflowNotFound


def _first(params: dict, name: str) -> str:
    values = params.get(name)
    return values[0] if values else ""


def _registered_project(raw: str) -> str | None:
    """The canonical registered path matching a user-supplied path,
    or None. Unregistered paths are 404 everywhere: the app only
    ever talks about projects the user added."""
    if not raw:
        return None
    canonical = os.path.realpath(os.path.expanduser(raw))
    for project in store.list_projects():
        if os.path.realpath(project) == canonical:
            return project
    return None


def _project_infos() -> list[dict]:
    infos = []
    for project in store.list_projects():
        infos.append({
            "path": project,
            "name": os.path.basename(project.rstrip("/")) or project,
            "latest": store.latest_run(project),
        })
    return infos


class _Handler(BaseHTTPRequestHandler):
    server_version = "GhostConsoleApp/0.1"

    # -- plumbing ----------------------------------------------------
    @property
    def _bind(self) -> str:
        return self.server.bind_display  # type: ignore[attr-defined]

    @property
    def _runner(self) -> Runner:
        return self.server.runner  # type: ignore[attr-defined]

    def log_message(self, format, *args):  # noqa: A002 - stdlib name
        if not getattr(self.server, "quiet", False):
            super().log_message(format, *args)

    def _send_html(self, status: int, body: str) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, location: str) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _not_found(self, what: str = "not found") -> None:
        self._send_html(404, render.message_page(
            "Not found", what, self._bind, link=("/", "Back to projects")))

    def _form(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        return parse_qs(raw.decode("utf-8", "replace"))

    # -- GET routes --------------------------------------------------
    def do_GET(self):  # noqa: N802 - stdlib name
        parts = urlsplit(self.path)
        params = parse_qs(parts.query)
        route = parts.path
        if route == "/":
            self._send_html(200, render.dashboard(
                _project_infos(), self._bind,
                notice=_first(params, "notice") or None,
                error=_first(params, "error") or None))
        elif route == "/project":
            self._project_page(_first(params, "path"))
        elif route == "/run-status":
            self._run_status(_first(params, "path"))
        elif route == "/run":
            self._run_detail(_first(params, "path"), _first(params, "run_id"))
        elif route == "/board":
            self._board(_first(params, "path"), _first(params, "run_id"))
        else:
            self._not_found()

    def _project_page(self, raw_path: str, error: str | None = None,
                      notice: str | None = None) -> None:
        project = _registered_project(raw_path)
        if project is None:
            self._not_found("unknown project")
            return
        record = self._runner.status(project)
        active = record if record is not None and record.status == "running" else None
        name = os.path.basename(project.rstrip("/")) or project
        self._send_html(200, render.project_page(
            project, name, store.list_runs(project), active, self._bind,
            notice=notice, error=error))

    def _run_status(self, raw_path: str) -> None:
        project = _registered_project(raw_path)
        if project is None:
            self._not_found("unknown project")
            return
        record = self._runner.status(project)
        self._send_html(200, render.run_status_page(project, record, self._bind))

    def _run_detail(self, raw_path: str, run_id: str) -> None:
        project = _registered_project(raw_path)
        if project is None:
            self._not_found("unknown project")
            return
        try:
            report = store.load_report(project, run_id)
        except store.StoreError:
            self._not_found("unknown run")
            return
        if report is None:
            self._not_found("unknown run")
            return
        name = os.path.basename(project.rstrip("/")) or project
        self._send_html(200, render.run_detail(
            project, name, report, run_id, self._bind))

    def _board(self, raw_path: str, run_id: str) -> None:
        project = _registered_project(raw_path)
        if project is None:
            self._not_found("unknown project")
            return
        try:
            board = store.board_path(project, run_id)
        except store.StoreError:
            self._send_html(400, render.message_page(
                "Bad run id", "That run id is not a valid run name.",
                self._bind, link=("/", "Back to projects")))
            return
        if board is None:
            self._not_found("no board for that run")
            return
        data = board.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # -- POST routes -------------------------------------------------
    def do_POST(self):  # noqa: N802 - stdlib name
        route = urlsplit(self.path).path
        form = self._form()
        if route == "/projects":
            self._add_project(form)
        elif route == "/projects/remove":
            self._remove_project(form)
        elif route == "/run":
            self._start_run(form)
        else:
            self._not_found()

    def _add_project(self, form: dict) -> None:
        try:
            canonical = store.add_project(_first(form, "path"))
        except store.StoreError as exc:
            self._send_html(400, render.dashboard(
                _project_infos(), self._bind, error=str(exc)))
            return
        self._redirect("/project?path=" + render.quote(canonical, safe=""))

    def _remove_project(self, form: dict) -> None:
        try:
            store.remove_project(_first(form, "path"))
        except store.StoreError as exc:
            self._send_html(400, render.dashboard(
                _project_infos(), self._bind, error=str(exc)))
            return
        self._redirect("/")

    def _start_run(self, form: dict) -> None:
        project = _registered_project(_first(form, "path"))
        if project is None:
            self._not_found("unknown project")
            return
        task = _first(form, "task").strip() or None
        test_command = _first(form, "test_command").strip() or None
        try:
            self._runner.start(project, task, test_command)
        except RunInProgress as exc:
            self._send_html(409, render.message_page(
                "Run already in progress", str(exc), self._bind,
                link=("/run-status?path=" + render.quote(project, safe=""),
                      "Watch the current run")))
            return
        except WorkflowNotFound as exc:
            self._send_html(500, render.message_page(
                "ghostworkflow not found", str(exc), self._bind,
                link=("/", "Back to projects")))
            return
        self._redirect("/run-status?path=" + render.quote(project, safe=""))


def make_server(host: str, port: int, runner: Runner,
                quiet: bool = False) -> ThreadingHTTPServer:
    """Build (and bind) the server. Raises OSError when the address
    cannot be bound, e.g. the port is taken; the caller reports it.
    The port is never silently changed."""
    server = ThreadingHTTPServer((host, port), _Handler)
    server.daemon_threads = True
    server.runner = runner  # type: ignore[attr-defined]
    server.quiet = quiet  # type: ignore[attr-defined]
    bound_host, bound_port = server.server_address[:2]
    server.bind_display = f"{bound_host}:{bound_port}"  # type: ignore[attr-defined]
    return server
