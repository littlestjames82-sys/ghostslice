"""GhostPrimer: first-session starter bundle builder for GhostSlice.

Builds a minimal starter pack (project facts, entry-point code slice,
project-memory primer) for a new agent session or a new hire. Extractive
facts only, no LLM, project-local sources only.

Typical use is the CLI (``ghostprimer build <project> -o <bundle>``);
programmatic use is ``ghostprimer.bundle.build_bundle`` and
``ghostprimer.bundle.check_bundle``. See README.md for what goes in
the pack, what is deliberately left out, and the hard rules.
"""
__version__ = "0.1.0"
