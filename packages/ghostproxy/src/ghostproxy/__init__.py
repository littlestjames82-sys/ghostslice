"""GhostProxy: local, fail-open, in-flight context proxy for GhostSlice.

Zero dependencies (Python stdlib only). Localhost only. Never stores,
logs, or writes an API key. Never logs request bodies by default.
Token counts are estimates, not exact model tokenizer counts.
"""
__version__ = "0.1.0"
__all__ = ["__version__"]
