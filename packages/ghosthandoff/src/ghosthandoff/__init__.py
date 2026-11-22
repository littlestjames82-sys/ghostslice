"""GhostHandoff: session handoff packs drafted from repo facts only.

Propose-only. Builds HANDOFF.md + handoff.json describing a project's
state at stop time (git state, session changes, verification status,
open loops, next steps). Never commits, never sends, never edits the
project it describes, never runs project code. Stdlib only.

Quick use (see README.md for the full guide)::

    ghosthandoff pack <project> [-o <dir>] [--since <when>] [--base <ref>]
    ghosthandoff show <pack-dir>
    ghosthandoff mcp

Every fact in the pack names its source (for example ``git status``,
a report file path, or the marker scan), and verification status is
quoted from report files on disk with their age, never re-run.
"""

__version__ = "0.1.0"
TOOL = "ghosthandoff"
