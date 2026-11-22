"""GhostLogs: log slicer for GhostSlice.

Turns one local log file into a token-budgeted incident pack
(INCIDENT.md + manifest.json): error/exception windows, collapsed
duplicate lines with exact counts, timeline anchors, and
secret-shaped literals redacted by default. The source log is only
ever read, line by line; it is never modified.
"""

__version__ = "0.1.0"
