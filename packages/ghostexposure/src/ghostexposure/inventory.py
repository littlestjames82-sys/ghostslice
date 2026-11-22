"""Full-tree inventory: every file accounted for exactly once.

The inventory is the denominator for the partition: every regular file
under the project root (minus the always-skipped directories in
``DEFAULT_IGNORE_DIRS`` and paths matched by the project's
``.gitignore``) appears exactly once, with its size and sha256. Files
small enough and free of NUL bytes are also carried as decoded text for
pattern matching; larger or binary files are recorded with
``text=None``.
"""
import hashlib
import os
import stat as stat_mod
from pathlib import Path

DEFAULT_IGNORE_DIRS = {".git", "__pycache__", ".tox", ".venv", "venv",
                       "node_modules", "dist", "build", ".ghostexposure-cache"}
MAX_TEXT_BYTES = 2_000_000


def _gitignore_patterns(root):
    """Return the non-comment, non-negation patterns from ``.gitignore``.

    Patterns are stripped of surrounding slashes. Negations (``!...``)
    are not honoured: a path matched by any listed pattern is treated
    as ignored. Returns an empty list when there is no ``.gitignore``.
    """
    pats = []
    gi = root / ".gitignore"
    if gi.exists():
        for raw in gi.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and not line.startswith("!"):
                pats.append(line.strip("/"))
    return pats


def _ignored(rel, pats):
    """Return True when project-relative path ``rel`` matches a pattern.

    A pattern matches the full relative path, the path with the
    pattern as a directory prefix, or any leading directory of the
    path.
    """
    import fnmatch
    parts = rel.split("/")
    for pat in pats:
        if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(rel, pat + "/*"):
            return True
        for i in range(len(parts)):
            if fnmatch.fnmatch("/".join(parts[:i + 1]), pat):
                return True
    return False


def is_text_bytes(data):
    """Return True when ``data`` looks like text (no NUL in first 4 KiB)."""
    return b"\x00" not in data[:4096]


def build_inventory(root):
    """Walk ``root`` and return the sorted inventory of its files.

    Each entry is a dict with keys ``path`` (project-relative, POSIX
    separators), ``size`` (bytes), ``sha256`` (hex digest of the raw
    bytes), ``is_text``, and ``text`` (decoded text, or None for binary
    or oversized files). Entries are sorted by ``path``.

    Raises ValueError when ``root`` is not a directory.
    """
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError(f"project is not a directory: {root}")
    pats = _gitignore_patterns(root)
    entries = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Fail closed on symlinked directories os.walk will not descend
        # into: one pointing outside the tree (or nowhere) would leave
        # reachable files silently unaccounted for in the partition.
        for d in dirnames:
            if d in DEFAULT_IGNORE_DIRS:
                continue
            full_dir = Path(dirpath) / d
            if full_dir.is_symlink():
                rel_dir = full_dir.relative_to(root).as_posix()
                target = full_dir.resolve()
                if not target.exists():
                    raise ValueError(
                        f"broken symlink in project tree: {rel_dir}")
                try:
                    target.relative_to(root)
                except ValueError:
                    raise ValueError(
                        "symlinked directory in project tree points "
                        f"outside the project: {rel_dir}") from None
        dirnames[:] = sorted(d for d in dirnames
                             if d not in DEFAULT_IGNORE_DIRS)
        for name in sorted(filenames):
            full = Path(dirpath) / name
            rel = full.relative_to(root).as_posix()
            if _ignored(rel, pats):
                continue
            # Fail closed on entries the inventory cannot account for
            # faithfully, instead of crashing on a raw OSError, blocking
            # forever opening a FIFO, or silently copying content from
            # outside the tree into an export.
            try:
                st = full.lstat()
            except OSError as e:
                raise ValueError(
                    f"cannot stat file in project tree: {rel}: {e}") from e
            if stat_mod.S_ISLNK(st.st_mode):
                target = full.resolve()
                if not target.exists():
                    raise ValueError(
                        f"broken symlink in project tree: {rel}")
                try:
                    target.relative_to(root)
                except ValueError:
                    raise ValueError(
                        "symlink in project tree points outside the "
                        f"project: {rel}") from None
                if target.is_dir():
                    raise ValueError(
                        f"symlink in project tree points to a "
                        f"directory: {rel}")
            elif not stat_mod.S_ISREG(st.st_mode):
                raise ValueError(
                    f"not a regular file in project tree: {rel}")
            try:
                data = full.read_bytes()
            except OSError as e:
                raise ValueError(
                    f"cannot read file in project tree: {rel}: {e}") from e
            is_text = is_text_bytes(data) and len(data) <= MAX_TEXT_BYTES
            entries.append({
                "path": rel,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "is_text": bool(is_text),
                "text": data.decode("utf-8", errors="replace") if is_text else None,
            })
    return sorted(entries, key=lambda e: e["path"])


def inventory_hash(entries):
    """Return the sha256 hex digest identifying an inventory.

    The digest covers each entry's ``path`` and ``sha256`` in the
    order given, so two inventories hash equally only when they list
    the same paths with the same contents.
    """
    h = hashlib.sha256()
    for e in entries:
        h.update(f"{e['path']}\0{e['sha256']}\n".encode("utf-8"))
    return h.hexdigest()


def estimate_tokens(text, path=None):
    """Token estimate for inventory/partition records.

    Delegates to ghostexposure.tokens, which prefers GhostSlice's
    estimator (per-file language) so figures recorded here match the
    manifest figures GhostSlice's checker recomputes. Imported here
    (not at module top) to keep the inventory module importable on
    its own."""
    from .tokens import estimate_tokens as _estimate
    return _estimate(text, path)
