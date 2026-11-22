"""ghostworkflow: the Ghost ecosystem's end-to-end workflow runner.

GhostConsole stays read-only; this package is the one that runs
things. It invokes GhostSlice, GhostVerify, GhostBench and
GhostConsole through their CLIs (never by importing them), lets each
engine write its native reports, and writes one workflow-report.json
per run carrying the shared evidence contract fields.
"""

__version__ = "0.1.0"
