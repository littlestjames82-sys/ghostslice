"""Board model: the data every renderer (HTML, text, JSON) shares.

A Section is one tool's latest word on one project. A ProjectBoard is
one project plus its sections plus the column the classifier chose and
the reason it chose it. Reasons are always carried in the model so the
board can print why every card sits where it sits.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

# Section states
OK = "ok"
ATTENTION = "attention"
STALE = "stale"
ABSENT = "absent"
UNREADABLE = "unreadable"

# Board columns
VERIFIED = "verified"
COL_ATTENTION = "attention"
COL_STALE = "stale"

COLUMNS = (VERIFIED, COL_ATTENTION, COL_STALE)

# Verification levels (shared evidence contract, EVIDENCE_CONTRACT
# DRAFT v0.1): how strong a report's evidence is, weakest first.
# A level is only ever shown when the report itself states one;
# absence means "not stated", never a guessed level.
LEVEL_NONE = "none"
LEVEL_STATIC = "static-analysis"
LEVEL_TESTS = "tests-executed"
LEVEL_LIVE_AGENT = "live-agent"

VERIFICATION_LEVELS = (LEVEL_NONE, LEVEL_STATIC, LEVEL_TESTS,
                       LEVEL_LIVE_AGENT)
LEVEL_RANK = {level: rank for rank, level in enumerate(VERIFICATION_LEVELS)}

# Plain words for one line of board legend, so a reader who never
# saw the contract still understands the levels.
LEVEL_PLAIN = {
    LEVEL_NONE: "no usable evidence",
    LEVEL_STATIC: "static analysis only (no code executed, no agent ran)",
    LEVEL_TESTS: "the project's own tests were actually run",
    LEVEL_LIVE_AGENT: "a real agent attempted the real task",
}

# Provenance values a section can carry. "live" is the project's own
# state; "fixture" and "sample" are shipped material: shown and
# labelled, but they never place a project or feed its freshness
# clock.
NON_LIVE_PROVENANCE = ("fixture", "sample")


def strongest_level(sections) -> str | None:
    """Strongest stated verification level among sections, or None.

    Only levels from the contract enum count; an unrecognized value
    is not a level and never wins. Returns None when no section
    states a level at all.
    """
    stated = [s.verification_level for s in sections
              if s.verification_level in LEVEL_RANK]
    if not stated:
        return None
    return max(stated, key=LEVEL_RANK.__getitem__)


@dataclass
class Section:
    """One tool's latest word on one project: a single board row."""

    tool: str                      # display name, e.g. "GhostVerify"
    state: str = ABSENT
    summary: str = "no report found"
    source: str | None = None      # path of the report used, as shown
    when: datetime | None = None   # report time (aware, UTC)
    time_kind: str = ""            # "reported" | "mtime" | ""
    reason: str = ""               # why attention/stale, when applicable
    # Informational history context (adapters with a .jsonl history):
    # how the latest entry compares with what came before it. Built
    # only from fields the adapter already recognizes. A trend never
    # drives a column: the latest report alone places the project.
    trend: str = ""
    # "live": a report the project itself produced in normal use.
    # "fixture": a report shipped inside the project as test/example
    # material (under tests/, fixtures/, examples/, ...). "sample": a
    # report that declares itself a sample (its own provenance field
    # says so), wherever it sits on disk. Fixture and sample sections
    # are shown on the card, labelled, but never drive the project's
    # column: they are not the project's live state.
    provenance: str = "live"
    # Evidence-contract fields, carried only when the report itself
    # states them. None means the report did not say; renderers show
    # a stated level and never invent one for an unstated report.
    verification_level: str | None = None
    tool_version: str | None = None

    def to_dict(self) -> dict:
        """Plain-dict form used by the JSON renderer."""
        return {
            "tool": self.tool,
            "state": self.state,
            "summary": self.summary,
            "source": self.source,
            "when": self.when.isoformat() if self.when else None,
            "time_kind": self.time_kind,
            "reason": self.reason,
            "trend": self.trend,
            "provenance": self.provenance,
            "verification_level": self.verification_level,
            "tool_version": self.tool_version,
        }


@dataclass
class ProjectBoard:
    """One project card: its sections, its column, and why it is there."""

    name: str
    path: str
    sections: list[Section] = field(default_factory=list)
    column: str = COL_STALE
    column_reason: str = "no reports found"
    newest: datetime | None = None

    def to_dict(self) -> dict:
        """Plain-dict form used by the JSON renderer."""
        return {
            "name": self.name,
            "path": self.path,
            "column": self.column,
            "column_reason": self.column_reason,
            "newest": self.newest.isoformat() if self.newest else None,
            "sections": [s.to_dict() for s in self.sections],
        }
