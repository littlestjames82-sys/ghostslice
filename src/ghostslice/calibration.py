"""Per-family token calibration report (v0.10).

The transparency surface for the estimator's calibration: for each
language family present in a project, show file count, raw
characters, the uncalibrated (v1 raw split) estimate, the calibrated
estimate the rest of GhostSlice actually uses, the implied
characters-per-token of the calibrated estimate, and the factor and
published-anchor target behind it (see tokens.py for the factor
table and its evidence basis). All numbers are estimates.
"""
from __future__ import annotations

from pathlib import Path

from .profile import Profile
from .scanner import scan
from .textio import read_text as _gs_read_text
from .tokens import (FAMILY_CALIBRATION, METHOD, estimate_tokens,
                     estimate_tokens_raw, family_for)


def calibrate_project(path, profile: Profile | None = None) -> dict:
    """Group a project's scan by calibration family and compare the
    raw vs calibrated estimator on the same texts the scanner used,
    so this report always agrees with `ghostslice scan` totals."""
    profile = profile or Profile()
    matcher = profile.is_ignored if profile.path else None
    result = scan(path, ignore_matcher=matcher)
    rows: dict[str, dict] = {}
    for entry in result.files:
        try:
            text = _gs_read_text(entry.abspath)
        except OSError:
            continue
        fam = family_for(entry.language, text)
        factor, target = FAMILY_CALIBRATION[fam]
        row = rows.setdefault(fam, {
            "family": fam, "files": 0, "chars": 0,
            "raw_tokens": 0, "calibrated_tokens": 0,
            "factor": factor, "target_chars_per_token": target or None,
        })
        row["files"] += 1
        row["chars"] += len(text)
        row["raw_tokens"] += estimate_tokens_raw(text)
        row["calibrated_tokens"] += estimate_tokens(text, entry.language)
    out_rows = []
    for fam in sorted(rows, key=lambda f: -rows[f]["calibrated_tokens"]):
        row = rows[fam]
        cal = row["calibrated_tokens"]
        row["implied_chars_per_token"] = round(row["chars"] / cal, 2) if cal else 0.0
        out_rows.append(row)
    totals = {
        "files": sum(r["files"] for r in out_rows),
        "chars": sum(r["chars"] for r in out_rows),
        "raw_tokens": sum(r["raw_tokens"] for r in out_rows),
        "calibrated_tokens": sum(r["calibrated_tokens"] for r in out_rows),
    }
    totals["implied_chars_per_token"] = (
        round(totals["chars"] / totals["calibrated_tokens"], 2)
        if totals["calibrated_tokens"] else 0.0)
    return {
        "root": result.root,
        "token_method": METHOD,
        "families": out_rows,
        "totals": totals,
    }
