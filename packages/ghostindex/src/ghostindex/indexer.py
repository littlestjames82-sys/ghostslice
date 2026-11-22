"""Build and incrementally update the index.

Update is hash-driven: a re-walk compares size + mtime first, then
sha256, and only files whose content hash actually changed are
re-read into FTS. Files that vanished, became ignored, became binary,
or grew past the size cap are removed. Counts are exact and reported
(added / changed / removed / unchanged / skipped), because "the
update did nothing" must be provable, not assumed.
"""
from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import scanner, tokens

DEFAULT_MAX_BYTES = 2 * 1024 * 1024
_SNIFF_BYTES = 8192


@dataclass
class UpdateReport:
    """Exact outcome of indexing one root. Counts are reported, not
    summarised away, so "the update did nothing" is provable:
    a no-change run shows ``unchanged`` for every file and zero
    for added / changed / removed."""

    root: str
    added: int = 0
    changed: int = 0
    removed: int = 0
    unchanged: int = 0
    skipped_binary_content: int = 0
    skipped_too_large: int = 0
    skipped_unreadable: int = 0
    walk_skips: dict = field(default_factory=dict)
    files_indexed: int = 0
    total_tokens: int = 0

    def as_dict(self) -> dict:
        """The report as printed by ``index --json`` / ``update --json``."""
        return {
            "root": self.root,
            "added": self.added,
            "changed": self.changed,
            "removed": self.removed,
            "unchanged": self.unchanged,
            "skipped_binary_content": self.skipped_binary_content,
            "skipped_too_large": self.skipped_too_large,
            "skipped_unreadable": self.skipped_unreadable,
            "walk_skips": self.walk_skips,
            "files_indexed": self.files_indexed,
            "total_tokens": self.total_tokens,
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def index_root(
    conn: sqlite3.Connection,
    root: Path,
    max_bytes: int = DEFAULT_MAX_BYTES,
    db_path: Path | None = None,
) -> UpdateReport:
    """Full or incremental (re)index of one root. Same code path:
    on a first run every file is 'added', later runs diff by hash."""
    root = root.resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"not a directory: {root}")
    if max_bytes < 0:
        raise ValueError("max_bytes must be at least 0")
    root_str = str(root)
    report = UpdateReport(root=root_str)

    extra_skip: set[Path] = set()
    if db_path is not None:
        extra_skip.add(db_path.resolve())

    walked = scanner.walk(root, extra_skip_paths=extra_skip)
    report.walk_skips = walked.skips.as_dict()

    existing = {
        row["rel"]: row
        for row in conn.execute(
            "SELECT id, rel, sha256, size, mtime FROM files WHERE root = ?",
            (root_str,),
        )
    }

    seen: set[str] = set()
    for cand in walked.candidates:
        if cand.size > max_bytes:
            report.skipped_too_large += 1
            continue
        old = existing.get(cand.rel)
        if (
            old is not None
            and old["size"] == cand.size
            and abs(old["mtime"] - cand.mtime) < 1e-6
        ):
            seen.add(cand.rel)
            report.unchanged += 1
            continue
        try:
            data = cand.abspath.read_bytes()
        except OSError:
            report.skipped_unreadable += 1
            continue
        if len(data) > max_bytes:
            # The size cap is re-checked on the bytes actually read:
            # the walker's stat can be stale (a file that grew after
            # it was statted, or a link whose target changed), and a
            # stale small stat must not let oversized content in.
            report.skipped_too_large += 1
            continue
        digest = hashlib.sha256(data).hexdigest()
        if old is not None and old["sha256"] == digest:
            conn.execute(
                "UPDATE files SET size = ?, mtime = ? WHERE id = ?",
                (cand.size, cand.mtime, old["id"]),
            )
            seen.add(cand.rel)
            report.unchanged += 1
            continue
        if b"\x00" in data[:_SNIFF_BYTES]:
            report.skipped_binary_content += 1
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("utf-8", errors="replace")
        language = scanner.language_for(cand.rel)
        line_count = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
        est = tokens.estimate_tokens(text, language)
        if old is not None:
            conn.execute(
                "UPDATE files SET sha256 = ?, size = ?, mtime = ?, language = ?,"
                " line_count = ?, tokens = ? WHERE id = ?",
                (digest, cand.size, cand.mtime, language, line_count, est, old["id"]),
            )
            conn.execute(
                "UPDATE docs SET rel = ?, body = ? WHERE rowid = ?",
                (cand.rel, text, old["id"]),
            )
            report.changed += 1
        else:
            cur = conn.execute(
                "INSERT INTO files(root, rel, sha256, size, mtime, language,"
                " line_count, tokens) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (root_str, cand.rel, digest, cand.size, cand.mtime,
                 language, line_count, est),
            )
            conn.execute(
                "INSERT INTO docs(rowid, rel, body, root) VALUES (?, ?, ?, ?)",
                (cur.lastrowid, cand.rel, text, root_str),
            )
            report.added += 1
        seen.add(cand.rel)

    for rel, row in existing.items():
        if rel not in seen:
            conn.execute("DELETE FROM files WHERE id = ?", (row["id"],))
            conn.execute("DELETE FROM docs WHERE rowid = ?", (row["id"],))
            report.removed += 1

    conn.execute(
        "INSERT INTO projects(root, indexed_at, token_method) VALUES (?, ?, ?)"
        " ON CONFLICT(root) DO UPDATE SET indexed_at = excluded.indexed_at,"
        " token_method = excluded.token_method",
        (root_str, _now_iso(), tokens.method()),
    )
    agg = conn.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(tokens), 0) AS t FROM files WHERE root = ?",
        (root_str,),
    ).fetchone()
    report.files_indexed = agg["n"]
    report.total_tokens = agg["t"]
    conn.commit()
    return report


def remove_root(conn: sqlite3.Connection, root: Path) -> int:
    """Drop one root from the index. Returns files removed.
    Deletes nothing from the project itself."""
    root_str = str(root.resolve())
    ids = [row["id"] for row in conn.execute(
        "SELECT id FROM files WHERE root = ?", (root_str,))]
    for fid in ids:
        conn.execute("DELETE FROM docs WHERE rowid = ?", (fid,))
    conn.execute("DELETE FROM files WHERE root = ?", (root_str,))
    conn.execute("DELETE FROM projects WHERE root = ?", (root_str,))
    conn.commit()
    return len(ids)


def known_roots(conn: sqlite3.Connection) -> list[str]:
    """Every root currently in the index, sorted by path."""
    return [row["root"] for row in conn.execute(
        "SELECT root FROM projects ORDER BY root")]
