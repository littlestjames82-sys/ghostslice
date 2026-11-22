"""One tolerant adapter per Ghost tool.

Every adapter reads only that tool's published report artifacts, by
file name and documented shape, using nothing but the stdlib. No
sibling tool is imported or executed.

Tolerance rules, shared by all adapters:
- Missing tool: the section is ABSENT ("no report found"). Never an
  error, never affects anything beyond its own row.
- Present but unparseable: the section is UNREADABLE and says why.
- Present and parseable but with unrecognized fields: the section is
  OK with a summary that only claims what was recognized, or says the
  shape was not recognized in detail.
- Searches under a project are bounded (depth, visited-file cap,
  skipped directories, no symlink following, per-file size cap).
- Provenance: a report found under a test, fixture, or example
  directory is fixture material the project ships, not live state the
  project produced. Adapters search live paths first and only fall
  back to fixture paths when no live report exists; the section is
  then labelled "fixture" (see _provenance) and the classifier never
  lets it place the project.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .model import (ABSENT, ATTENTION, LEVEL_RANK, OK, STALE, UNREADABLE,
                    Section)

MAX_DEPTH = 4
MAX_VISITED = 20000
MAX_FILE_BYTES = 5 * 1024 * 1024
SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", ".tox",
    ".mypy_cache", ".pytest_cache", "dist", "build", ".idea",
}


# ---------------------------------------------------------------- IO

def _read_json(path: Path):
    """Return (object, error_str). Exactly one of the two is not None."""
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return None, "report larger than the 5 MB parse cap"
        return json.loads(path.read_text(encoding="utf-8")), None
    except Exception as exc:  # unreadable is a board state, not a crash
        return None, f"{type(exc).__name__}: {exc}"


def _read_jsonl(path: Path):
    """Return (rows, bad_line_count, error_str)."""
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return [], 0, "history larger than the 5 MB parse cap"
        rows, bad = [], 0
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    rows.append(obj)
                else:
                    bad += 1
            except ValueError:
                bad += 1
        return rows, bad, None
    except Exception as exc:
        return [], 0, f"{type(exc).__name__}: {exc}"


def find_candidates(root: Path, filename: str,
                      cap: int = 50) -> list[Path]:
    """Files named `filename` under root, newest first, bounded walk."""
    found: list[tuple[float, Path]] = []
    visited = 0
    root = Path(root)
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        depth = len(Path(dirpath).relative_to(root).parts)
        dirnames[:] = [d for d in dirnames
                       if d not in SKIP_DIRS and depth < MAX_DEPTH]
        if depth >= MAX_DEPTH:
            dirnames[:] = []
        for name in filenames:
            visited += 1
            if visited > MAX_VISITED:
                found.sort(key=lambda item: -item[0])
                return [p for _m, p in found[:cap]]
            if name != filename:
                continue
            cand = Path(dirpath) / name
            try:
                if cand.is_symlink():
                    continue
                mtime = cand.stat().st_mtime
            except OSError:
                continue
            found.append((mtime, cand))
    found.sort(key=lambda item: -item[0])
    return [p for _m, p in found[:cap]]


def find_newest(root: Path, filename: str, validate=None,
                provenance: str | None = None) -> Path | None:
    """Newest file named `filename` under root.

    validate(path) -> bool can reject look-alike files (for example a
    node manifest.json that is not a GhostSlice bundle manifest).
    provenance="live" / "fixture" restricts the search to one class of
    paths (see _provenance); None searches everything, as before.
    """
    for cand in find_candidates(root, filename):
        if provenance is not None and \
                _provenance(cand, Path(root)) != provenance:
            continue
        if validate is None or validate(cand):
            return cand
    return None


def pick_report(root: Path, filename: str, shape,
                provenance: str | None = None) -> tuple:
    """Pick the newest report file whose parsed shape matches.

    shape(obj) -> bool decides whether a parsed JSON object is really
    this tool's report. Returns (path, obj, corrupt_path, corrupt_err):
    on a match, path/obj are set; when files with this exact (Ghost
    specific) name exist but none parse, the newest one's error is
    returned so the caller can show an unreadable row instead of a
    misleading absent row. provenance restricts the candidate paths to
    one class (see _provenance); None searches everything, as before.
    """
    corrupt_path = corrupt_err = None
    for cand in find_candidates(root, filename):
        if provenance is not None and \
                _provenance(cand, Path(root)) != provenance:
            continue
        obj, err = _read_json(cand)
        if err is not None:
            if corrupt_path is None:
                corrupt_path, corrupt_err = cand, err
            continue
        if not isinstance(obj, dict):
            # Valid JSON but not a report object (a list, a number,
            # null): for these Ghost-specific file names that is a
            # corrupt report, not an absent one. Record it so the
            # caller can show an unreadable row instead of dropping
            # the file silently.
            if corrupt_path is None:
                corrupt_path, corrupt_err = cand, "not a JSON object"
            continue
        if shape(obj):
            return cand, obj, None, None
    return None, None, corrupt_path, corrupt_err


def pick_report_two_pass(root: Path, filename: str, shape) -> tuple:
    """pick_report over live paths first, then fixture/example paths.

    Returns (path, obj, corrupt_path, corrupt_err, provenance). A live
    result (match or corrupt) always wins: a live unreadable report is
    the project's real state and is never masked by fixture material.
    Only when no live file with this name exists at all are fixture
    paths considered, and the result is labelled "fixture" so it can
    be shown as evidence without driving the project's column.
    """
    for prov in ("live", "fixture"):
        path, obj, corrupt, corrupt_err = pick_report(
            root, filename, shape, provenance=prov)
        if path is not None or corrupt is not None:
            return path, obj, corrupt, corrupt_err, prov
    return None, None, None, None, "live"


def parse_time(value) -> datetime | None:
    """Best-effort timestamp: ISO strings and epoch numbers."""
    if value is None:
        return None
    if isinstance(value, bool):
        # JSON true/false is not an epoch; int(True) == 1 would
        # otherwise become a 1970 "reported" time.
        return None
    if isinstance(value, (int, float)) and value > 0:
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    return None


def _mtime(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def _when(path: Path, embedded) -> tuple[datetime, str]:
    dt = parse_time(embedded)
    if dt is not None:
        return dt, "reported"
    return _mtime(path), "mtime"


def _is_int(value) -> bool:
    """True for real JSON integers. bool is an int subclass in
    Python, but a report field carrying true/false is not a count."""
    return isinstance(value, int) and not isinstance(value, bool)


def _fmt_int(value) -> str:
    if isinstance(value, bool):
        return "?"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "?"


def _int_or_none(value) -> int | None:
    """An int field exactly as written, or None. Bools are not counts
    and floats/strings are not guessed at."""
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) else None


def _history_rows(project: Path, filename: str) -> list:
    """Readable rows of a project's history file, for trend context.

    Best-effort only: a missing or unreadable history yields no trend.
    The history's own adapter branch still reports an unreadable
    history as UNREADABLE when that history is the row's evidence;
    this helper is used when another report is the row's evidence, or
    alongside rows the caller already read.
    """
    path = project / filename
    if not path.is_file():
        return []
    rows, _bad, err = _read_jsonl(path)
    return rows if err is None else []


# ------------------------------------------------------- history trends
# A trend summarizes a tool's recorded history (2+ readable entries):
# how many entries, and how the latest compares with the previous
# one. Trends are context on the row, never a verdict: they are built
# only from fields each adapter already recognizes, and the
# classifier never sees them, so history can neither promote a
# project with a recovered latest report nor demote one whose older
# entries were worse.

def _slice_trend(rows: list) -> str:
    if len(rows) < 2:
        return ""
    parts = [f"{len(rows)} entries recorded in history"]
    saved = []
    for row in rows:
        value = _int_or_none(row.get("saved_tokens"))
        if value is None:
            before = _int_or_none(row.get("before_tokens"))
            after = _int_or_none(row.get("after_tokens"))
            if before is not None and after is not None:
                value = before - after
        saved.append(value)
    latest, previous = saved[-1], saved[-2]
    if latest is not None and previous is not None:
        if latest > previous:
            change = f"up {_fmt_int(latest - previous)}"
        elif latest < previous:
            change = f"down {_fmt_int(previous - latest)}"
        else:
            change = "unchanged"
        parts.append(f"tokens saved {_fmt_int(previous)} -> "
                     f"{_fmt_int(latest)} ({change})")
    return "; ".join(parts)


def _verify_trend(rows: list) -> str:
    if len(rows) < 2:
        return ""
    attention = sum(1 for row in rows
                    if _verdict_state(row.get("verdict")) == ATTENTION)
    parts = [f"{len(rows)} verdicts recorded in history",
             f"{attention} needed attention"]
    latest, previous = rows[-1].get("verdict"), rows[-2].get("verdict")
    if isinstance(latest, str) and isinstance(previous, str) and latest:
        if latest == previous:
            parts.append(f"verdict unchanged from previous ({latest})")
        else:
            parts.append(f"verdict changed: {previous} -> {latest}")
    return "; ".join(parts)


def _bench_failed_count(row: dict) -> int | None:
    """Failing-task count on one Bench history line, or None.

    Bench's history writer records "tasks_failed"; "failed" is also
    honoured. Reading only "failed" used to make a history-only
    project with failing runs read as ok. A boolean or negative
    value is not a count (harden lane): it is skipped, falling
    through to the other key, and yields None if neither counts.
    """
    for key in ("tasks_failed", "failed"):
        value = _int_or_none(row.get(key))
        if value is not None and value >= 0:
            return value
    return None


def _bench_trend(rows: list) -> str:
    if len(rows) < 2:
        return ""
    parts = [f"{len(rows)} runs recorded in history"]
    counts = [_bench_failed_count(row) for row in rows]
    latest, previous = counts[-1], counts[-2]
    if latest is not None and previous is not None:
        parts.append(f"failing tasks {_fmt_int(previous)} -> "
                     f"{_fmt_int(latest)}")
    return "; ".join(parts)


def _rel(path: Path, project: Path) -> str:
    try:
        return str(path.relative_to(project))
    except ValueError:
        return str(path)


# ---------------------------------------------------------- provenance

# Path segments that mark shipped test/example material rather than a
# project's live reports. The ecosystem run of Oct 14, 2026 found all
# three of the board's Attention rows were reports under examples/,
# tests/fixtures/, and examples/fixture_reports/ inside the projects:
# fixture evidence wearing live clothing. A segment containing
# "fixture" (fixture_reports, __fixtures__, fixture-data) also counts.
FIXTURE_SEGMENTS = frozenset({
    "test", "tests", "testing", "example", "examples",
    "fixture", "fixtures", "sample", "samples",
    "testdata", "test-data", "snapshots",
})


def _provenance(path: Path, project: Path) -> str:
    """Classify a discovered report path as "live" or "fixture".

    Relative to the project root: a file at the root, or under ordinary
    working directories, is live. A file under a test, fixture, or
    example directory is fixture/example material the project ships,
    not state the project produced by being used.
    """
    try:
        parts = path.relative_to(project).parts
    except ValueError:
        return "live"
    for part in parts[:-1]:
        low = part.lower()
        if low in FIXTURE_SEGMENTS or "fixture" in low:
            return "fixture"
    return "live"


def _tag(section: Section, provenance: str) -> Section:
    """Record a section's provenance, labelling fixture evidence on
    its face so every renderer (HTML, text, JSON) shows it."""
    section.provenance = provenance
    if provenance == "fixture" and section.state != ABSENT:
        section.summary += " (fixture/example report)"
    return section


# ------------------------------------------------- evidence contract
# Reports written after the shared evidence contract carry
# "verification_level", "tool_version", and sometimes their own
# "provenance". These helpers read those fields exactly as written:
# a level outside the contract enum is not a level, a version that
# is not a string is not a version, and nothing is ever inferred
# from other fields (a tier string is not a verification level).

def _stated_level(obj: dict) -> str | None:
    value = obj.get("verification_level")
    if isinstance(value, str) and value.strip().lower() in LEVEL_RANK:
        return value.strip().lower()
    return None


def _stated_version(obj: dict) -> str | None:
    value = obj.get("tool_version")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _apply_evidence(section: Section, obj: dict) -> Section:
    """Carry a report's stated evidence-contract fields onto its
    section. Absent fields stay None: not stated, never invented."""
    level = _stated_level(obj)
    if level is not None:
        section.verification_level = level
    version = _stated_version(obj)
    if version is not None:
        section.tool_version = version
    return section


def _mark_sample(section: Section) -> Section:
    """A report that declares provenance "sample" is sample
    evidence wherever it sits on disk: shown, labelled, and (like
    fixture material) never live state. The path-based label, when
    the file also sits under a fixture path, is kept as well."""
    section.provenance = "sample"
    if section.state != ABSENT and \
            "(sample report)" not in section.summary:
        section.summary += " (sample report)"
    return section


# ---------------------------------------------------------------- Slice

def slice_section(project: Path) -> Section:
    """GhostSlice row: latest history line, else newest bundle manifest."""
    tool = "GhostSlice"
    history = project / ".ghostslice-history.jsonl"
    if history.is_file():
        rows, bad, err = _read_jsonl(history)
        if err:
            return Section(tool, UNREADABLE, f"history unreadable ({err})",
                           _rel(history, project), reason="history unreadable")
        if not rows:
            return Section(tool, UNREADABLE,
                           "history file present but has no readable lines",
                           _rel(history, project),
                           reason="history present but empty of records")
        last = rows[-1]
        when, kind = _when(history, last.get("at") or last.get("ts")
                           or last.get("timestamp"))
        before, after = last.get("before_tokens"), last.get("after_tokens")
        if before is not None and after is not None:
            summary = (f"latest {last.get('kind', 'run')}: "
                       f"{_fmt_int(before)} -> {_fmt_int(after)} tokens")
            saved = last.get("saved_tokens")
            if saved is not None:
                summary += f" (saved {_fmt_int(saved)})"
        else:
            summary = f"latest history line: {last.get('kind', 'run')}"
        if bad:
            summary += f"; {bad} unreadable line(s) skipped"
        section = Section(tool, OK, summary, _rel(history, project),
                          when, kind)
        section.trend = _slice_trend(rows)
        return section

    def _is_slice_manifest(p: Path) -> bool:
        obj, err = _read_json(p)
        return (err is None and isinstance(obj, dict)
                and isinstance(obj.get("files"), list)
                and ("total_sliced_tokens" in obj or "root" in obj))

    manifest = find_newest(project, "manifest.json",
                           validate=_is_slice_manifest,
                           provenance="live")
    prov = "live"
    if manifest is None:
        manifest = find_newest(project, "manifest.json",
                               validate=_is_slice_manifest,
                               provenance="fixture")
        prov = "fixture"
    if manifest is not None:
        obj, _ = _read_json(manifest)
        when, kind = _when(manifest, obj.get("generated_at"))
        total = obj.get("total_sliced_tokens")
        orig = obj.get("total_original_tokens")
        if total is not None and orig is not None:
            summary = (f"latest bundle: {_fmt_int(orig)} -> "
                       f"{_fmt_int(total)} tokens, "
                       f"{len(obj.get('files', []))} files")
        else:
            summary = "latest bundle manifest found"
        return _tag(Section(tool, OK, summary, _rel(manifest, project),
                            when, kind), prov)
    return Section(tool)


# ---------------------------------------------------------------- Verify

# Exact verdict vocabularies, grounded in the sibling tools' writers,
# matched whole (after strip + lower), never by substring. Anything
# outside the known vocabulary returns None and is shown verbatim on
# the row, never guessed at.
#
# GhostVerify (core.py / reports.py): pre verdicts "sufficient",
# "sufficient_after_expand", "gaps_found", "gaps_remain",
# "could_not_verify"; post (patch) verdicts "ok", "failed", "flagged",
# "could_not_verify"; "insufficient" is the documented plan-level word.
# Substring matching put "could_not_verify" (a check that did not
# complete; GhostVerify returns a passing verdict only on positive
# evidence) and "flagged" (findings present, exit 1) on ok rows.
_VERIFY_OK_WORDS = frozenset({"sufficient", "sufficient_after_expand", "ok"})
_VERIFY_ATTENTION_WORDS = frozenset({
    "insufficient", "gaps_found", "gaps_remain", "could_not_verify",
    "failed", "flagged",
})
# GhostBench (runner.py): task row statuses "pass" / "fail" /
# "unknown" (report fixtures also carry "passed" / "failed"). "unknown"
# is Bench's own third bucket, counted separately from failures there,
# so it is deliberately in neither set: it never counts as failing.
_BENCH_OK_WORDS = frozenset({"pass", "passed"})
_BENCH_FAILING_WORDS = frozenset({"fail", "failed"})


def _exact_state(value, ok_words, attention_words) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    low = value.strip().lower()
    if low in attention_words:
        return ATTENTION
    if low in ok_words:
        return OK
    return None


def _verdict_state(verdict) -> str | None:
    """GhostVerify verdicts (report, post, and history lines)."""
    return _exact_state(verdict, _VERIFY_OK_WORDS, _VERIFY_ATTENTION_WORDS)


def _bench_status_state(status) -> str | None:
    """GhostBench task statuses."""
    return _exact_state(status, _BENCH_OK_WORDS, _BENCH_FAILING_WORDS)


def verify_section(project: Path) -> Section:
    """GhostVerify row: newest verify report, else latest history verdict."""
    tool = "GhostVerify"

    report, obj, corrupt, corrupt_err, prov = pick_report_two_pass(
        project, "verify-report.json", lambda o: "verdict" in o)
    if report is None and corrupt is not None:
        return _tag(Section(tool, UNREADABLE,
                            f"report found but unreadable ({corrupt_err})",
                            _rel(corrupt, project),
                            reason="Verify report unreadable"), prov)
    if report is not None:
        verdict = obj.get("verdict")
        state = _verdict_state(verdict)
        summary = f"verdict: {verdict}"
        reason = ""
        gaps = obj.get("gaps")
        if isinstance(gaps, list) and gaps:
            summary += f", {len(gaps)} gap(s)"
        post = obj.get("post")
        if isinstance(post, dict) and post.get("verdict"):
            summary += f"; patch: {post['verdict']}"
            if _verdict_state(post.get("verdict")) == ATTENTION:
                state = ATTENTION
        if state is None:
            state = OK
            summary += " (verdict wording not recognized)"
        if state == ATTENTION:
            reason = f"Verify verdict: {verdict}"
            if isinstance(post, dict) and \
                    _verdict_state(post.get("verdict")) == ATTENTION:
                reason = f"Verify patch verdict: {post.get('verdict')}"
        when, kind = _when(report, obj.get("generated_at") or obj.get("at"))
        section = _tag(Section(tool, state, summary, _rel(report, project),
                               when, kind, reason), prov)
        _apply_evidence(section, obj)
        section.trend = _verify_trend(
            _history_rows(project, ".ghostverify-history.jsonl"))
        return section

    history = project / ".ghostverify-history.jsonl"
    if history.is_file():
        rows, _bad, err = _read_jsonl(history)
        if err:
            return Section(tool, UNREADABLE, f"history unreadable ({err})",
                           _rel(history, project),
                           reason="Verify history unreadable")
        if not rows:
            # Same rule as Slice: a present history with no readable
            # records is unreadable evidence, never an absent row.
            return Section(tool, UNREADABLE,
                           "history file present but has no readable lines",
                           _rel(history, project),
                           reason="history present but empty of records")
        if rows:
            last = rows[-1]
            verdict = last.get("verdict")
            state = _verdict_state(verdict)
            summary = f"latest verdict: {verdict}"
            if state is None:
                state = OK
                summary += " (verdict wording not recognized)"
            patch = last.get("patch_result")
            if patch:
                summary += f"; patch: {patch}"
                if _verdict_state(patch) == ATTENTION:
                    state = ATTENTION
            when, kind = _when(history, last.get("at"))
            reason = (f"Verify verdict: {verdict}"
                      if state == ATTENTION else "")
            section = Section(tool, state, summary, _rel(history, project),
                              when, kind, reason)
            _apply_evidence(section, last)
            section.trend = _verify_trend(rows)
            return section
    return Section(tool)


# ---------------------------------------------------------------- Bench

def bench_section(project: Path) -> Section:
    """GhostBench row: newest bench report, else latest history run."""
    tool = "GhostBench"

    report, obj, corrupt, corrupt_err, prov = pick_report_two_pass(
        project, "bench-report.json",
        lambda o: isinstance(o.get("tasks"), list))
    if report is None and corrupt is not None:
        return _tag(Section(tool, UNREADABLE,
                            f"report found but unreadable ({corrupt_err})",
                            _rel(corrupt, project),
                            reason="Bench report unreadable"), prov)
    if report is not None:
        tasks = obj.get("tasks", [])
        failed = sum(1 for t in tasks if isinstance(t, dict)
                     and _bench_status_state(t.get("status")) == ATTENTION)
        run = obj.get("run_id", "unknown run")
        summary = f"run {run}: {len(tasks)} task(s)"
        if failed:
            summary += f", {failed} failed"
        version = _stated_version(obj)
        if version is not None:
            summary += f" (ghostbench {version})"
        when, kind = _when(report, obj.get("generated_at")
                           or obj.get("created_utc") or obj.get("at"))
        state = ATTENTION if failed else OK
        reason = f"Bench run {run}: {failed} failing task(s)" if failed else ""
        section = _tag(Section(tool, state, summary, _rel(report, project),
                               when, kind, reason), prov)
        _apply_evidence(section, obj)
        # The report's own word on provenance beats its path: a
        # report declaring "sample" is sample evidence even at a
        # live path, and must never place the project.
        declared = obj.get("provenance")
        if isinstance(declared, str) and \
                declared.strip().lower() == "sample":
            _mark_sample(section)
        section.trend = _bench_trend(
            _history_rows(project, ".ghostbench-history.jsonl"))
        return section

    history = project / ".ghostbench-history.jsonl"
    if history.is_file():
        rows, _bad, err = _read_jsonl(history)
        if err:
            return Section(tool, UNREADABLE, f"history unreadable ({err})",
                           _rel(history, project),
                           reason="Bench history unreadable")
        if not rows:
            return Section(tool, UNREADABLE,
                           "history file present but has no readable lines",
                           _rel(history, project),
                           reason="history present but empty of records")
        if rows:
            last = rows[-1]
            when, kind = _when(history, last.get("at"))
            failed = _bench_failed_count(last)
            state = ATTENTION if failed else OK
            summary = f"latest run: {last.get('run_id', 'recorded')}"
            if failed:
                summary += f", {_fmt_int(failed)} failed"
            reason = ("Bench history records failing tasks"
                      if failed else "")
            section = Section(tool, state, summary, _rel(history, project),
                              when, kind, reason)
            _apply_evidence(section, last)
            section.trend = _bench_trend(rows)
            return section
    return Section(tool)


# ---------------------------------------------------------------- Workflow

# GhostWorkflow (evidence.py): run verdicts "ok" / "attention" /
# "failed". A failed run is parseable evidence that a step failed, so
# it maps to ATTENTION, exactly as GhostVerify's "failed" patch
# verdict does; there is no separate error state on the board.
# "error" is honoured defensively for the same outcome.
_WORKFLOW_OK_WORDS = frozenset({"ok"})
_WORKFLOW_ATTENTION_WORDS = frozenset({"attention", "failed", "error"})


def _workflow_state(verdict) -> str | None:
    """GhostWorkflow run verdicts."""
    return _exact_state(verdict, _WORKFLOW_OK_WORDS,
                        _WORKFLOW_ATTENTION_WORDS)


def _is_workflow_report(obj) -> bool:
    if not isinstance(obj, dict):
        return False
    if obj.get("tool") == "ghostworkflow":
        return True
    return "verdict" in obj and isinstance(obj.get("steps"), list)


def _workflow_candidates(project: Path) -> list[Path]:
    """Run reports at .ghostworkflow/<run-id>/workflow-report.json,
    newest first.

    GhostWorkflow writes exactly one layout: a run directory under
    the project's .ghostworkflow/ holding workflow-report.json (and
    the board.html the run rendered beside it). Discovery is scoped
    to that layout rather than the name-anywhere search the older
    adapters use: a same-named file elsewhere was not written by a
    workflow run. The directory is never a fixture segment, so these
    reports are live by path, as _provenance would also find.
    """
    found = []
    for cand in find_candidates(project, "workflow-report.json"):
        try:
            parts = cand.relative_to(Path(project)).parts
        except ValueError:
            continue
        if len(parts) == 3 and parts[0] == ".ghostworkflow":
            found.append(cand)
    return found


def workflow_section(project: Path) -> Section:
    """GhostWorkflow row: newest run report under .ghostworkflow/."""
    tool = "GhostWorkflow"
    report = obj = corrupt = corrupt_err = None
    for cand in _workflow_candidates(project):
        parsed, err = _read_json(cand)
        if err is not None:
            if corrupt is None:
                corrupt, corrupt_err = cand, err
            continue
        if not isinstance(parsed, dict):
            if corrupt is None:
                corrupt, corrupt_err = cand, "not a JSON object"
            continue
        if _is_workflow_report(parsed):
            report, obj = cand, parsed
            break
    if report is None and corrupt is not None:
        return Section(tool, UNREADABLE,
                       f"report found but unreadable ({corrupt_err})",
                       _rel(corrupt, project),
                       reason="Workflow report unreadable")
    if report is None:
        return Section(tool)
    verdict = obj.get("verdict")
    state = _workflow_state(verdict)
    run = obj.get("run_id", "unknown run")
    if isinstance(verdict, str) and verdict.strip():
        summary = f"run {run}: verdict {verdict.strip()}"
    else:
        summary = f"run {run}: no verdict recorded"
    steps = obj.get("steps")
    if isinstance(steps, list):
        outcomes = []
        for step in steps:
            if isinstance(step, dict) and \
                    isinstance(step.get("name"), str) and \
                    isinstance(step.get("status"), str):
                outcomes.append(f"{step['name']} {step['status']}")
        if outcomes:
            summary += "; steps: " + ", ".join(outcomes)
    tree_hash = obj.get("tree_hash")
    if isinstance(tree_hash, str) and tree_hash.strip():
        summary += f"; tree_hash {tree_hash.strip()}"
    version = _stated_version(obj)
    if version is not None:
        summary += f" (ghostworkflow {version})"
    if state is None:
        state = OK
        summary += " (verdict wording not recognized)"
    reason = f"Workflow verdict: {verdict}" if state == ATTENTION else ""
    when, kind = _when(report, obj.get("timestamp")
                       or obj.get("generated_at") or obj.get("at"))
    # The row's artifact is the board the run rendered beside its
    # report: that is the file a reader opens from this row. When no
    # board sits beside the report, the row names the report itself,
    # as every other adapter does. (Rows carry a project-relative
    # source path; the board renders sources as text, like all rows.)
    board_html = report.parent / "board.html"
    source = _rel(board_html if board_html.is_file() else report,
                  project)
    section = Section(tool, state, summary, source, when, kind, reason)
    # The report's own contract fields (level, tool_version) are
    # carried exactly as stated. Its "provenance" field is not read:
    # ghostworkflow's schema fixes it to "live", and a workflow
    # report is never treated as sample evidence.
    _apply_evidence(section, obj)
    return section


# ---------------------------------------------------------------- Scope

def scope_section(project: Path) -> Section:
    """GhostScope row: newest scope pack found under the project."""
    tool = "GhostScope"
    pack = find_newest(project, "scope.json", provenance="live")
    prov = "live"
    if pack is None:
        pack = find_newest(project, "scope.json", provenance="fixture")
        prov = "fixture"
    if pack is None:
        return Section(tool)
    obj, err = _read_json(pack)
    if err or not isinstance(obj, dict):
        return _tag(Section(tool, UNREADABLE,
                            f"pack unreadable "
                            f"({err or 'not a JSON object'})",
                            _rel(pack, project),
                            reason="Scope pack unreadable"), prov)
    counts = []
    for key in ("changed_files", "files", "changed", "entries", "packed"):
        value = obj.get(key)
        if isinstance(value, list):
            counts.append(f"{len(value)} {key.replace('_', ' ')}")
            break
        if _is_int(value):
            counts.append(f"{value} {key.replace('_', ' ')}")
            break
    risk = obj.get("max_risk", obj.get("risk"))
    if isinstance(risk, (int, float)):
        counts.append(f"max risk {risk}")
    summary = ("pack: " + ", ".join(counts)) if counts else \
        "pack found (shape not recognized in detail)"
    when, kind = _when(pack, obj.get("generated_at"))
    return _tag(Section(tool, OK, summary, _rel(pack, project), when, kind),
                prov)


# ---------------------------------------------------------------- Ledger

def _loop_count(value) -> int:
    if isinstance(value, list):
        return len(value)
    if _is_int(value):
        return value
    return 0


def ledger_section(project: Path) -> Section:
    """GhostLedger row: ledger-report.json, else the raw ledger file."""
    tool = "GhostLedger"
    report = project / "ledger-report.json"
    if report.is_file():
        obj, err = _read_json(report)
        if err or not isinstance(obj, dict):
            return Section(tool, UNREADABLE,
                           f"report unreadable ({err or 'not a JSON object'})",
                           _rel(report, project),
                           reason="Ledger report unreadable")
        totals = obj.get("totals", {}) if isinstance(obj.get("totals"), dict) \
            else {}
        loops = _loop_count(obj.get("loop_warnings"))
        if not loops and isinstance(totals, dict):
            loops = _loop_count(totals.get("loop_warnings"))
        entries = totals.get("entries", obj.get("entries"))
        cost = totals.get("cost_estimate_usd", obj.get("cost_estimate_usd"))
        if cost is None:
            # GhostLedger's report writer (and its shipped fixtures)
            # name the estimate "estimated_cost" inside totals.
            cost = totals.get("estimated_cost", obj.get("estimated_cost"))
        parts = []
        if entries is not None:
            parts.append(f"{_fmt_int(entries)} entries")
        if cost is not None:
            parts.append(f"est. cost ${cost} (estimate, dated price table)")
        summary = "totals: " + ", ".join(parts) if parts else \
            "report found (shape not recognized in detail)"
        if loops:
            summary += f"; {loops} loop warning(s)"
        when, kind = _when(report, obj.get("generated_at") or obj.get("as_of"))
        state = ATTENTION if loops else OK
        reason = f"Ledger: {loops} loop warning(s)" if loops else ""
        section = Section(tool, state, summary, _rel(report, project),
                          when, kind, reason)
        return _apply_evidence(section, obj)

    ledger = project / ".ghostledger.jsonl"
    if ledger.is_file():
        rows, _bad, err = _read_jsonl(ledger)
        if err:
            return Section(tool, UNREADABLE, f"ledger unreadable ({err})",
                           _rel(ledger, project),
                           reason="Ledger file unreadable")
        if not rows:
            # An empty/corrupt-only ledger file is not evidence that
            # everything is ok: without this, a project whose only
            # report is an empty ledger file landed in Verified.
            return Section(tool, UNREADABLE,
                           "ledger file present but has no readable lines",
                           _rel(ledger, project),
                           reason="ledger present but empty of records")
        loops = sum(1 for r in rows if r.get("loop_warning"))
        summary = f"{len(rows)} entries (no ledger-report.json)"
        if loops:
            summary += f"; {loops} loop warning(s)"
        when = _mtime(ledger)
        state = ATTENTION if loops else OK
        reason = f"Ledger: {loops} loop warning(s)" if loops else ""
        return Section(tool, state, summary, _rel(ledger, project),
                       when, "mtime", reason)
    return Section(tool)


# ---------------------------------------------------------------- Watch

def watch_section(project: Path) -> Section:
    """GhostWatch row: newest watch report and its freshness verdict."""
    tool = "GhostWatch"

    report, obj, corrupt, corrupt_err, prov = pick_report_two_pass(
        project, "watch-report.json", lambda o: "verdict" in o)
    if report is None and corrupt is not None:
        return _tag(Section(tool, UNREADABLE,
                            f"report found but unreadable ({corrupt_err})",
                            _rel(corrupt, project),
                            reason="Watch report unreadable"), prov)
    if report is None:
        return Section(tool)
    verdict = str(obj.get("verdict", "unknown")).strip().lower()
    findings = obj.get("findings")
    extra = ""
    if isinstance(findings, list) and findings:
        extra = f", {len(findings)} finding(s)"
    elif isinstance(findings, dict):
        # GhostWatch's writer ships findings as a dict of lists
        # ({"missing_bundle_file": [...], "stale_symbols": [...]}).
        found = sum(len(v) for v in findings.values()
                    if isinstance(v, list))
        if found:
            extra = f", {found} finding(s)"
    # GhostWatch's report carries its run time as "checked_at".
    when, kind = _when(report, obj.get("generated_at")
                       or obj.get("checked_at") or obj.get("at"))
    if verdict == "fresh":
        section = _tag(Section(tool, OK, f"verdict: fresh{extra}",
                               _rel(report, project), when, kind), prov)
        return _apply_evidence(section, obj)
    state = STALE
    section = _tag(Section(tool, state, f"verdict: {verdict}{extra}",
                           _rel(report, project), when, kind,
                           reason=f"Watch verdict: {verdict}"), prov)
    return _apply_evidence(section, obj)


# ---------------------------------------------------------------- Approve

_DECISION_WORDS = ("decid", "approv", "deni", "reject")


def _record_risk(record: dict) -> str | None:
    """Risk value for one request record, or None.

    GhostApprove's real record shape nests the request content:
    {"id", "hash", "ingested_at", "content": {"risk": ...}}. A flat
    top-level "risk" (the suite fixture shape) is honoured too. Only
    the top level was read before, so risks on real stores were never
    named in the pending summary.
    """
    risk = record.get("risk")
    if risk:
        return str(risk)
    content = record.get("content")
    if isinstance(content, dict) and content.get("risk"):
        return str(content["risk"])
    return None


def _store_facts(store: Path):
    """(records, pending_ids, newest) for one store, or None.

    None means the directory holds neither request records nor a
    ledger, so it is not treated as a store at all. Decisions are
    resolved against the store's own ledger only.
    """
    requests_dir = store / "requests"
    records: dict[str, dict] = {}
    if requests_dir.is_dir():
        for entry in sorted(requests_dir.iterdir()):
            if entry.suffix != ".json" or not entry.is_file():
                continue
            obj, _err = _read_json(entry)
            rid = entry.stem
            if isinstance(obj, dict) and isinstance(obj.get("id"), str):
                rid = obj["id"]
            records[rid] = obj if isinstance(obj, dict) else {}
    ledger = store / "ledger.jsonl"
    if not records and not ledger.is_file():
        return None
    decided: set[str] = set()
    newest = _mtime(store)
    if ledger.is_file():
        newest = max(newest, _mtime(ledger))
        rows, _bad, _err = _read_jsonl(ledger)
        for row in rows:
            rid = row.get("id") or row.get("request_id")
            marker = " ".join(str(row.get(k, "")) for k in
                              ("event", "type", "decision", "action_taken"))
            if rid and any(w in marker.lower() for w in _DECISION_WORDS):
                decided.add(str(rid))
    pending = [rid for rid in records if rid not in decided]
    return records, pending, newest


def _pending_risks(records: dict, pending: list) -> list[str]:
    risks = []
    for rid in pending:
        risk = _record_risk(records[rid])
        if risk:
            risks.append(risk)
    return risks


def _approve_store_section(store: Path, label_path: Path) -> Section:
    """Section for one Approve store directory."""
    tool = "GhostApprove"
    facts = _store_facts(store)
    if facts is None:
        return Section(tool)
    records, pending, newest = facts
    source = str(store if label_path == store else
                 store.relative_to(label_path)
                 if store.is_relative_to(label_path) else store)
    if pending:
        summary = f"{len(pending)} pending of {len(records)} request(s)"
        risks = _pending_risks(records, pending)
        if risks:
            summary += f" (risk: {', '.join(sorted(set(risks)))})"
        return Section(tool, ATTENTION, summary, source, newest, "mtime",
                       reason=f"Approve: {len(pending)} request(s) pending")
    summary = f"queue clear ({len(records)} request(s), all decided)"
    return Section(tool, OK, summary, source, newest, "mtime")


def _find_store_dirs(project: Path) -> list[Path]:
    """Directories named .ghostapprove under a project, bounded walk.

    Same discipline as find_candidates: depth cap, skipped directory
    names, symlinks not followed or read, and stores are not descended
    into. The project's root store is not returned: callers check it
    first and it takes precedence.
    """
    found: list[Path] = []
    for dirpath, dirnames, _filenames in os.walk(project,
                                                  followlinks=False):
        depth = len(Path(dirpath).relative_to(project).parts)
        dirnames[:] = [d for d in dirnames
                       if d not in SKIP_DIRS and depth < MAX_DEPTH]
        if depth >= MAX_DEPTH:
            dirnames[:] = []
            continue
        if ".ghostapprove" in dirnames:
            dirnames.remove(".ghostapprove")
            if depth > 0:
                cand = Path(dirpath) / ".ghostapprove"
                if not cand.is_symlink():
                    found.append(cand)
    found.sort()
    return found


def _aggregate_stores(nested: list, project: Path) -> Section:
    """One section over several stores of one provenance class."""
    tool = "GhostApprove"
    total = 0
    pending_count = 0
    risks: list[str] = []
    newest = None
    for _cand, (records, pending, when) in nested:
        total += len(records)
        pending_count += len(pending)
        risks += _pending_risks(records, pending)
        newest = when if newest is None else max(newest, when)
    sources = [_rel(cand, project) for cand, _facts in nested]
    if len(sources) > 3:
        source = ", ".join(sources[:2]) + f" (+{len(sources) - 2} more)"
    else:
        source = ", ".join(sources)
    if pending_count:
        summary = (f"{pending_count} pending of {total} request(s) "
                   f"across {len(nested)} nested store(s)")
        if risks:
            summary += f" (risk: {', '.join(sorted(set(risks)))})"
        return Section(tool, ATTENTION, summary, source, newest, "mtime",
                       reason=f"Approve: {pending_count} request(s) pending")
    summary = (f"queue clear ({total} request(s), all decided) "
               f"across {len(nested)} nested store(s)")
    return Section(tool, OK, summary, source, newest, "mtime")


def _fixture_store_note(section: Section, fixture_stores: int) -> Section:
    """Name fixture stores that were kept out of a live section, so
    their exclusion is visible on the card rather than silent."""
    if fixture_stores and section.state != ABSENT:
        section.summary += (f"; {fixture_stores} fixture store(s) not "
                            f"counted as live evidence")
    return section


def approve_section(project: Path) -> Section:
    """GhostApprove row: root store first, else nested store(s)."""
    nested_live: list = []
    nested_fixture: list = []
    for cand in _find_store_dirs(project):
        facts = _store_facts(cand)
        if facts is None:
            continue
        if _provenance(cand, project) == "fixture":
            nested_fixture.append((cand, facts))
        else:
            nested_live.append((cand, facts))
    store = project / ".ghostapprove"
    if store.is_dir():
        return _fixture_store_note(_approve_store_section(store, project),
                                   len(nested_fixture))
    if nested_live:
        if len(nested_live) == 1:
            section = _approve_store_section(nested_live[0][0], project)
        else:
            section = _aggregate_stores(nested_live, project)
        return _fixture_store_note(section, len(nested_fixture))
    if nested_fixture:
        if len(nested_fixture) == 1:
            section = _approve_store_section(nested_fixture[0][0], project)
        else:
            section = _aggregate_stores(nested_fixture, project)
        return _tag(section, "fixture")
    return Section("GhostApprove")


def project_store_section(store: Path) -> Section:
    """GhostApprove row for a shared store passed with --approve-store."""
    """Section for a shared store passed with --approve-store."""
    if store.is_dir():
        return _approve_store_section(store, store)
    section = Section("GhostApprove")
    section.summary = "no report found (store path given but not a directory)"
    return section


# ---------------------------------------------------------------- Handoff

def _is_handoff_pack(obj) -> bool:
    if not isinstance(obj, dict):
        return False
    if obj.get("tool") == "ghosthandoff":
        return True
    return "open_loops" in obj and "session_window" in obj


def handoff_section(project: Path) -> Section:
    """GhostHandoff row: newest handoff pack (a snapshot, not a verdict)."""
    tool = "GhostHandoff"
    report, obj, corrupt, corrupt_err, prov = pick_report_two_pass(
        project, "handoff.json", _is_handoff_pack)
    if report is None and corrupt is not None:
        return _tag(Section(tool, UNREADABLE,
                            f"pack found but unreadable ({corrupt_err})",
                            _rel(corrupt, project),
                            reason="Handoff pack unreadable"), prov)
    if report is None:
        return Section(tool, ABSENT, "no handoff pack found")
    loops = obj.get("open_loops")
    loops = loops if isinstance(loops, list) else []
    steps = obj.get("next_steps")
    steps = steps if isinstance(steps, list) else []
    git = obj.get("git") if isinstance(obj.get("git"), dict) else {}
    if git.get("available"):
        branch = git.get("branch") or \
            ("detached HEAD" if git.get("detached") else "unknown branch")
        head = git.get("head_short")
        state = f"{branch}@{head}" if head else str(branch)
        status = git.get("status") if isinstance(git.get("status"),
                                                  dict) else {}
        dirty = 0
        for key in ("staged", "unstaged", "untracked"):
            value = status.get(f"{key}_count", status.get(key))
            if _is_int(value):
                dirty += value
            elif isinstance(value, list):
                dirty += len(value)
        summary = (f"session pack: {state}, {dirty} uncommitted "
                   f"change(s), {len(loops)} open loop(s), "
                   f"{len(steps)} next step(s)")
    else:
        summary = (f"session pack: git state not recorded, "
                   f"{len(loops)} open loop(s), {len(steps)} next step(s)")
    when, kind = _when(report, obj.get("generated_at"))
    # A handoff pack is a snapshot, not a verdict: GhostHandoff has no
    # pass/fail vocabulary, so a parseable pack is an ok row whose
    # summary states the open loops exactly. The failing evidence a
    # pack quotes (a Verify report, a pytest cache) is read directly
    # by its own adapter when that file is discoverable.
    return _tag(Section(tool, OK, summary, _rel(report, project),
                        when, kind), prov)


# ------------------------------------------------- shared manifest packs

def _pick_pack_manifest(project: Path, shape, companion: str) -> tuple:
    """Find a tool pack whose manifest is a bare `manifest.json`.

    GhostLogs and GhostData packs share that file name with GhostSlice
    bundles and each other, so a manifest is claimed only by parsed
    shape (see the shape functions). A corrupt manifest is claimed
    only when the pack's companion file (INCIDENT.md for GhostLogs,
    PROMPT.md for GhostData; both packs always ship the pair) sits
    beside it: a corrupt manifest without the companion belongs to
    some other tool's pack and is not this adapter's row to report.
    Live paths are tried before fixture/example paths, as everywhere.
    Returns (path, obj, corrupt_path, corrupt_err, provenance).
    """
    candidates = find_candidates(project, "manifest.json")
    for prov in ("live", "fixture"):
        corrupt_path = corrupt_err = None
        for cand in candidates:
            if _provenance(cand, project) != prov:
                continue
            obj, err = _read_json(cand)
            if err is not None:
                if corrupt_path is None and \
                        (cand.parent / companion).is_file():
                    corrupt_path, corrupt_err = cand, err
                continue
            if not isinstance(obj, dict):
                if corrupt_path is None and \
                        (cand.parent / companion).is_file():
                    corrupt_path, corrupt_err = cand, "not a JSON object"
                continue
            if shape(obj):
                return cand, obj, None, None, prov
        if corrupt_path is not None:
            return None, None, corrupt_path, corrupt_err, prov
    return None, None, None, None, "live"


# ---------------------------------------------------------------- Logs

def _is_logs_manifest(obj) -> bool:
    if not isinstance(obj, dict):
        return False
    if obj.get("tool") == "ghostlogs":
        return True
    counts = obj.get("counts")
    return isinstance(counts, dict) and "total_lines" in counts \
        and "reconciles" in counts


def logs_section(project: Path) -> Section:
    """GhostLogs row: incident pack claimed by manifest shape + INCIDENT.md."""
    tool = "GhostLogs"
    report, obj, corrupt, corrupt_err, prov = _pick_pack_manifest(
        project, _is_logs_manifest, "INCIDENT.md")
    if report is None and corrupt is not None:
        return _tag(Section(tool, UNREADABLE,
                            f"manifest found but unreadable "
                            f"({corrupt_err})",
                            _rel(corrupt, project),
                            reason="Logs manifest unreadable"), prov)
    if report is None:
        return Section(tool, ABSENT, "no incident pack found")
    counts = obj.get("counts") if isinstance(obj.get("counts"), dict) \
        else {}
    total = counts.get("total_lines")
    summary = f"incident pack: {_fmt_int(total)} line(s)"
    kept, collapsed, dropped = (counts.get("kept"), counts.get("collapsed"),
                                counts.get("dropped"))
    if None not in (kept, collapsed, dropped):
        summary += (f" -> {_fmt_int(kept)} kept, "
                    f"{_fmt_int(collapsed)} collapsed, "
                    f"{_fmt_int(dropped)} dropped")
    windows = obj.get("windows") if isinstance(obj.get("windows"), dict) \
        else {}
    if windows.get("matched") is not None:
        summary += (f"; {_fmt_int(windows.get('emitted'))} of "
                    f"{_fmt_int(windows.get('matched'))} error window(s)")
    est, budget = obj.get("pack_estimated_tokens"), obj.get("budget_tokens")
    if est is not None and budget is not None:
        summary += (f"; est. {_fmt_int(est)} of {_fmt_int(budget)} "
                    f"budget tokens")
    tier = obj.get("budget_tier")
    if tier:
        summary += f" (tier {tier})"
    redaction = obj.get("redaction") if isinstance(obj.get("redaction"),
                                                   dict) else {}
    if redaction.get("total"):
        summary += f"; {_fmt_int(redaction['total'])} redaction(s)"
    state, reason = OK, ""
    if obj.get("over_budget") is True:
        state = ATTENTION
        reason = "Logs incident pack shipped over its token budget"
        summary += "; OVER BUDGET"
    elif counts.get("reconciles") is False:
        state = ATTENTION
        reason = "Logs pack line counts do not reconcile"
    when, kind = _when(report, obj.get("generated_at"))
    return _tag(Section(tool, state, summary, _rel(report, project),
                        when, kind, reason), prov)


# ---------------------------------------------------------------- Deps

def _is_deps_manifest(obj) -> bool:
    if not isinstance(obj, dict):
        return False
    if obj.get("tool") == "ghostdeps":
        return True
    counts = obj.get("counts")
    return isinstance(counts, dict) and "imported_not_declared" in counts \
        and "declared" in counts


def deps_section(project: Path) -> Section:
    """GhostDeps row: newest deps manifest; undeclared imports are Attention."""
    tool = "GhostDeps"
    report, obj, corrupt, corrupt_err, prov = pick_report_two_pass(
        project, "deps-manifest.json", _is_deps_manifest)
    if report is None and corrupt is not None:
        return _tag(Section(tool, UNREADABLE,
                            f"manifest found but unreadable "
                            f"({corrupt_err})",
                            _rel(corrupt, project),
                            reason="Deps manifest unreadable"), prov)
    if report is None:
        return Section(tool, ABSENT, "no deps pack found")
    counts = obj.get("counts") if isinstance(obj.get("counts"), dict) \
        else {}
    declared = counts.get("declared")
    used = counts.get("declared_and_used")
    not_imported = counts.get("declared_not_imported")
    not_declared = counts.get("imported_not_declared")
    summary = f"{_fmt_int(declared)} declared"
    detail = []
    if used is not None:
        detail.append(f"{_fmt_int(used)} imported")
    if not_imported is not None:
        detail.append(f"{_fmt_int(not_imported)} declared not imported")
    if detail:
        summary += " (" + ", ".join(detail) + ")"
    summary += f", {_fmt_int(not_declared)} imported not declared"
    pins = counts.get("pins_recorded")
    transitive = counts.get("pins_transitive_recorded")
    if _is_int(pins) or _is_int(transitive):
        pin_total = (pins if _is_int(pins) else 0) + \
            (transitive if _is_int(transitive) else 0)
        summary += f"; {_fmt_int(pin_total)} pin(s) recorded"
    state, reason = OK, ""
    # GhostDeps' own notes call declared-not-imported "a lead for a
    # human, not a verdict", so it is stated but never drives the
    # column. Code importing a package no manifest declares is the
    # factual gap (the Ledger loop-warning analogue) and does.
    if _is_int(not_declared) and not_declared > 0:
        state = ATTENTION
        reason = (f"Deps: {not_declared} imported package(s) "
                  f"not declared")
    when, kind = _when(report, obj.get("generated_at"))
    return _tag(Section(tool, state, summary, _rel(report, project),
                        when, kind, reason), prov)


# ---------------------------------------------------------------- Data

def _is_data_manifest(obj) -> bool:
    if not isinstance(obj, dict):
        return False
    if obj.get("tool") == "ghostdata":
        return True
    counts = obj.get("counts")
    return isinstance(counts, dict) and "rows_parsed" in counts \
        and isinstance(obj.get("columns"), list)


def data_section(project: Path) -> Section:
    """GhostData row: data pack claimed by manifest shape + PROMPT.md."""
    tool = "GhostData"
    report, obj, corrupt, corrupt_err, prov = _pick_pack_manifest(
        project, _is_data_manifest, "PROMPT.md")
    if report is None and corrupt is not None:
        return _tag(Section(tool, UNREADABLE,
                            f"manifest found but unreadable "
                            f"({corrupt_err})",
                            _rel(corrupt, project),
                            reason="Data manifest unreadable"), prov)
    if report is None:
        return Section(tool, ABSENT, "no data pack found")
    counts = obj.get("counts") if isinstance(obj.get("counts"), dict) \
        else {}
    source = obj.get("source") if isinstance(obj.get("source"), dict) \
        else {}
    columns = obj.get("columns") if isinstance(obj.get("columns"), list) \
        else []
    redaction = obj.get("redaction") if isinstance(obj.get("redaction"),
                                                    dict) else {}
    redacted = redaction.get("columns")
    n_redacted = len(redacted) if isinstance(redacted, list) else \
        sum(1 for c in columns if isinstance(c, dict) and c.get("redacted"))
    parsed = counts.get("rows_parsed")
    total = counts.get("rows_total", parsed)
    malformed = counts.get("rows_malformed")
    name = source.get("file", "data file")
    fmt = source.get("format")
    summary = f"{name} ({fmt}): " if fmt else f"{name}: "
    summary += (f"{_fmt_int(parsed)} of {_fmt_int(total)} row(s) parsed, "
                f"{_fmt_int(malformed)} malformed, "
                f"{len(columns)} column(s), "
                f"{n_redacted} redacted column(s)")
    if redaction.get("enabled") is False:
        summary += "; redaction disabled for this pack"
    state, reason = OK, ""
    if _is_int(malformed) and malformed > 0:
        state = ATTENTION
        reason = f"Data pack: {malformed} malformed row(s) in the source"
    when, kind = _when(report, obj.get("generated_at"))
    return _tag(Section(tool, state, summary, _rel(report, project),
                        when, kind, reason), prov)
