"""GhostLedger: local token and cost ledger for GhostSlice.

GhostLedger answers the end-of-day question the other Ghost tools
do not: what did agent work cost, per project, per model, per
agent, per day, and where did the actual diverge from the estimate?
It ingests GhostSlice history, GhostProxy reports, and GhostBench
reports plus manual entries into one local ledger file.

Zero-dependency Python stdlib only. Local only, no network, no
telemetry, ever. Ledger never approves, blocks, or dispatches
anything. All dollar figures are ESTIMATES from a local dated price
table, never billed amounts and never live prices; an unknown model
books cost as unknown, never as $0. API keys are never stored or
logged: importers drop credential-named fields on sight.
"""

__version__ = "0.1.0"
LOOP_THRESHOLD = 3.0
