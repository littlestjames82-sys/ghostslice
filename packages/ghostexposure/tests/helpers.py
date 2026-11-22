"""Helpers for reading GhostExposure artifacts in a schema-tolerant way.

The primary assumed schema (REPORT_B.md) for ``exposure.json`` is:

    {
      "surface": {"id": ..., "version": ...},
      "inventory_sha256": "...",
      "files": [
        {"path": "auth/login.py", "decision": "surface",
         "reasons": ["glob:auth/**"]},
        {"path": "app/main.py", "decision": "context",
         "reasons": ["graph-neighbour"]},
        {"path": "util/format.py", "decision": "out",
         "reasons": ["no-match"]}
      ],
      "redactions": [{"path": "config/secrets_config.py", "type": "..."}]
    }

Decisions normalise as: surface/context/in/included -> IN,
out/excluded/not_in_bundle -> OUT, conflict -> CONFLICT.

Alternate shapes ({"partition": {"in": [...], "out": [...]}},
{"in_bundle": [...], "not_in_bundle": [...]}) are also normalised so a
reasonable core variation does not fail every test for a naming choice.
Strictness lives in the set comparisons in the tests, not in key names.
"""
from __future__ import annotations

import json
from pathlib import Path

METADATA_FILES = {"exposure.json", "EXPOSURE.md", "manifest.json", "PROMPT.md"}

IN_WORDS = {"in", "surface", "context", "included", "in_bundle", "include"}
OUT_WORDS = {"out", "excluded", "not_in_bundle", "exclude", "not-in-bundle"}


def load_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def find_exposure_json(bundle: Path) -> Path:
    direct = Path(bundle) / "exposure.json"
    if direct.exists():
        return direct
    hits = sorted(Path(bundle).rglob("exposure.json"))
    assert hits, f"no exposure.json found under bundle {bundle}"
    return hits[0]


def get_partition(exposure) -> tuple[set, set, set]:
    """Return (in_set, out_set, conflict_set) of relative posix paths."""
    in_set: set = set()
    out_set: set = set()
    conflict_set: set = set()

    if isinstance(exposure, dict):
        files = exposure.get("files") or exposure.get("partition_files")
        if isinstance(files, list):
            for entry in files:
                if isinstance(entry, str):
                    in_set.add(entry)
                    continue
                path = entry.get("path") or entry.get("file")
                decision = str(entry.get("decision") or entry.get("status") or "").lower()
                if not path:
                    continue
                if decision == "conflict":
                    conflict_set.add(path)
                elif decision in IN_WORDS:
                    in_set.add(path)
                elif decision in OUT_WORDS:
                    out_set.add(path)
            return in_set, out_set, conflict_set

        part = exposure.get("partition") or exposure
        for key in ("in", "in_bundle", "included", "surface", "context"):
            val = part.get(key) if isinstance(part, dict) else None
            if isinstance(val, list):
                in_set.update(v if isinstance(v, str) else v.get("path") for v in val)
        for key in ("out", "not_in_bundle", "excluded"):
            val = part.get(key) if isinstance(part, dict) else None
            if isinstance(val, list):
                out_set.update(v if isinstance(v, str) else v.get("path") for v in val)
        for key in ("conflicts", "conflict"):
            val = part.get(key) if isinstance(part, dict) else None
            if isinstance(val, list):
                conflict_set.update(v if isinstance(v, str) else v.get("path") for v in val)
    return in_set, out_set, conflict_set


def inventory(project: Path) -> set:
    """All regular files under a project, relative posix paths.

    Hidden VCS internals are not project inventory. Everything else counts:
    the plan's partition must account for every file, with no file in
    neither list.
    """
    out = set()
    for p in Path(project).rglob("*"):
        if p.is_file() and ".git" not in p.parts and "__pycache__" not in p.parts:
            out.add(p.relative_to(project).as_posix())
    return out


def bundle_payload_files(bundle: Path) -> set:
    """Files a receiver actually got, relative posix paths.

    Handles both bundle layouts: payload under ``files/<rel>`` (GhostSlice
    style) or payload at the bundle root. Metadata files are not payload.
    """
    bundle = Path(bundle)
    payload = set()
    files_dir = bundle / "files"
    base = files_dir if files_dir.is_dir() else bundle
    for p in base.rglob("*"):
        if p.is_file() and "__pycache__" not in p.parts:
            rel = p.relative_to(base).as_posix()
            if rel not in METADATA_FILES:
                payload.add(rel)
    return payload


def read_all_text(bundle: Path) -> dict:
    """Map of relative path -> text for every readable file in a bundle."""
    texts = {}
    for p in Path(bundle).rglob("*"):
        if p.is_file():
            try:
                texts[p.relative_to(bundle).as_posix()] = p.read_text(encoding="utf-8", errors="strict")
            except (UnicodeDecodeError, ValueError):
                continue
    return texts


COVERAGE_FRAGMENTS = (
    ("does not detect", "no matching"),
    ("does not cover", "no matching"),
    ("not cover", "sensitive logic"),
    ("does not detect", "sensitive"),
)

CANNOT_PROVE_FRAGMENTS = (
    ("cannot prove", "another channel"),
    ("cannot prove", "other channel"),
    ("cannot prove", "did not share"),
    ("can not prove", "another channel"),
)


def contains_limit_statement(text: str, fragment_sets) -> bool:
    low = text.lower()
    return any(all(frag in low for frag in frags) for frags in fragment_sets)
