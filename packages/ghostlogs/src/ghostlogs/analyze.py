"""Streaming single-pass log analysis.

The source file is read in binary mode, one line at a time; the
whole file is never loaded at once. Retained state is bounded by
design: capped window line storage, the duplicate signature table,
the pending before-context buffer (window_before lines), and
counters. What those bounds mean is stated in IMPLEMENTATION_A.md
and in every manifest's limits list.

Line accounting is exact and partitioned. Every source line ends up
in exactly one place:
- a window line (stored, or counted as window store overflow), or
- duplicate accounting (a duplicate group member, or a singleton).
Before-context lines are held in the pending buffer and only enter
duplicate accounting once no window has claimed them, so no line is
ever counted twice.
"""
from __future__ import annotations

import hashlib
import re
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from functools import lru_cache

from .patterns import (NEEDLE_RE, Pattern, find_timestamp, hour_bucket,
                       is_continuation)
from .tokens import estimate_tokens

MAX_STORED_WINDOW_LINES = 100_000  # across all windows, per run
TRACE_ABSORB_CAP = 200            # continuation lines per window


@dataclass
class Window:
    """One error window: the lines claimed around a pattern match.

    `stored` holds the lines kept for the pack (bounded by the store
    cap); `overflow` counts claimed lines past that cap. `repeats`
    and `repeat_ranges` record consecutive same-signature lines that
    were collapsed in place, and `line_counts` keeps the exact
    per-signature occurrence count for every claimed line.
    """
    start_line: int
    end_line: int = 0
    match_line: int = 0
    pattern_id: str = ""
    severity: int = 0
    matches: list = field(default_factory=list)   # [{line, pattern}]
    stored: list = field(default_factory=list)    # [(line_no, text)]
    overflow: int = 0
    repeats: int = 0          # consecutive same-signature lines collapsed in place
    repeat_ranges: list = field(default_factory=list)  # [(first, last)] per run
    match_signatures: set = field(default_factory=set)
    last_sig: str | None = None
    # Per-signature occurrence accounting for EVERY line this window
    # claims (stored, collapsed in place, or overflow): signature ->
    # {exemplar, occurrences, exact_copies, first_line, last_line}.
    # Window lines never enter the routine duplicate table, so without
    # this a repeated line inside a window (a repeated ERROR, say) had
    # its true count stated nowhere. See FIX_REPORT.md, defect D1.
    line_counts: dict = field(default_factory=dict)

    @property
    def total_lines(self) -> int:
        return self.end_line - self.start_line + 1


@dataclass
class DupGroup:
    """One duplicate group: lines sharing a near-duplicate signature.

    `exemplar` is the first occurrence, verbatim. `occurrences` is the
    exact total; `exact_copies` is how many of those were
    byte-identical to the exemplar, so over-grouping stays visible.
    """
    signature: str
    exemplar: str
    exemplar_line: int
    first_line: int
    last_line: int
    occurrences: int = 0
    exact_copies: int = 0


@dataclass
class Analysis:
    """The result of one streaming pass over a source log.

    Carries the source identity (path, bytes, sha256), the timeline
    anchors, the error windows, and the duplicate table. Every source
    line is accounted for exactly once across windows and duplicate
    accounting; pack.py turns that partition into the reconciled
    kept / collapsed / dropped counts.
    """
    source_path: str
    source_bytes: int
    source_sha256: str
    total_lines: int
    estimated_tokens_in: int
    first_line_text: str | None
    last_line_text: str | None
    first_timestamp: tuple | None   # (text, line_no)
    last_timestamp: tuple | None
    windows: list
    dup_groups: dict                # signature -> DupGroup
    dup_accounted_lines: int
    suppressed_repeat_matches: int = 0
    # Signature of the duplicate group containing line 1 / the last
    # line, when that line went through duplicate accounting (else
    # None). pack.py uses these to avoid counting an anchor line
    # twice: once as kept (anchor) and once as a collapsed or
    # dropped member of its group.
    first_dup_signature: str | None = None
    last_dup_signature: str | None = None
    # Evidence overview tallies, counted once per source line at the
    # point matches are first computed (before any window claim,
    # suppression, or duplicate accounting), so they describe the
    # whole file exactly and never interact with the kept /
    # collapsed / dropped partition. See Analysis properties below.
    matched_lines: int = 0
    pattern_counts: dict = field(default_factory=dict)
    severity_counts: dict = field(default_factory=dict)
    timeline_buckets: list = field(default_factory=list)
    lines_with_timestamp: int = 0
    matched_lines_without_timestamp: int = 0

    @property
    def singleton_lines(self) -> int:
        return sum(1 for g in self.dup_groups.values() if g.occurrences == 1)

    @property
    def duplicate_groups(self) -> list:
        return [g for g in self.dup_groups.values() if g.occurrences >= 2]

    @property
    def window_duplicate_groups(self) -> list:
        """Duplicate groups for lines claimed by error windows,
        aggregated across windows by signature. These lines are
        accounted separately from `duplicate_groups` (routine lines)
        because window lines follow window accounting in the pack
        (kept / window-not-fitted), not exemplar accounting; merging
        the two tables would double-count. Only signatures with at
        least two occurrences are groups; the rest are singletons
        inside their window and need no count statement."""
        merged: dict[str, DupGroup] = {}
        for win in self.windows:
            for sig, st in win.line_counts.items():
                group = merged.get(sig)
                if group is None:
                    merged[sig] = DupGroup(
                        sig, st["exemplar"], st["first_line"],
                        st["first_line"], st["last_line"],
                        st["occurrences"], st["exact_copies"])
                else:
                    group.occurrences += st["occurrences"]
                    group.exact_copies += st["exact_copies"]
                    group.last_line = max(group.last_line, st["last_line"])
                    if st["first_line"] < group.first_line:
                        group.first_line = st["first_line"]
                        group.exemplar = st["exemplar"]
                        group.exemplar_line = st["first_line"]
        return sorted(
            (g for g in merged.values() if g.occurrences >= 2),
            key=lambda g: (-g.occurrences, g.first_line))


_TS_IN_LINE = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?"
    r"|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}"
    r"\s+\d{2}:\d{2}:\d{2}\b")
_UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                      r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
_IP_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b")
_QUOTED_RE = re.compile(r'"[^"\n]*"|\'[^\'\n]*\'')
_HEXADDR_RE = re.compile(r"0x[0-9a-fA-F]+")
_HEX_RE = re.compile(r"\b(?=[0-9a-f]*\d)[0-9a-f]{12,}\b")
_NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?\b")
_WS_RE = re.compile(r"\s+")


@lru_cache(maxsize=65536)
def signature_of(text: str) -> str:
    """Near-duplicate signature: mask the parts of a line that vary
    between repetitions (timestamps, uuids, ips, quoted strings, hex
    ids, numbers) so repeats group together. Order matters: the
    timestamp and uuid masks run before the number mask. Memoised on
    the exact line text; identical lines always share a signature.
    The cheap substring guards skip masks that cannot apply."""
    s = _TS_IN_LINE.sub("<ts>", text)
    if s.count("-") >= 4:
        s = _UUID_RE.sub("<uuid>", s)
    s = _IP_RE.sub("<ip>", s)
    if '"' in s or "'" in s:
        s = _QUOTED_RE.sub("<str>", s)
    if "0x" in s:
        s = _HEXADDR_RE.sub("<hex>", s)
    s = _HEX_RE.sub("<hex>", s)
    s = _NUMBER_RE.sub("<n>", s)
    s = _WS_RE.sub(" ", s).strip()
    return s[:300]


def analyze(path, patterns: list[Pattern], window_before: int = 3,
            window_after: int = 5) -> Analysis:
    """Analyse one log file in a single streaming pass and return an Analysis.

    `patterns` is the full pattern list to match (built-ins plus any
    custom patterns). A match opens a window with `window_before`
    lines of context before it and `window_after` lines after it;
    stack-trace continuations are absorbed past the after-count, up
    to a per-window cap. The file is read line by line and is never
    modified, moved, or loaded whole.
    """
    path = Path(path)
    sha = hashlib.sha256()
    total_lines = 0
    total_bytes = 0
    est_in = 0
    first_line_text = None
    last_line_text = None
    first_ts = None
    last_ts = None

    windows: list[Window] = []
    current: Window | None = None
    planned_end = 0
    trace_absorbed = 0
    stored_total = 0

    groups: dict[str, DupGroup] = {}
    dup_accounted = 0
    pending: deque = deque()

    # Evidence overview accumulators (counts only; no line text is
    # retained, so the overview adds no redaction surface).
    ov_matched_lines = 0
    ov_pattern_counts: dict[str, int] = {}
    ov_severity_counts: dict[int, int] = {}
    ov_buckets: dict[str, dict] = {}
    ov_lines_with_ts = 0
    ov_matched_without_ts = 0

    gated = [p for p in patterns if p.builtin]
    ungated = [p for p in patterns if not p.builtin]

    windowed_signatures: set[str] = set()
    suppressed = 0

    def close_window(win: Window) -> None:
        windowed_signatures.update(win.match_signatures)
        windows.append(win)

    def claim_window_line(win: Window, no: int, text: str) -> None:
        nonlocal stored_total
        sig = signature_of(text)
        # Exact occurrence accounting for every claimed line, whether
        # it ends up stored, collapsed in place, or past the store
        # cap. This is counting only; it changes no claim decision.
        stat = win.line_counts.get(sig)
        if stat is None:
            win.line_counts[sig] = {
                "exemplar": text, "occurrences": 1, "exact_copies": 1,
                "first_line": no, "last_line": no}
        else:
            stat["occurrences"] += 1
            stat["last_line"] = no
            if text == stat["exemplar"]:
                stat["exact_copies"] += 1
        if sig == win.last_sig:
            # Consecutive repeat of the line above: collapse in
            # place. The stored line above represents it; pack.py
            # counts it as collapsed when the window is emitted and
            # as not fitted when it is not.
            win.repeats += 1
            if win.repeat_ranges and win.repeat_ranges[-1][1] == no - 1:
                win.repeat_ranges[-1] = (win.repeat_ranges[-1][0], no)
            else:
                win.repeat_ranges.append((no, no))
            win.end_line = no
            return
        win.last_sig = sig
        if stored_total < MAX_STORED_WINDOW_LINES:
            win.stored.append((no, text))
            stored_total += 1
        else:
            win.overflow += 1
        win.end_line = no

    first_dup_sig = None
    last_dup_sig = None
    last_dup_no = 0

    def dup_account(no: int, text: str) -> None:
        nonlocal dup_accounted, first_dup_sig, last_dup_sig, last_dup_no
        dup_accounted += 1
        sig = signature_of(text)
        if no == 1:
            first_dup_sig = sig
        if no > last_dup_no:
            last_dup_no, last_dup_sig = no, sig
        group = groups.get(sig)
        if group is None:
            groups[sig] = DupGroup(sig, text, no, no, no, 1, 1)
        else:
            group.occurrences += 1
            group.last_line = no
            if text == group.exemplar:
                group.exact_copies += 1

    with path.open("rb") as fh:
        for raw in fh:
            total_bytes += len(raw)
            sha.update(raw)
            total_lines += 1
            no = total_lines
            text = raw.decode("utf-8", errors="replace")
            if text.endswith("\n"):
                text = text[:-1]
            if text.endswith("\r"):
                text = text[:-1]
            est_in += estimate_tokens(text)
            if first_line_text is None:
                first_line_text = text
            last_line_text = text
            ts = find_timestamp(text)
            if ts is not None:
                if first_ts is None:
                    first_ts = (ts, no)
                last_ts = (ts, no)

            if gated and NEEDLE_RE.search(text) is None:
                matches = [p for p in ungated if p.regex.search(text)]
            else:
                matches = [p for p in patterns if p.regex.search(text)]

            # Evidence overview: count this line once, here, before
            # any claim decision below can consume, extend, or
            # suppress its matches. A line counts once toward
            # matched_lines and once toward its highest matched
            # severity; it counts once per pattern it matches in
            # pattern_counts. Its hour bucket (when it carries a
            # recognised timestamp) counts the line and, when it
            # matched, the match and the bucket's highest severity.
            bucket_label = hour_bucket(ts) if ts is not None else None
            if bucket_label is not None:
                ov_lines_with_ts += 1
                bucket = ov_buckets.get(bucket_label)
                if bucket is None:
                    bucket = ov_buckets[bucket_label] = {
                        "bucket": bucket_label, "first_line": no,
                        "last_line": no, "lines": 0, "matched_lines": 0,
                        "max_severity": 0}
                bucket["last_line"] = no
                bucket["lines"] += 1
            if matches:
                ov_matched_lines += 1
                top_severity = max(m.severity for m in matches)
                ov_severity_counts[top_severity] = \
                    ov_severity_counts.get(top_severity, 0) + 1
                for m in matches:
                    ov_pattern_counts[m.id] = \
                        ov_pattern_counts.get(m.id, 0) + 1
                if bucket_label is not None:
                    bucket["matched_lines"] += 1
                    if top_severity > bucket["max_severity"]:
                        bucket["max_severity"] = top_severity
                else:
                    ov_matched_without_ts += 1

            if current is not None:
                belongs = no <= planned_end
                if not belongs and trace_absorbed < TRACE_ABSORB_CAP \
                        and is_continuation(text):
                    belongs = True
                    trace_absorbed += 1
                    planned_end = no
                if belongs:
                    if matches:
                        current.match_signatures.add(signature_of(text))
                        for m in matches:
                            current.matches.append(
                                {"line": no, "pattern": m.id})
                            if m.severity > current.severity:
                                current.severity = m.severity
                                current.pattern_id = m.id
                        planned_end = max(planned_end, no + window_after)
                    claim_window_line(current, no, text)
                    continue
                close_window(current)
                current = None

            if matches and signature_of(text) in windowed_signatures:
                # A later burst of an error that already has a
                # window: collapse it as a duplicate instead of
                # opening another window.
                suppressed += 1
                matches = []

            if matches:
                start = pending[0][0] if pending else no
                current = Window(start_line=start, match_line=no)
                current.match_signatures.add(signature_of(text))
                for m in matches:
                    current.matches.append({"line": no, "pattern": m.id})
                    if m.severity > current.severity:
                        current.severity = m.severity
                        current.pattern_id = m.id
                for pno, ptext in pending:
                    claim_window_line(current, pno, ptext)
                pending.clear()
                planned_end = no + window_after
                trace_absorbed = 0
                claim_window_line(current, no, text)
                continue

            if window_before > 0:
                pending.append((no, text))
                while len(pending) > window_before:
                    pno, ptext = pending.popleft()
                    dup_account(pno, ptext)
            else:
                dup_account(no, text)

    if current is not None:
        close_window(current)
    for pno, ptext in pending:
        dup_account(pno, ptext)
    pending.clear()

    return Analysis(
        source_path=str(path),
        source_bytes=total_bytes,
        source_sha256=sha.hexdigest(),
        total_lines=total_lines,
        estimated_tokens_in=est_in,
        first_line_text=first_line_text,
        last_line_text=last_line_text,
        first_timestamp=first_ts,
        last_timestamp=last_ts,
        windows=windows,
        dup_groups=groups,
        dup_accounted_lines=dup_accounted,
        suppressed_repeat_matches=suppressed,
        first_dup_signature=first_dup_sig,
        last_dup_signature=last_dup_sig if last_dup_no == total_lines else None,
        matched_lines=ov_matched_lines,
        pattern_counts=ov_pattern_counts,
        severity_counts=ov_severity_counts,
        timeline_buckets=sorted(ov_buckets.values(),
                                key=lambda b: b["first_line"]),
        lines_with_timestamp=ov_lines_with_ts,
        matched_lines_without_timestamp=ov_matched_without_ts,
    )
