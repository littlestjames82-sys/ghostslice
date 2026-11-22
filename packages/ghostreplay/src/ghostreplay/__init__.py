"""GhostReplay: what did an agent session actually consume?

Zero-dependency (Python stdlib only), local-first, no network, no
telemetry, no live recording. GhostReplay analyses local transcript
files the user already has on disk, joined against a GhostSlice
bundle manifest, and PROPOSES GhostSlice profile improvements with
evidence. It never applies a profile change without an explicit
terminal yes (see cli.apply_command), and it never quotes
secret-shaped strings in any output (see secrets.py).

Note on the name (from PLAN.md, not hidden): GhostGuard already
has a "replay" add-on in the family (policy backtest over recorded
trails). This tool does a different job (session context replay);
the product name is GhostReplay unless Ryan renames it. The
reserve alternative discussed in the plan is GhostTrace.

Token counts are estimates, not exact model tokenizer counts.
"""
__version__ = "0.1.0"
__all__ = ["__version__"]
