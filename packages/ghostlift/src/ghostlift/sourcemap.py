"""Tier 1 exact recovery from version 3 source maps.

A source map's sourcesContent entries are the original source, byte
for byte. GhostLift recovers exactly those entries, sanitises the
paths so nothing can be written outside the output tree, and reports
every listed source that carries no embedded content as not recovered.
Static parsing only: the map is read as JSON data, nothing in it is
executed or fetched. Mappings (VLQ) are not decoded in v0.1 because
recovery does not need them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import PurePosixPath


class SourceMapError(ValueError):
    """Raised when a source map cannot be read honestly."""


@dataclass
class RecoveredSource:
    """One source recovered byte-for-byte from a map's ``sourcesContent``."""

    original_path: str
    output_path: str
    content: bytes
    path_rewritten: bool


@dataclass
class SourceMapResult:
    """Outcome of a source-map recovery: what came back, what did not."""

    sources_total: int
    recovered: list[RecoveredSource]
    not_recovered: list[str]
    map_file: str | None


def sanitise_source_path(raw: str, index: int) -> tuple[str, bool]:
    """Map a source path from a map file to a safe relative path.

    Strips ``webpack://`` prefixes, absolute roots, drive fragments,
    and ``.`` components; ``..`` becomes ``__`` so no path can escape
    the output tree. Returns ``(path, rewritten)`` where ``rewritten``
    is true when anything had to change; callers record it in the
    manifest.
    """
    rewritten = False
    text = raw.replace("\\", "/")
    if text.startswith("webpack://"):
        text = text[len("webpack://") :]
        rewritten = True
    parts = []
    for part in PurePosixPath(text).parts:
        if not part.strip("/"):
            # Root anchor: "/", and also "//" (UNC-style), which
            # PurePosixPath reports as a part of its own. Dropping
            # only "/" would leave "//etc/passwd" absolute, and
            # files_dir / "//etc/passwd" escapes the output tree.
            rewritten = True
            continue
        if part == "..":
            parts.append("__")
            rewritten = True
            continue
        if part == ".":
            rewritten = True
            continue
        if len(part) >= 2 and part[1] == ":" and part[0].isalpha():
            # Windows drive prefix, absolute ("C:\x") or relative
            # ("C:x"): strip the drive, keep any remainder as a part.
            rewritten = True
            part = part[2:]
            if not part:
                continue
        if ":" in part and len(part) <= 3:
            # Windows drive fragment or scheme remnant.
            rewritten = True
            continue
        parts.append(part)
    if text != raw:
        rewritten = True
    if not parts:
        return f"unnamed-{index}.txt", True
    return "/".join(parts), rewritten


def recover_source_map(data: bytes) -> SourceMapResult:
    """Recover every ``sourcesContent`` entry from version 3 map bytes.

    Sources listed in the map but carrying no embedded content are
    returned in ``not_recovered`` by name, never silently dropped.

    Raises:
        SourceMapError: the bytes are not UTF-8 JSON, the root is
            not an object, the version is not 3, or ``sources`` /
            ``sourcesContent`` do not line up.
    """
    try:
        parsed = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        # RecursionError: a pathologically nested document is a
        # malformed/hostile map, not a reason to crash the caller.
        raise SourceMapError(f"not a readable UTF-8 JSON source map: {exc}") from exc
    if not isinstance(parsed, dict):
        raise SourceMapError("source map root is not a JSON object")
    if parsed.get("version") != 3:
        raise SourceMapError(f"unsupported source map version: {parsed.get('version')!r}")
    sources = parsed.get("sources")
    if not isinstance(sources, list) or not all(isinstance(s, str) for s in sources):
        raise SourceMapError("source map has no valid sources list")
    contents = parsed.get("sourcesContent")
    if contents is None:
        contents = [None] * len(sources)
    if not isinstance(contents, list) or len(contents) != len(sources):
        raise SourceMapError("sourcesContent does not line up with sources")
    recovered: list[RecoveredSource] = []
    not_recovered: list[str] = []
    used: dict[str, int] = {}
    for i, (source, content) in enumerate(zip(sources, contents)):
        if not isinstance(content, str):
            not_recovered.append(source)
            continue
        output_path, rewritten = sanitise_source_path(source, i)
        if output_path in used:
            # Generate candidates until one is genuinely unused, and
            # register each generated name: the old counter-only
            # scheme returned an already-taken name when a literal
            # source (e.g. "x-2.js") collided with a generated one,
            # so two recovered files shared one output path.
            stem, dot, ext = output_path.rpartition(".")
            can_split = bool(dot) and "/" not in ext and bool(ext)
            count = used[output_path]
            while True:
                count += 1
                candidate = (
                    f"{stem}-{count}.{ext}" if can_split else f"{output_path}-{count}"
                )
                if candidate not in used:
                    used[output_path] = count
                    used[candidate] = 1
                    output_path = candidate
                    break
            rewritten = True
        else:
            used[output_path] = 1
        recovered.append(
            RecoveredSource(
                original_path=source,
                output_path=output_path,
                content=content.encode("utf-8"),
                path_rewritten=rewritten,
            )
        )
    return SourceMapResult(
        sources_total=len(sources),
        recovered=recovered,
        not_recovered=not_recovered,
        map_file=parsed.get("file") if isinstance(parsed.get("file"), str) else None,
    )
