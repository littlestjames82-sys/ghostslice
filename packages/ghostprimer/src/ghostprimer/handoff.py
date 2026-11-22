"""GhostHandoff pack consumption for the next GhostPrimer session.

A handoff pack is an explicit, optional input: either the pack
directory (containing ``handoff.json``) or the ``handoff.json`` file
itself. Only the recorded state, open loops and next steps are turned
into primer items. Every candidate item passes through the same
secret-shape scan as project memory; a flagged item is blocked and
recorded, never included. The items are returned unbudgeted: bundle
assembly puts them in the shared memory budget pool, so a supplied
handoff competes for the same memory share as Recall/fallback items.

Reading order inside a pack: state first, then open loops, then next
steps, matching the section order _render_primer emits for handoff
items in bundle.py.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import scan, secrets as secrets_mod


def _as_int(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _count(section: dict, count_key: str, list_key: str) -> int:
    count = _as_int(section.get(count_key))
    if count is not None:
        return count
    values = section.get(list_key)
    return len(values) if isinstance(values, list) else 0


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _state_text(data: dict) -> str:
    lines: list[str] = []
    if data.get("generated_at"):
        lines.append(f"Handoff generated at: {_text(data['generated_at'])}")
    project = data.get("project") or {}
    if isinstance(project, dict) and project.get("name"):
        lines.append(f"Project: {_text(project['name'])}")
    if data.get("session_window"):
        lines.append(f"Session window: {_text(data['session_window'])}")

    git = data.get("git") or {}
    if isinstance(git, dict) and git.get("available"):
        branch = _text(git.get("branch")) or "unknown"
        head = _text(git.get("head_short") or git.get("head")) or "unknown"
        lines.append(f"Branch: {branch} (HEAD {head})")
        status = git.get("status") or {}
        if isinstance(status, dict):
            lines.append(
                "Working tree: "
                f"{_count(status, 'staged_count', 'staged')} staged, "
                f"{_count(status, 'unstaged_count', 'unstaged')} unstaged, "
                f"{_count(status, 'untracked_count', 'untracked')} untracked")
        lines.append(f"Stash entries: {_count(git, 'stash_count', 'stash')}")
        if git.get("upstream"):
            ahead = git.get("ahead")
            behind = git.get("behind")
            lines.append(
                f"Upstream: {_text(git['upstream'])}, "
                f"{ahead if ahead is not None else 'unknown'} ahead, "
                f"{behind if behind is not None else 'unknown'} behind")
        commit_count = _as_int(git.get("commit_count"))
        if commit_count is None and isinstance(git.get("commits"), list):
            commit_count = len(git["commits"])
        files_total = _as_int(git.get("files_changed_total"))
        if commit_count is not None or files_total is not None:
            lines.append(
                f"Changed in window: {commit_count if commit_count is not None else 'unknown'} "
                f"commit(s), {files_total if files_total is not None else 'unknown'} file(s) touched")
        commits = git.get("commits")
        if isinstance(commits, list) and commits and isinstance(commits[0], dict):
            latest = commits[0]
            subject = _text(latest.get("subject"))
            short = _text(latest.get("short") or latest.get("hash"))
            if subject:
                lines.append(f"Latest commit: {short} {subject}".strip())
    elif isinstance(git, dict):
        reason = _text(git.get("reason")) or "git state was not recorded"
        lines.append(f"Git: unavailable ({reason})")

    reports = data.get("reports")
    if isinstance(reports, list):
        for report in reports:
            if not isinstance(report, dict):
                continue
            kind = _text(report.get("kind")) or "report"
            path = _text(report.get("path"))
            modified = _text(report.get("modified"))
            summary = _text(report.get("summary"))
            verdict = _text(report.get("verdict"))
            detail = summary or (f"verdict {verdict}" if verdict else "")
            prefix = f"Verification: {kind}"
            if path:
                prefix += f" at {path}"
            if modified:
                prefix += f" (modified {modified})"
            lines.append(prefix + (f": {detail}" if detail else ""))

    markers = data.get("markers")
    if isinstance(markers, dict) and "total" in markers:
        lines.append(
            f"Markers: {_count(markers, 'total', 'items')} total "
            f"({_as_int(markers.get('code_total')) or 0} in code, "
            f"{_as_int(markers.get('docs_total')) or 0} in documentation/fixture files)")
    return "\n".join(lines) if lines else "No state facts were recorded in the handoff pack."


def _loops_text(data: dict) -> str:
    loops = data.get("open_loops")
    if not isinstance(loops, list) or not loops:
        return "No open loops were recorded in the handoff pack."
    lines = []
    for loop in loops:
        if isinstance(loop, dict):
            kind = _text(loop.get("kind"))
            detail = _text(loop.get("detail") or loop.get("text"))
            source = _text(loop.get("source"))
            line = f"- [{kind}] {detail}" if kind else f"- {detail}"
            if source:
                line += f" (source: {source})"
            lines.append(line)
        else:
            lines.append(f"- {_text(loop)}")
    return "\n".join(lines)


def _steps_text(data: dict) -> str:
    steps = data.get("next_steps")
    if not isinstance(steps, list) or not steps:
        return "No next steps were recorded in the handoff pack."
    lines = []
    for idx, step in enumerate(steps, 1):
        if isinstance(step, dict):
            text = _text(step.get("text") or step.get("detail"))
            source = _text(step.get("source"))
            line = f"{idx}. {text}"
            if source:
                line += f" (source: {source})"
            lines.append(line)
        else:
            lines.append(f"{idx}. {_text(step)}")
    return "\n".join(lines)


def load_handoff_pack(project_root: Path, supplied) -> tuple[list[dict], list[dict], dict]:
    """Read a GhostHandoff pack and return (items, blocked, metadata).

    ``supplied`` may be a pack directory or its ``handoff.json`` file.
    The pack is an explicitly supplied input, so it need not live in
    the project tree; it must still describe this project when its
    JSON records a project path, and the assistant's private memory
    locations remain refused.
    """
    supplied_path = Path(supplied).expanduser()
    if scan.is_private_memory(supplied_path):
        raise ValueError(
            f"refused: handoff pack is in a private memory location: {supplied_path}")
    if not supplied_path.exists():
        raise ValueError(f"handoff pack not found: {supplied_path}")
    if supplied_path.is_dir():
        input_kind = "directory"
        json_path = supplied_path / "handoff.json"
        if not json_path.is_file():
            raise ValueError(
                f"handoff pack directory has no handoff.json: {supplied_path}")
    elif supplied_path.is_file():
        input_kind = "file"
        json_path = supplied_path
    else:
        raise ValueError(f"handoff pack is neither a directory nor a file: {supplied_path}")
    if scan.is_private_memory(json_path):
        raise ValueError(
            f"refused: handoff pack is in a private memory location: {json_path}")

    json_path = json_path.resolve()
    supplied_resolved = supplied_path.resolve()
    try:
        raw = json_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"handoff pack unreadable: {json_path}: {exc}") from exc
    try:
        data = json.loads(raw)
    except Exception as exc:
        raise ValueError(f"handoff pack is not valid JSON: {json_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"handoff pack JSON is not an object: {json_path}")
    tool = data.get("tool")
    if tool is not None and tool != "ghosthandoff":
        raise ValueError(f"not a GhostHandoff pack (tool={tool!r}): {json_path}")
    if tool is None and not any(
            key in data for key in
            ("project", "git", "open_loops", "next_steps", "session_window")):
        raise ValueError(f"not a GhostHandoff pack: {json_path}")

    project = data.get("project") or {}
    if isinstance(project, dict) and project.get("path"):
        described = Path(str(project["path"])).expanduser().resolve()
        if described != project_root.resolve():
            raise ValueError(
                "handoff pack describes a different project: "
                f"{described} (primer project is {project_root.resolve()})")

    candidates = [
        ("handoff-state", "Previous session state", _state_text(data)),
        ("handoff-open-loops", "Previous session open loops", _loops_text(data)),
        ("handoff-next-steps", "Previous session next steps", _steps_text(data)),
    ]
    items: list[dict] = []
    blocked: list[dict] = []
    for item_id, title, text in candidates:
        findings = secrets_mod.scan_text(text)
        if findings:
            blocked.append({
                "path": str(json_path),
                "title": title,
                "line": 1,
                "reason": "secret-shaped literal found ("
                          + ", ".join(sorted({f['type'] for f in findings}))
                          + "); handoff item blocked, value not recorded",
            })
            continue
        items.append({
            "id": item_id,
            "source_type": "handoff",
            "title": title,
            "text": text,
            "provenance": {
                "path": "handoff.json",
                "line": 1,
                "pack": str(json_path),
            },
            "status": "recorded",
        })

    metadata = {
        "input": str(supplied_resolved),
        "input_kind": input_kind,
        "json_path": str(json_path),
        "pack_dir": str(json_path.parent),
        "tool": tool or "ghosthandoff",
        "version": data.get("version"),
        "generated_at": data.get("generated_at"),
        "project": {
            "name": project.get("name") if isinstance(project, dict) else None,
            "path": project.get("path") if isinstance(project, dict) else None,
        },
    }
    return items, blocked, metadata
