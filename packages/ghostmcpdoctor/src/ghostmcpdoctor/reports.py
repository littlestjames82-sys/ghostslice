"""Report building (JSON dict) and rendering (JSON + Markdown files).

Input records are already redacted by the scanner, so rendering cannot
leak env values: there are none left to leak.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .checks import check_servers

REPORT_JSON = "mcpdoctor-report.json"
REPORT_MD = "MCPDOCTOR.md"


def exit_code_for(findings, configs_scanned, fallback=None) -> int:
    """The PLAN exit-code rule, in one place so scan and report agree.

    0 = scanned, no findings above info (an info-only report, e.g. a
    lone DISABLED entry, is a clean pass); 1 = at least one warning or
    error finding; 2 = could not scan (nothing was scanned). ``fallback``
    is used only when nothing was scanned and a stored report carries
    its own code.
    """
    if not configs_scanned:
        return 2 if fallback is None else int(fallback)
    if any(f.get("severity") != "info" for f in findings):
        return 1
    return 0


def build_report(scans, home, missing_explicit=None) -> dict:
    """Assemble the report dict from config scans.

    Runs the checks, inventories the (already redacted) server records,
    and computes the summary counts and exit code. The dict returned
    here is exactly what is written to ``mcpdoctor-report.json``.
    """
    findings = check_servers(scans, home)
    servers = [srv.inventory() for scan in scans for srv in scan.servers]
    by_severity = Counter(f["severity"] for f in findings)
    by_issue = Counter(f["issue"] for f in findings)
    worst = exit_code_for(findings, len(scans))
    return {
        "tool": "ghostmcpdoctor",
        "version": __version__,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "configs": [
            {"path": s.path, "client": s.client, "status": s.status,
             "server_count": len(s.servers)}
            for s in scans
        ],
        "missing_explicit_paths": list(missing_explicit or []),
        "servers": servers,
        "findings": findings,
        "summary": {
            "configs_scanned": len(scans),
            "servers_found": len(servers),
            "findings": len(findings),
            "by_severity": dict(sorted(by_severity.items())),
            "by_issue": dict(sorted(by_issue.items())),
            "stale": sum(1 for f in findings if f["stale"]),
            "duplicates": by_issue.get("DUPLICATE", 0),
        },
        "exit_code": worst,
        "notes": [
            "Read-only scan: no config was modified and no server was started.",
            "Env values are never reported: env keys are listed by name with "
            "present/absent only.",
            "MISSING-COMMAND for a bare command name is evidence, not proof: "
            "PATH inside the client app may differ from PATH here.",
        ],
    }


def render_markdown(report: dict) -> str:
    """Render a report dict as the human-readable ``MCPDOCTOR.md`` text."""
    s = report.get("summary", {})
    lines = [
        "# GhostMCP Doctor report",
        "",
        f"Tool: ghostmcpdoctor {report.get('version', '')} - read-only scan. "
        "Findings are server name + path + issue only. Env values are never shown.",
        "",
        "## Summary",
        "",
        f"- Configs scanned: {s.get('configs_scanned', 0)}",
        f"- Servers found: {s.get('servers_found', 0)}",
        f"- Findings: {s.get('findings', 0)} "
        f"(stale evidence: {s.get('stale', 0)}, duplicates: {s.get('duplicates', 0)})",
        f"- By severity: {s.get('by_severity', {})}",
        f"- By issue: {s.get('by_issue', {})}",
        "",
        "## Configs",
        "",
    ]
    for cfg in report.get("configs", []):
        lines.append(f"- `{cfg.get('path')}` ({cfg.get('client')}) - "
                     f"{cfg.get('status')}, {cfg.get('server_count')} server(s)")
    for missing in report.get("missing_explicit_paths", []):
        lines.append(f"- `{missing}` - NOT FOUND (named explicitly)")
    lines += ["", "## Servers", ""]
    if not report.get("servers"):
        lines.append("No servers found.")
    for srv in report.get("servers", []):
        env = ", ".join(srv.get("env_keys", [])) or "none"
        lines.append(
            f"- **{srv.get('name')}** in `{srv.get('config_path')}` "
            f"({srv.get('client')}, {srv.get('transport')}"
            + (f", command: {srv.get('command')}" if srv.get("command") else "")
            + (f", url host: {srv.get('url_host')}" if srv.get("url_host") else "")
            + f", env keys present: {env}"
            + (", DISABLED" if srv.get("disabled") else "") + ")")
    lines += ["", "## Findings", ""]
    if not report.get("findings"):
        lines.append("No findings. Nothing above info level was detected.")
    for f in report.get("findings", []):
        loc = f.get("path") or f.get("config_path")
        lines.append(f"- [{f.get('severity')}] **{f.get('server') or '(config)'}** - "
                     f"`{loc}` - {f.get('issue')}: {f.get('detail')}"
                     + (" (stale)" if f.get("stale") else ""))
    lines += ["", "## Notes", ""]
    for note in report.get("notes", []):
        lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)


def write_reports(report: dict, out_dir) -> tuple[Path, Path]:
    """Write ``mcpdoctor-report.json`` and ``MCPDOCTOR.md`` into ``out_dir``.

    Creates the directory if needed and returns ``(json_path, md_path)``.
    This is the only place Doctor writes files, and it never writes
    into or next to a scanned config unless the caller chose that dir.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / REPORT_JSON
    md_path = out / REPORT_MD
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path
