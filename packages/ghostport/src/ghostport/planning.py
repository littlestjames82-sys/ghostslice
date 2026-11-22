"""Build a full port plan (scan + units + sequence) and render it."""
from __future__ import annotations

import json
from pathlib import Path

from .graph import form_units
from .patterns import Pack
from .profile import load_port_profile
from .scanner import scan_project
from .tokens import METHOD


def build_plan(project: Path, pack: Pack) -> dict:
    """Scan ``project`` with ``pack`` and return the full plan dict.

    The dict is the exact shape written to port-plan.json: scan summary,
    units in port order, blockers, token total, and profile settings.
    """
    project = Path(project)
    profile = load_port_profile(project)
    scan = scan_project(project, pack)
    formed = form_units(project, scan, profile)
    plan = {
        "tool": "ghostport", "version": "0.1.0",
        "project": str(project),
        "pack": scan["pack"], "token_method": METHOD,
        "scan": {"hits": scan["hits"], "files_scanned": scan["files_scanned"],
                 "files_without_hits": scan["files_without_hits"],
                 "parse_errors": scan["parse_errors"],
                 "not_covered_languages": scan["not_covered_languages"],
                 "note": scan["note"]},
        "units": formed["units"], "blockers": formed["blockers"],
        "total_estimated_tokens": formed["total_estimated_tokens"],
        "profile": {"budget_tokens": profile.get("budget_tokens"),
                    "test_command": profile.get("test_command")},
    }
    return plan


def render_plan_md(plan: dict) -> str:
    """Render a plan dict as the PORT_PLAN.md markdown text."""
    lines = [f"# GhostPort plan: pack {plan['pack']['id']} v{plan['pack']['version']} ({plan['pack']['date']})",
             "", f"Project: {plan['project']}",
             f"Token figures are estimates ({plan['token_method']}).",
             f"Note: {plan['scan']['note']}", ""]
    if plan["scan"]["not_covered_languages"]:
        lines += ["## Languages not covered by this pack", ""]
        for lang, files in plan["scan"]["not_covered_languages"].items():
            lines.append(f"- {lang}: {len(files)} file(s) NOT scanned by this pack")
        lines.append("")
    lines += ["## Units in port order (leaves first)", "",
              "| # | Unit | Files | Hits | Patterns | Est. tokens | Depends on | Covering tests |",
              "|---|------|-------|------|----------|-------------|------------|----------------|"]
    for u in plan["units"]:
        lines.append(f"| {u['order']} | {u['id']} | {', '.join(u['files'])} | {u['hit_count']} | "
                     f"{', '.join(u['pattern_ids'])} | {u['estimated_tokens']} | "
                     f"{', '.join(u['depends_on_units']) or '-'} | {', '.join(u['covering_tests']) or 'none found'} |")
    lines += ["", f"Total estimated tokens (touched units): {plan['total_estimated_tokens']}", ""]
    if plan["blockers"]:
        lines += ["## Blockers", ""]
        for b in plan["blockers"]:
            lines.append(f"- CYCLE combined into {b['unit']}: {', '.join(b['files'])} must port together.")
        lines.append("")
    lines += ["## Files scanned with zero hits", ""]
    for f in plan["scan"]["files_without_hits"]:
        lines.append(f"- {f}")
    if plan["scan"]["parse_errors"]:
        lines += ["", "## Parse errors", ""]
        for e in plan["scan"]["parse_errors"]:
            lines.append(f"- {e['file']}: {e['error']}")
    lines += ["", "## Manual override",
              "Sequencing can be adjusted in .ghostslice.json under port.merge "
              "(combine units) and port.pin_first / port.order (tie-breakers only; "
              "dependency order is never overridden). GhostPort never rewrites code.", ""]
    return "\n".join(lines)


def write_plan(project: Path, pack: Pack, out_dir: Path | None = None) -> tuple[dict, Path, Path]:
    """Build a plan and write PORT_PLAN.md + port-plan.json.

    Files go to ``out_dir``, or to the project directory when it is
    omitted. Returns ``(plan, json_path, md_path)``.
    """
    plan = build_plan(project, pack)
    out_dir = Path(out_dir) if out_dir else Path(project)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "port-plan.json"
    md_path = out_dir / "PORT_PLAN.md"
    json_path.write_text(json.dumps(plan, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(render_plan_md(plan), encoding="utf-8")
    return plan, json_path, md_path
