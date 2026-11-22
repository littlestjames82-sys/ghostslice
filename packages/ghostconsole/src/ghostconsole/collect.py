"""Collection: run every adapter over every project, then classify.

Classification precedence (printed on every card, see PLAN.md):
attention beats stale beats verified. Age staleness uses the newest
live section time in the project, so one fresh report keeps a project
out of the stale column even when older tools have gone quiet.
Sections whose provenance is "fixture" (reports shipped under tests/,
fixtures/, examples/ inside the project) are displayed on the card,
labelled, but never place the project: they describe the project's
test material, not the project.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import adapters
from .model import (ABSENT, ATTENTION, COL_ATTENTION, COL_STALE,
                    LEVEL_LIVE_AGENT, LEVEL_NONE, LEVEL_PLAIN, LEVEL_STATIC,
                    LEVEL_TESTS, STALE, UNREADABLE, VERIFIED, ProjectBoard,
                    Section, strongest_level)

ADAPTERS = (
    adapters.slice_section,
    adapters.verify_section,
    adapters.bench_section,
    adapters.workflow_section,
    adapters.scope_section,
    adapters.ledger_section,
    adapters.watch_section,
    adapters.approve_section,
    adapters.handoff_section,
    adapters.logs_section,
    adapters.deps_section,
    adapters.data_section,
)


def collect_project(path: Path) -> ProjectBoard:
    """Run every adapter over one project (no classification yet).

    A path that is not a directory still returns a board: a single
    unreadable section, so the problem is shown on the board instead
    of raising or being dropped.
    """
    project = Path(path)
    board = ProjectBoard(name=project.name or str(project),
                         path=str(project))
    if not project.is_dir():
        section = Section("Projects", UNREADABLE,
                          "project path is not a directory", str(project),
                          reason="project path not found")
        board.sections = [section]
        board.column = COL_ATTENTION
        board.column_reason = "project path is not a directory"
        return board
    board.sections = [adapter(project) for adapter in ADAPTERS]
    # Freshness is a property of the project's live evidence. A fresh
    # fixture report must not make a quiet project look current, so
    # only live sections feed the newest-evidence clock.
    times = [s.when for s in board.sections
             if s.when is not None and s.provenance == "live"]
    board.newest = max(times) if times else None
    return board


def classify(board: ProjectBoard, now: datetime,
             stale_days: int) -> ProjectBoard:
    """Place a board in exactly one column and record the reason.

    Precedence: any live attention/unreadable section wins, then any
    live stale section, then age staleness of the newest live
    evidence, otherwise Verified. The chosen ``column_reason`` is
    always set, so every card can print why it sits where it sits.
    """
    # Only live sections place a project. Fixture/example and sample
    # sections are evidence about material the project ships (or a
    # report that declares itself a sample), not about the project's
    # live state, so they never drive a column in either direction.
    present = [s for s in board.sections
               if s.state != ABSENT and s.provenance == "live"]
    fixture = [s for s in board.sections
               if s.state != ABSENT and s.provenance == "fixture"]
    sample = [s for s in board.sections
              if s.state != ABSENT and s.provenance == "sample"]
    for section in present:
        if section.state in (ATTENTION, UNREADABLE):
            board.column = COL_ATTENTION
            board.column_reason = section.reason or \
                f"{section.tool} needs attention"
            return board
    for section in present:
        if section.state == STALE:
            board.column = COL_STALE
            board.column_reason = section.reason or \
                f"{section.tool} reports stale"
            return board
    if not present:
        board.column = COL_STALE
        untrusted = []
        if fixture:
            untrusted.append(f"{len(fixture)} fixture/example report(s)")
        if sample:
            untrusted.append(f"{len(sample)} sample report(s)")
        if untrusted:
            board.column_reason = (
                "no live reports found (" + ", ".join(untrusted) +
                " on the card, labelled, not counted)")
        else:
            board.column_reason = "no reports found"
        return board
    if board.newest is not None and \
            now - board.newest > timedelta(days=stale_days):
        age = (now - board.newest).days
        board.column = COL_STALE
        board.column_reason = (f"newest report is {age} day(s) old "
                               f"(stale window {stale_days} day(s))")
        return board
    board.column = VERIFIED
    board.column_reason = _verified_reason(board, present, stale_days)
    return board


def _verified_reason(board: ProjectBoard, present: list[Section],
                     stale_days: int) -> str:
    """Why a project sits in Verified, stated without overclaiming.

    The reason always names the strongest verification level among
    the project's LIVE sections (fixture/sample evidence never feeds
    this), says plainly when that level is only static analysis, says
    "not stated" when no live report states a level, and counts how
    many of the board's tool rows have no live report at all, so a
    Verified card built on one of eleven checks reads that way.
    """
    reason = ("latest reports ok and inside the "
              f"{stale_days} day stale window")
    strongest = strongest_level(present)
    if strongest is None:
        reason += "; verification level not stated by any live report"
    elif strongest == LEVEL_STATIC:
        reason += ("; strongest verification level: static-analysis "
                   "(static only: no tests executed, no live run)")
    elif strongest == LEVEL_TESTS:
        reason += ("; strongest verification level: tests-executed "
                   f"({LEVEL_PLAIN[LEVEL_TESTS]})")
    elif strongest == LEVEL_LIVE_AGENT:
        reason += ("; strongest verification level: live-agent "
                   f"({LEVEL_PLAIN[LEVEL_LIVE_AGENT]})")
    else:  # LEVEL_NONE stated, and nothing stronger
        reason += ("; strongest verification level: none "
                   f"({LEVEL_PLAIN[LEVEL_NONE]})")
    missing = len(board.sections) - len(present)
    reason += (f"; {missing} of {len(board.sections)} checks missing "
               f"(no live report)")
    return reason


def collect(projects: list[Path], stale_days: int = 7,
            approve_store: Path | None = None,
            now: datetime | None = None) -> dict:
    """Collect and classify every project into the shared board model.

    The returned dict carries ``generated_at``, ``stale_days``, the
    JSON-ready ``projects`` list, and the ``boards`` objects the HTML
    and text renderers consume. ``approve_store``, when given, adds
    one extra board for that shared GhostApprove store. ``now`` is
    injectable for tests; it defaults to the current UTC time.
    """
    now = now or datetime.now(timezone.utc)
    boards = [classify(collect_project(p), now, stale_days)
              for p in projects]
    if approve_store is not None:
        store_board = ProjectBoard(
            name=f"GhostApprove store ({approve_store.name})",
            path=str(approve_store))
        store_board.sections = [adapters.project_store_section(approve_store)]
        present = [s for s in store_board.sections if s.when is not None]
        store_board.newest = present[0].when if present else None
        boards.append(classify(store_board, now, stale_days))
    return {
        "generated_at": now.isoformat(),
        "stale_days": stale_days,
        "projects": [b.to_dict() for b in boards],
        "boards": boards,
    }


def discover_root(root: Path) -> list[Path]:
    """Every immediate subdirectory of root is a project."""
    root = Path(root)
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir()
                  if p.is_dir() and not p.name.startswith("."))
