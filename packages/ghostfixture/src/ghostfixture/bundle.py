"""GhostSlice bundle reader.

A bundle is the on-disk artifact GhostSlice writes: ``manifest.json``
(per-file path/mode/language/original_tokens/sliced_tokens/sha256 plus
totals), ``PROMPT.md`` and ``files/<rel>`` holding the sliced text.

GhostFixture only needs the manifest: which project files the bundle
references (every entry whose mode is not ``exclude``). The bytes are
always copied from the original project, never from the sliced text.
A manifest that does not parse means no fixture can be built; callers
map that to exit 2, never to an empty-but-successful fixture.

Guard records: when a bundle was exported with GhostSlice's
redaction on, each flagged file's manifest entry carries
``redactions`` (how many values the guard flagged and replaced in
that file) and ``redaction_kinds`` (the guard's finding types for
it, e.g. ``sensitive-assignment``). Those fields are the bundle's
recorded guard findings; the reader surfaces them per entry so the
build can propagate them instead of dropping them silently. A plain
export records no per-file findings in the manifest (the guard's
warning exists only on the export terminal), so entries parsed from
such a bundle simply carry no findings.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path


class BundleError(ValueError):
    """The bundle cannot be read well enough to build a fixture."""


@dataclass
class BundleEntry:
    """One referenced file from a bundle manifest.

    ``mode`` is the bundle's mode for the file (anything other than
    ``exclude`` counts as referenced). ``redactions`` and
    ``redaction_kinds`` carry the guard findings the bundle recorded
    for the file, or stay empty when it recorded none.
    """

    path: str
    mode: str
    language: str = "text"
    sha256: str = ""
    redactions: int = 0
    redaction_kinds: list = field(default_factory=list)

    @property
    def upstream_findings(self):
        """The guard findings the bundle recorded for this file, as
        ``{"redactions": n, "kinds": [...]}``, or None when the
        bundle recorded none (the common case: most exports record
        no per-file findings at all)."""
        if self.redactions > 0 or self.redaction_kinds:
            return {"redactions": self.redactions,
                    "kinds": list(self.redaction_kinds)}
        return None


@dataclass
class Bundle:
    """A parsed GhostSlice bundle: its manifest plus the split of
    entries into referenced files (``entries``) and the paths the
    bundle listed with mode ``exclude`` (``excluded``)."""

    path: Path
    manifest: dict
    manifest_sha256: str
    root: str = ""
    entries: list = field(default_factory=list)  # list[BundleEntry], referenced only
    excluded: list = field(default_factory=list)  # paths listed with mode "exclude"

    @property
    def referenced_paths(self) -> list:
        """Project-relative paths of every referenced (non-exclude) entry."""
        return [e.path for e in self.entries]


def load_bundle(bundle_path) -> Bundle:
    """Read and validate a bundle's ``manifest.json``.

    Returns a Bundle with referenced entries in manifest order and
    duplicate paths removed. Raises BundleError when the bundle is
    not a directory, the manifest cannot be read or parsed, or an
    entry has no string ``path``.
    """
    bundle = Path(bundle_path)
    if not bundle.is_dir():
        raise BundleError(f"bundle is not a directory: {bundle}")
    mpath = bundle / "manifest.json"
    try:
        raw = mpath.read_bytes()
    except OSError as exc:
        raise BundleError(f"manifest.json: cannot read ({exc})") from exc
    manifest_sha = hashlib.sha256(raw).hexdigest()
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise BundleError(f"manifest.json: invalid ({exc})") from exc
    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), list):
        raise BundleError("manifest.json: top level must be an object with a 'files' list")
    entries: list[BundleEntry] = []
    excluded: list = []
    seen: set = set()
    for i, entry in enumerate(manifest["files"]):
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise BundleError(f"manifest files[{i}]: not an object with a string 'path'")
        rel = entry["path"]
        mode = str(entry.get("mode") or "full")
        if mode == "exclude":
            # In the manifest but not referenced. The exclusion is an
            # explicit bundle decision: Fixture records it and never
            # copies the file, not even via import closure.
            if rel not in excluded:
                excluded.append(rel)
            continue
        if rel in seen:
            continue
        seen.add(rel)
        redactions = entry.get("redactions")
        if not isinstance(redactions, int) or isinstance(redactions, bool) \
                or redactions < 0:
            redactions = 0
        kinds = entry.get("redaction_kinds")
        kinds = [str(k) for k in kinds if isinstance(k, str)] \
            if isinstance(kinds, list) else []
        entries.append(BundleEntry(
            path=rel,
            mode=mode,
            language=str(entry.get("language") or "text"),
            sha256=str(entry.get("sha256") or ""),
            redactions=redactions,
            redaction_kinds=kinds,
        ))
    return Bundle(
        path=bundle,
        manifest=manifest,
        manifest_sha256=manifest_sha,
        root=str(manifest.get("root") or ""),
        entries=entries,
        excluded=excluded,
    )
