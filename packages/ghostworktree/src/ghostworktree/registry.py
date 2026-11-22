"""Atomic JSON registry at <worktrees-root>/registry.json. Never stores file/env contents."""
from __future__ import annotations
import json, os, tempfile
from contextlib import contextmanager
from pathlib import Path
from .errors import RegistryError

try:
    import fcntl
except ImportError:  # non-POSIX: locking degrades to no-op, atomic save still applies
    fcntl = None

REGISTRY_NAME = "registry.json"
SCHEMA = 1

@contextmanager
def locked(root: Path):
    """Exclusive advisory lock serialising registry read-modify-write cycles.

    Create and cleanup hold this across load -> allocate -> git -> save, so
    two concurrent processes cannot allocate the same port or overwrite
    each other's records. Reads (list/status) do not take it: save() swaps
    the file atomically, so a reader always sees a complete old or new file.
    """
    root = Path(root)
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        # e.g. the root path is an existing file: report a named
        # registry error, never a bare traceback.
        raise RegistryError(f"could not create registry root: {root}: {e}") from e
    if fcntl is None:
        yield
        return
    try:
        fh = open(root / ".registry.lock", "a+")
    except OSError as e:
        raise RegistryError(f"could not open registry lock: {root}: {e}") from e
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try: fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally: fh.close()

def default_root(repo: Path) -> Path:
    """Default worktrees root: the sibling ``<repo-parent>/<repo-name>-worktrees``."""
    repo = Path(repo).resolve()
    return repo.parent / f"{repo.name}-worktrees"

def registry_path(root: Path) -> Path:
    """Path of the registry file inside a worktrees root."""
    return Path(root) / REGISTRY_NAME

def load(root: Path, *, allow_duplicate_names: bool = False) -> dict:
    """Load and validate the registry; return an empty one if none exists yet.

    Corrupt JSON, an unexpected shape, a record missing a valid
    ``name``/``path``/``branch``, an invalid ``port`` (non-integer,
    boolean, or outside 1-65535), or a duplicate worktree name
    raises :class:`RegistryError` naming the problem. A bad registry
    is never silently treated as empty, which would orphan trees.

    ``allow_duplicate_names`` exists only for the read-only
    ``doctor`` audit, which must *report* duplicate names as a
    problem instead of failing on them; every other caller uses
    the strict default.
    """
    p = registry_path(root)
    if not p.exists():
        return {"schema": SCHEMA, "worktrees": []}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        raise RegistryError(f"registry is corrupt or unreadable: {p}: {e}") from e
    if not isinstance(data, dict) or not isinstance(data.get("worktrees"), list):
        raise RegistryError(f"registry has unexpected shape: {p}")
    seen_names: set[str] = set()
    for i, w in enumerate(data["worktrees"]):
        if not isinstance(w, dict):
            raise RegistryError(f"registry record #{i} in {p} is not an object")
        for field in ("name", "path", "branch"):
            if not isinstance(w.get(field), str) or not w[field]:
                raise RegistryError(
                    f"registry record #{i} in {p} is missing a valid {field!r} field")
        if w["name"] in seen_names and not allow_duplicate_names:
            raise RegistryError(
                f"registry record #{i} in {p} duplicates worktree name {w['name']!r}")
        seen_names.add(w["name"])
        port = w.get("port")
        # bool is a subclass of int in Python: JSON true/false must not
        # pass as ports 1/0, and a port outside 1-65535 is not a port.
        if port is not None and (isinstance(port, bool)
                                 or not isinstance(port, int)
                                 or not (1 <= port <= 65535)):
            raise RegistryError(
                f"registry record #{i} in {p} has an invalid 'port' field")
    return data

def save(root: Path, data: dict) -> Path:
    """Write the registry atomically (temp file, then replace) and return its path.

    Readers therefore always see a complete old or new file. Write
    failures raise :class:`RegistryError`, not a raw ``OSError``.
    """
    root = Path(root)
    p = registry_path(root)
    try:
        root.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(root), prefix=".registry-", suffix=".tmp")
    except OSError as e:
        raise RegistryError(f"could not write registry: {p}: {e}") from e
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True); f.write("\n")
        os.replace(tmp, p)
    except Exception as e:
        try: os.unlink(tmp)
        except OSError: pass
        raise RegistryError(f"could not write registry: {p}: {e}") from e
    return p

def find(data: dict, name: str) -> dict | None:
    """Return the record named ``name``, or ``None`` if it is not registered."""
    for w in data["worktrees"]:
        if w.get("name") == name: return w
    return None

def used_ports(data: dict) -> set[int]:
    """Return the set of ports currently allocated to registered worktrees."""
    return {int(w["port"]) for w in data["worktrees"] if w.get("port") is not None}
