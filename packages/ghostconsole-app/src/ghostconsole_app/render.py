"""HTML rendering for the GhostConsole app.

Every string that came from a file, a report, or a form is escaped
at render time with html.escape; there is no raw-HTML path for
file-derived content. The look follows the Ghost board: dark navy,
violet accent, green for ok, amber for attention, grey for stale or
absent evidence.
"""

from __future__ import annotations

import html
from urllib.parse import quote

# Plain words for the evidence levels, the same legend GhostConsole
# prints on its board, so the two surfaces never disagree.
LEVEL_LEGEND = (
    "Verification levels: static-analysis = static analysis only "
    "(no code executed, no agent ran); tests-executed = the project's "
    "own tests were actually run; live-agent = a real agent attempted "
    "the real task. A level appears only when the report states one; "
    "no stated level means the report did not say, not that the "
    "check was weaker or stronger."
)

_CSS = """
:root{
  --bg:#0b1026; --panel:#131a38; --panel2:#0e1430; --line:#26305c;
  --ink:#e8eaf6; --dim:#9aa3c7; --violet:#8b5cf6; --violet2:#6716f3;
  --ok:#3fb96f; --attention:#e0a63f; --failed:#e05f5f; --stale:#7c86a8;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:15px/1.5 -apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif}
a{color:#b79cff}
header{background:var(--panel2);border-bottom:2px solid var(--violet2);
  padding:14px 22px;display:flex;justify-content:space-between;
  align-items:baseline;gap:16px;flex-wrap:wrap}
header .brand{font-size:20px;font-weight:700;letter-spacing:.3px}
header .brand span{color:var(--violet)}
header .bind{color:var(--dim);font-size:13px}
main{max-width:1100px;margin:0 auto;padding:22px}
h1{font-size:22px;margin:4px 0 14px}
h2{font-size:17px;margin:22px 0 10px}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));
  gap:14px}
.card{background:var(--panel);border:1px solid var(--line);
  border-top:3px solid var(--stale);border-radius:8px;padding:14px 16px}
.card.ok{border-top-color:var(--ok)} .card.attention{border-top-color:var(--attention)}
.card.failed{border-top-color:var(--failed)} .card.noruns{border-top-color:var(--stale)}
.card .name{font-size:17px;font-weight:700}
.card .path,.meta{color:var(--dim);font-size:13px;word-break:break-all}
.pill{display:inline-block;padding:1px 9px;border-radius:20px;font-size:12px;
  font-weight:700;color:#0b1026;background:var(--stale)}
.pill.ok{background:var(--ok)} .pill.attention{background:var(--attention)}
.pill.failed{background:var(--failed);color:#fff}
.pill.level{background:var(--violet);color:#fff}
table{border-collapse:collapse;width:100%;background:var(--panel);
  border:1px solid var(--line);border-radius:8px;overflow:hidden}
th,td{text-align:left;padding:8px 12px;border-bottom:1px solid var(--line);
  font-size:14px;vertical-align:top}
th{color:var(--dim);font-weight:600;background:var(--panel2)}
td code{word-break:break-all}
form.inline{display:inline}
input[type=text]{background:var(--panel2);border:1px solid var(--line);
  color:var(--ink);border-radius:6px;padding:8px 10px;width:100%}
input[type=text].short{max-width:520px}
button,.btn{background:var(--violet2);color:#fff;border:0;border-radius:6px;
  padding:8px 16px;font-size:14px;cursor:pointer;text-decoration:none;
  display:inline-block}
button.ghost,.btn.ghost{background:transparent;border:1px solid var(--line);
  color:var(--ink)}
.notice{background:#2a2140;border:1px solid var(--violet);border-radius:8px;
  padding:10px 14px;margin:0 0 16px}
.notice.error{background:#3a1d24;border-color:var(--failed)}
.legend{color:var(--dim);font-size:13px;margin:14px 0}
.counts{display:flex;gap:10px;flex-wrap:wrap;margin:0 0 16px}
.counts .card{padding:8px 16px;font-size:14px}
pre{background:var(--panel2);border:1px solid var(--line);border-radius:8px;
  padding:12px;overflow:auto;font-size:12px;white-space:pre-wrap}
footer{border-top:1px solid var(--line);color:var(--dim);font-size:13px;
  padding:14px 22px;max-width:1100px;margin:24px auto 0}
.empty{background:var(--panel);border:1px dashed var(--line);border-radius:8px;
  padding:18px}
"""


def esc(value) -> str:
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def _q(value: str) -> str:
    return quote(value, safe="")


def page(title: str, body: str, bind: str, refresh: int | None = None) -> str:
    refresh_tag = (
        f'<meta http-equiv="refresh" content="{refresh}">' if refresh else ""
    )
    return (
        "<!DOCTYPE html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{esc(title)} - GhostConsole</title>{refresh_tag}"
        f"<style>{_CSS}</style></head><body>"
        "<header><div class=\"brand\">Ghost<span>Console</span></div>"
        f"<div class=\"bind\">local front end &middot; bound to {esc(bind)}</div></header>"
        f"<main>{body}</main>"
        "<footer>GhostConsole app &middot; local only &middot; bound to "
        f"{esc(bind)} &middot; <strong>no authentication</strong> - do not "
        "expose this server beyond your own machine. The app reads "
        "workflow reports; it does not edit them.</footer>"
        "</body></html>"
    )


def _pill(value: str | None) -> str:
    if not value:
        return '<span class="pill">not stated</span>'
    return f'<span class="pill {esc(value)}">{esc(value)}</span>'


def _level_pill(level: str | None) -> str:
    if not level:
        return '<span class="pill">level not stated</span>'
    return f'<span class="pill level">{esc(level)}</span>'


def _project_url(path: str) -> str:
    return f"/project?path={_q(path)}"


def _run_url(path: str, run_dir: str) -> str:
    return f"/run?path={_q(path)}&run_id={_q(run_dir)}"


def _board_url(path: str, run_dir: str) -> str:
    return f"/board?path={_q(path)}&run_id={_q(run_dir)}"


def dashboard(projects: list[dict], bind: str, notice: str | None = None,
              error: str | None = None) -> str:
    parts: list[str] = []
    if error:
        parts.append(f'<div class="notice error">{esc(error)}</div>')
    if notice:
        parts.append(f'<div class="notice">{esc(notice)}</div>')
    parts.append("<h1>Projects</h1>")
    counts = {"ok": 0, "attention": 0, "failed": 0, "noruns": 0}
    for info in projects:
        latest = info["latest"]
        counts[latest["verdict"] if latest and latest["verdict"] in counts
               else "noruns"] += 1
    parts.append(
        '<div class="counts">'
        f'<div class="card">ok / verified: <strong>{counts["ok"]}</strong></div>'
        f'<div class="card">attention: <strong>{counts["attention"]}</strong></div>'
        f'<div class="card">failed: <strong>{counts["failed"]}</strong></div>'
        f'<div class="card">no runs yet: <strong>{counts["noruns"]}</strong></div>'
        "</div>"
    )
    if not projects:
        parts.append(
            '<div class="empty"><strong>No projects registered.</strong>'
            "<p>Add a project directory below. When you run the Ghost "
            "workflow on it from its project page, the run's verdict, "
            "verification level, and board appear here. Nothing is "
            "shown for a project that has no runs: no runs means no "
            "evidence, and the board says so.</p></div>"
        )
    else:
        parts.append('<div class="cards">')
        for info in projects:
            latest = info["latest"]
            cls = latest["verdict"] if latest and latest["verdict"] else "noruns"
            if latest:
                detail = (
                    f"<p>{_pill(latest['verdict'])} "
                    f"{_level_pill(latest['verification_level'])}</p>"
                    f"<p class=\"meta\">latest run: {esc(latest['timestamp'])}<br>"
                    f"task: {esc(latest['task']) or '<em>no task stated</em>'}<br>"
                    f"run: {esc(latest['run_id'])}</p>"
                )
            else:
                detail = ('<p><span class="pill">no runs yet</span></p>'
                          '<p class="meta">No workflow runs found in '
                          ".ghostworkflow/. Run one from the project page.</p>")
            parts.append(
                f'<div class="card {esc(cls)}">'
                f'<div class="name"><a href="{_project_url(info["path"])}">'
                f'{esc(info["name"])}</a></div>'
                f'<div class="path">{esc(info["path"])}</div>'
                f"{detail}</div>"
            )
        parts.append("</div>")
    parts.append(
        "<h2>Add a project</h2>"
        '<form method="post" action="/projects">'
        '<input type="text" name="path" class="short" '
        'placeholder="/absolute/path/to/project" required> '
        '<button type="submit">Add project</button></form>'
        f'<p class="legend">{esc(LEVEL_LEGEND)}</p>'
    )
    return page("Projects", "".join(parts), bind)


def project_page(project: str, name: str, runs: list[dict], active,
                 bind: str, notice: str | None = None,
                 error: str | None = None) -> str:
    parts: list[str] = []
    if error:
        parts.append(f'<div class="notice error">{esc(error)}</div>')
    if notice:
        parts.append(f'<div class="notice">{esc(notice)}</div>')
    parts.append(f"<h1>{esc(name)}</h1>")
    parts.append(f'<p class="path">{esc(project)}</p>')
    parts.append('<p><a href="/">&larr; all projects</a></p>')
    if active is not None:
        parts.append(
            '<div class="notice">A workflow run is in progress for this '
            f'project. <a href="/run-status?path={_q(project)}">Watch it</a>'
            "</div>"
        )
    if runs:
        latest_dir = runs[0]["dir"]
        parts.append(
            f'<p><a class="btn" href="{_board_url(project, latest_dir)}">'
            "View latest board</a></p>"
        )
    parts.append("<h2>Run workflow</h2>")
    parts.append(
        '<form method="post" action="/run">'
        f'<input type="hidden" name="path" value="{esc(project)}">'
        '<p><label>Task<br><input type="text" name="task" '
        'placeholder="Fix checkout totals using compute_total"></label></p>'
        '<p><label>Test command (optional - runs the project tests in '
        'GhostBench\'s contained runner)<br>'
        '<input type="text" name="test_command" '
        'placeholder="python3 -m pytest -q"></label></p>'
        '<button type="submit">Run workflow</button></form>'
        '<p class="meta">One run per project at a time. The run is '
        "ghostworkflow itself, in the background; this page and the "
        "dashboard read the report it writes.</p>"
    )
    parts.append("<h2>Run history</h2>")
    if not runs:
        parts.append('<div class="empty">No runs yet for this project.</div>')
    else:
        rows = []
        for run in runs:
            rows.append(
                "<tr>"
                f'<td><a href="{_run_url(project, run["dir"])}">'
                f'{esc(run["run_id"])}</a></td>'
                f"<td>{esc(run['timestamp'])}</td>"
                f"<td>{esc(run['task'])}</td>"
                f"<td>{_pill(run['verdict'])}</td>"
                f"<td>{_level_pill(run['verification_level'])}</td>"
                "</tr>"
            )
        parts.append(
            "<table><tr><th>Run</th><th>Time (UTC)</th><th>Task</th>"
            "<th>Verdict</th><th>Verification level</th></tr>"
            + "".join(rows) + "</table>"
        )
    parts.append(
        "<h2>Remove</h2>"
        '<form method="post" action="/projects/remove">'
        f'<input type="hidden" name="path" value="{esc(project)}">'
        '<button type="submit" class="ghost">Remove from registry</button>'
        "</form>"
        '<p class="meta">Removing a project only unregisters it here. '
        "Its files are never touched.</p>"
        f'<p class="legend">{esc(LEVEL_LEGEND)}</p>'
    )
    return page(name, "".join(parts), bind)


def run_status_page(project: str, record, bind: str) -> str:
    if record is None:
        body = (
            "<h1>Run status</h1><div class=\"empty\">No run is tracked "
            "for this project in this app session. Runs from before "
            "the app started are in the project's run history.</div>"
            f'<p><a href="{_project_url(project)}">&larr; project</a></p>'
        )
        return page("Run status", body, bind)
    parts = [f"<h1>Run for {esc(project)}</h1>"]
    parts.append(f'<p><a href="{_project_url(project)}">&larr; project</a></p>')
    parts.append(
        f"<p>Status: <strong>{esc(record.status)}</strong>"
        f"<br>Task: {esc(record.task) or '<em>no task stated</em>'}"
        f"<br>Started: {esc(record.started_utc)}"
    )
    if record.finished_utc:
        parts.append(f"<br>Finished: {esc(record.finished_utc)}")
    if record.exit_code is not None:
        parts.append(f"<br>ghostworkflow exit code: {record.exit_code}")
    parts.append("</p>")
    if record.error:
        parts.append(f'<div class="notice error">{esc(record.error)}</div>')
    if record.status == "running":
        parts.append(
            '<div class="notice">Still running. This page refreshes '
            "every 3 seconds.</div>"
        )
    if record.run_dir:
        parts.append(
            f'<p><a class="btn" href="{_run_url(project, record.run_dir)}">'
            "View run</a> "
            f'<a class="btn ghost" href="{_board_url(project, record.run_dir)}">'
            "View board</a></p>"
        )
    if record.output_tail:
        parts.append(f"<h2>Workflow output (tail)</h2><pre>{esc(record.output_tail)}</pre>")
    refresh = 3 if record.status == "running" else None
    return page("Run status", "".join(parts), bind, refresh=refresh)


def run_detail(project: str, name: str, report: dict, run_dir: str,
               bind: str) -> str:
    parts = [f"<h1>Run {esc(report.get('run_id') or run_dir)}</h1>"]
    parts.append(
        f'<p><a href="{_project_url(project)}">&larr; {esc(name)}</a> '
        f'&middot; <a href="{_board_url(project, run_dir)}">View board</a></p>'
    )
    project_info = report.get("project") or {}
    parts.append(
        "<table>"
        f"<tr><th>Project</th><td>{esc(project_info.get('name'))} "
        f"<code>{esc(project_info.get('path'))}</code></td></tr>"
        f"<tr><th>Task</th><td>{esc(report.get('task')) or '<em>no task stated</em>'}</td></tr>"
        f"<tr><th>Started (UTC)</th><td>{esc(report.get('timestamp'))}</td></tr>"
        f"<tr><th>Verdict</th><td>{_pill(report.get('verdict'))}</td></tr>"
        f"<tr><th>Verification level</th><td>{_level_pill(report.get('verification_level'))}</td></tr>"
        f"<tr><th>Tree hash</th><td><code>{esc(report.get('tree_hash')) or 'not recorded'}</code></td></tr>"
        f"<tr><th>Tree hash source</th><td>{esc(report.get('tree_hash_source'))}</td></tr>"
        f"<tr><th>Commit</th><td><code>{esc(report.get('commit')) or 'not recorded'}</code></td></tr>"
        f"<tr><th>Orchestrator</th><td>{esc(report.get('tool'))} "
        f"{esc(report.get('tool_version'))}</td></tr>"
        f"<tr><th>Provenance</th><td>{esc(report.get('provenance'))}</td></tr>"
        "</table>"
    )
    parts.append(f'<p class="legend">{esc(LEVEL_LEGEND)}</p>')
    engines = report.get("engines") or {}
    if engines:
        rows = []
        for engine_name in sorted(engines):
            info = engines[engine_name] or {}
            found = "found" if info.get("found") else "NOT FOUND"
            rows.append(
                f"<tr><td>{esc(engine_name)}</td><td>{found}</td>"
                f"<td>{esc(info.get('version')) or 'unknown'}</td>"
                f"<td>{esc(info.get('how')) or ''}</td></tr>"
            )
        parts.append(
            "<h2>Engines</h2><table><tr><th>Engine</th><th>Found</th>"
            "<th>Version</th><th>How</th></tr>" + "".join(rows) + "</table>"
        )
    steps = report.get("steps") or []
    if steps:
        rows = []
        for step in steps:
            duration = step.get("duration_s")
            duration_txt = f"{duration:.2f}s" if isinstance(duration, (int, float)) else ""
            reports = "<br>".join(f"<code>{esc(r)}</code>" for r in (step.get("reports") or []))
            exit_code = step.get("exit_code")
            rows.append(
                f"<tr><td>{esc(step.get('name'))}</td>"
                f"<td>{esc(step.get('status'))}</td>"
                f"<td>{'' if exit_code is None else exit_code}</td>"
                f"<td>{esc(duration_txt)}</td>"
                f"<td>{esc(step.get('verdict')) or ''}</td>"
                f"<td>{reports}</td></tr>"
            )
        parts.append(
            "<h2>Steps</h2><table><tr><th>Step</th><th>Status</th>"
            "<th>Exit</th><th>Duration</th><th>Engine verdict</th>"
            "<th>Reports</th></tr>" + "".join(rows) + "</table>"
        )
        for step in steps:
            if step.get("detail"):
                parts.append(
                    f'<p class="meta">{esc(step.get("name"))}: '
                    f'{esc(step.get("detail"))}</p>'
                )
    return page(f"Run {report.get('run_id') or run_dir}", "".join(parts), bind)


def message_page(title: str, message: str, bind: str,
                 link: tuple[str, str] | None = None) -> str:
    body = f"<h1>{esc(title)}</h1><div class=\"notice\">{esc(message)}</div>"
    if link:
        body += f'<p><a href="{esc(link[0])}">{esc(link[1])}</a></p>'
    return page(title, body, bind)
