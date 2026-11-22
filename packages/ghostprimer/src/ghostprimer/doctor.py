"""Doctor: read-only report of primer sources on a project.

Answers "what would a build find here?" without writing anything:
extracted facts, entry points, which fallback memory files exist,
whether a Recall bundle is present at a conventional location, and
which token estimator is in use. A project root that resolves to a
private memory location is reported as refused, never read.
"""
from __future__ import annotations

from pathlib import Path

from . import scan, tokens
from .memory import FALLBACK_FILES


def doctor(project) -> dict:
    """Return the read-only report dict for *project*.

    ``ok`` is False (with ``errors``) when the project is missing or
    is a private memory location; otherwise ``ok`` is True even when
    individual memory sources are simply absent.
    """
    root = Path(project)
    if not root.is_dir():
        return {"ok": False, "errors": [f"project not found: {project}"]}
    if scan.is_private_memory(root):
        return {"ok": False,
                "errors": ["refused: project root is a private memory location"]}
    root = root.resolve()
    facts = scan.project_facts(root)
    entries = scan.find_entry_points(root, facts)
    sources = {}
    readme = scan.readme_path(root)
    sources["readme"] = readme.name if readme else None
    for name in FALLBACK_FILES:
        if name == "README.md":
            continue
        sources[name] = (root / name).exists()
    decisions = root / "docs" / "decisions"
    sources["docs/decisions"] = (
        len(list(decisions.glob("*.md"))) if decisions.is_dir() else 0)
    recall_found = None
    for candidate in (root / ".ghostrecall", root / "recall-bundle"):
        if (candidate / "manifest.json").exists():
            recall_found = str(candidate)
    return {
        "ok": True,
        "project": str(root),
        "estimator": tokens.METHOD,
        "ghostslice_available": tokens.slice_available(),
        "facts_found": {k: facts.get(k) for k in
                        ("name", "version", "description")},
        "entry_points": entries,
        "memory_sources": sources,
        "recall_bundle_found": recall_found,
        "note": "Project-local sources only; private memory locations "
                "are refused by rule and never read.",
    }
