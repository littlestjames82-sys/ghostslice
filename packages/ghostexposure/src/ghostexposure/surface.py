"""Surface pack loading and validation. Surface definitions are data.

A surface pack is a JSON document with ``id``, ``version``, ``date``,
``description``, ``patterns``, and ``coverage_limits``. Each pattern
has ``id``, ``kind`` (one of ``glob``, ``symbol``, ``import``,
``data``), ``pattern``, and a plain-words ``reason``. Both sides of a
hand-off read the same pack, and the exact pack used is written into
every export.
"""
import json
from pathlib import Path

VALID_KINDS = {"glob", "symbol", "import", "data"}
REQUIRED_PACK_FIELDS = {"id", "version", "date", "description", "patterns",
                        "coverage_limits"}


class SurfaceError(ValueError):
    pass


def default_pack_path():
    """Return the path of the built-in starter pack.

    Candidates are tried in order: the repo-level ``surfaces/``
    directory, a ``surfaces/`` directory beside the package, then
    ``surfaces/starter.json`` under the current directory. The first
    candidate is returned when none exists, so the caller's error
    names a concrete path.
    """
    # src/ghostexposure/../../surfaces/starter.json relative to package root
    here = Path(__file__).resolve()
    candidates = [
        here.parents[2] / "surfaces" / "starter.json",
        here.parents[1] / "surfaces" / "starter.json",
        Path.cwd() / "surfaces" / "starter.json",
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


def load_pack(path=None):
    """Load and validate a surface pack, returning it as a dict.

    ``path`` defaults to :func:`default_pack_path`. Two spellings are
    normalised on load: ``dated`` is accepted for ``date``, and a
    single string for ``coverage_limits`` becomes a one-item list.
    The loaded pack gains a ``_path`` key with its source path.

    Raises SurfaceError when the file is missing, is not valid JSON,
    is missing required fields, declares a kind other than
    ``surface``, or contains a pattern with a missing field or an
    unknown kind.
    """
    p = Path(path) if path else default_pack_path()
    if not p.exists():
        raise SurfaceError(f"surface pack not found: {p}")
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError as e:
        raise SurfaceError(f"surface pack cannot be read: {p}: {e}") from e
    except UnicodeDecodeError as e:
        raise SurfaceError(f"surface pack is not valid UTF-8: {p}: {e}") from e
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise SurfaceError(f"surface pack is not valid JSON: {p}: {e}") from e
    if not isinstance(data, dict):
        raise SurfaceError(
            f"surface pack {p} must be a JSON object, "
            f"got {type(data).__name__}")
    # Accept 'dated' as the date field name and a plain string for
    # coverage_limits; normalise both to the canonical shape.
    if "date" not in data and "dated" in data:
        data["date"] = data["dated"]
    if isinstance(data.get("coverage_limits"), str):
        data["coverage_limits"] = [data["coverage_limits"]]
    missing = REQUIRED_PACK_FIELDS - set(data)
    if missing:
        raise SurfaceError(f"surface pack {p} missing fields: {sorted(missing)}")
    if data.get("kind", "surface") != "surface":
        raise SurfaceError("surface pack kind must be 'surface'")
    for field in ("id", "version", "date", "description"):
        if not isinstance(data[field], str):
            raise SurfaceError(
                f"surface pack {p} field must be a string: {field}")
    if not isinstance(data["coverage_limits"], list) or not all(
            isinstance(item, str) for item in data["coverage_limits"]):
        raise SurfaceError(
            f"surface pack {p} coverage_limits must be a list of strings")
    if not isinstance(data["patterns"], list):
        raise SurfaceError(f"surface pack {p} patterns must be a list")
    for pat in data["patterns"]:
        if not isinstance(pat, dict):
            raise SurfaceError(f"pattern in {p} is not an object: {pat!r:.60}")
        for field in ("id", "kind", "pattern", "reason"):
            if field not in pat:
                raise SurfaceError(f"pattern in {p} missing field: {field}")
            if not isinstance(pat[field], str):
                raise SurfaceError(
                    f"pattern in {p} field must be a string: {field}")
        if pat["kind"] not in VALID_KINDS:
            raise SurfaceError(
                f"pattern {pat['id']} has unknown kind: {pat['kind']}")
    data["_path"] = str(p)
    return data


def pack_summary(pack):
    """Return a short summary dict for a loaded pack.

    Keys: ``id``, ``version``, ``date``, ``description``, and
    ``pattern_count``. Used by ``scan --json`` and the ``packs``
    command.
    """
    return {"id": pack["id"], "version": pack["version"],
            "date": pack["date"], "description": pack["description"],
            "pattern_count": len(pack["patterns"])}
