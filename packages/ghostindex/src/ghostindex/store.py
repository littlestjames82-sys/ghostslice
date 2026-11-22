"""Sqlite storage for GhostIndex.

One database file holds every indexed root. Layout:

- ``projects``: one row per named root (path, last update, estimator
  method stamp in force when it was indexed).
- ``files``: one row per indexed file (root, relative path, sha256,
  size, mtime, language, line count, estimated tokens).
- ``docs``: an FTS5 virtual table whose rowid is the files row id,
  holding the searchable text. ``rel`` is an indexed column (so file
  name terms hit); ``root`` is UNINDEXED and only scopes results.

The database lives in the user's local state dir by default
(``~/.local/state/ghostindex/index.db``), overridable with ``--db``
or ``GHOSTINDEX_DB``. Indexing never writes into a project root.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
    root TEXT PRIMARY KEY,
    indexed_at TEXT NOT NULL,
    token_method TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY,
    root TEXT NOT NULL,
    rel TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    language TEXT NOT NULL,
    line_count INTEGER NOT NULL,
    tokens INTEGER NOT NULL,
    UNIQUE(root, rel)
);
CREATE INDEX IF NOT EXISTS idx_files_root ON files(root);
CREATE VIRTUAL TABLE IF NOT EXISTS docs USING fts5(
    rel,
    body,
    root UNINDEXED,
    tokenize = 'unicode61'
);
"""


class StoreError(Exception):
    """The index database cannot be opened, is missing when a
    read-only command needs it, or FTS5 is unavailable. The CLI
    reports it as ``error: ...`` and exits 2."""


def default_db_path() -> Path:
    """Default database location: ``$GHOSTINDEX_DB`` when set, else
    ``$XDG_STATE_HOME/ghostindex/index.db``, else
    ``~/.local/state/ghostindex/index.db``."""
    env = os.environ.get("GHOSTINDEX_DB")
    if env:
        return Path(env).expanduser()
    state_home = os.environ.get("XDG_STATE_HOME")
    base = Path(state_home).expanduser() if state_home else Path.home() / ".local" / "state"
    return base / "ghostindex" / "index.db"


def reclaim_space(conn: sqlite3.Connection) -> None:
    """Actually shrink the database file after rows are deleted.

    sqlite DELETEs only move pages onto the freelist; the file keeps
    its size until a VACUUM rewrites it. This first asks FTS5 to merge
    its index segments (the 'optimize' special insert, best effort:
    very old sqlite builds may not know it, and VACUUM below is the
    step that guarantees the reclaim), then VACUUMs. VACUUM cannot
    run inside a transaction, so any pending work is committed first.
    """
    conn.commit()
    try:
        conn.execute("INSERT INTO docs(docs) VALUES('optimize')")
        conn.commit()
    except sqlite3.Error:
        conn.rollback()
    conn.execute("VACUUM")
    conn.commit()


def freelist_bytes(conn: sqlite3.Connection) -> int:
    """Bytes currently sitting on the sqlite freelist: space the
    file is holding for deleted content, reclaimable by VACUUM."""
    pages = conn.execute("PRAGMA freelist_count").fetchone()[0]
    page_size = conn.execute("PRAGMA page_size").fetchone()[0]
    return int(pages) * int(page_size)


def fts5_available(conn: sqlite3.Connection) -> bool:
    """Probe ``conn`` for FTS5 support by creating and dropping a
    throwaway virtual table. False means this Python/sqlite build
    cannot run GhostIndex at all."""
    try:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _gi_fts_probe USING fts5(x)")
        conn.execute("DROP TABLE IF EXISTS _gi_fts_probe")
        return True
    except sqlite3.Error:
        return False


def open_store(db_path: Path, create: bool = True) -> sqlite3.Connection:
    """Open (and if ``create``, initialise) the index database.

    Raises :class:`StoreError` when the file is missing and
    ``create`` is False, when it cannot be opened, or (with
    ``create``) when FTS5 is unavailable.
    """
    if not create and not db_path.is_file():
        raise StoreError(f"no index database at {db_path} (run: ghostindex index <root>)")
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
    except (OSError, sqlite3.Error) as exc:
        raise StoreError(f"cannot open index database at {db_path}: {exc}") from exc
    conn.row_factory = sqlite3.Row
    if create:
        try:
            conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
        except sqlite3.Error as exc:
            # The file exists but is not a database. Without this
            # probe the FTS5 check below fails on it too and the
            # corruption is misreported as "FTS5 not available".
            conn.close()
            raise StoreError(
                f"index database at {db_path} is unreadable or corrupt: {exc}"
            ) from exc
        if not fts5_available(conn):
            conn.close()
            raise StoreError(
                "sqlite FTS5 is not available in this Python build; "
                "GhostIndex cannot run"
            )
        try:
            conn.executescript(_SCHEMA)
            conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            conn.commit()
        except sqlite3.Error as exc:
            # E.g. the file at db_path exists but is not a database:
            # report it as a StoreError, not a raw traceback.
            conn.close()
            raise StoreError(
                f"index database at {db_path} is unreadable or corrupt: {exc}"
            ) from exc
    return conn
