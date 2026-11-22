"""GhostConsole: one offline HTML board for every Ghost tool's reports.

Read-only by construction. Console reads published report artifacts
(histories, manifests, report JSON, ledger summaries, queue stores),
never executes another tool, and renders a single self-contained HTML
file with no JavaScript and no external assets.
"""

__version__ = "0.1.0"
