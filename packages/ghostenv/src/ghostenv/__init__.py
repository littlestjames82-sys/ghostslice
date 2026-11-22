"""GhostEnv: local .env doctor for GhostSlice-paired projects.

Zero-dependency Python stdlib only. Local only, no network.

NAMES-ONLY RULE: GhostEnv never prints, logs, or stores actual
environment variable VALUES anywhere. Parsers discard the right-hand
side of every assignment immediately; every data structure, report,
and generated file in this package carries variable names plus
present/absent information only.
"""

__version__ = "0.1.0"

NAMES_ONLY_STATEMENT = (
    "GhostEnv works on variable names only: no value from any file "
    "was stored, printed, or written by this run."
)
