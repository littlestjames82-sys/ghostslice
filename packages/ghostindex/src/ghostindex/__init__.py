"""GhostIndex: cross-project local search index for GhostSlice.

Indexes code and docs from project roots the user names into a local
sqlite database (FTS5, stdlib sqlite3) and answers searches with
ranked, bounded excerpts instead of whole files. Offline only: the
tool contains no network code and never writes into an indexed root.
"""

__version__ = "0.1.0"
