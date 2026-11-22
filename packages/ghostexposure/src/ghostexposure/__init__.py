"""GhostExposure: audit bundles with proof of exclusion.

Evidence only. This package partitions a project tree against a readable
surface pack, exports the surface plus its direct context, and verifies a
bundle against its manifest. It records evidence only: contents,
decisions, reasons, and hashes. It issues no verdict about the code in
a bundle and makes no network calls.

Public constants:
    COVERAGE_STATEMENT: the coverage-limits wording written into every
        scan report, export, and verification. Its presence in a bundle
        is checked by ``verify``; do not reword it casually.
    CANNOT_PROVE_STATEMENT: the wording that states what verification
        cannot prove. Printed by every ``verify`` run and written into
        every ``EXPOSURE.md``.
"""
__version__ = "0.1.0"

COVERAGE_STATEMENT = (
    "Coverage limits: this tool matches files using the patterns in the "
    "surface pack only. It does not detect sensitive logic in files with "
    "no matching signals, and a file recorded as not in the bundle is "
    "recorded on pattern outcome alone."
)
CANNOT_PROVE_STATEMENT = (
    "This verification proves the bundle on disk matches its manifest. "
    "It cannot prove a sender did not share other files by another channel. "
    "It proves what is in the artifact, not what happened in the world."
)
