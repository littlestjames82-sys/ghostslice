"""GhostWatch: standalone staleness checker for saved GhostSlice bundles/Packs.

Snapshot a project's source hashes and symbol outlines when a
bundle is exported (`ghostwatch snapshot`), then ask later whether
that saved bundle still matches the project (`ghostwatch check`):
a verdict of fresh, stale, or unknown, by file and by symbol.
GhostWatch reports freshness only; it never silently refreshes a
bundle - re-export is opt-in via --reexport and is delegated to
the GhostSlice CLI. Local only, stdlib only, no network.
"""
__version__ = "0.1.0"
