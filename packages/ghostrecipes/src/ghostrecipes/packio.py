"""Data-only export / import packs, GhostPacks style.

An export pack is a plain folder: the recipe file(s) plus a
manifest.json carrying a sha256 per file. Import verifies the
manifest and every hash, validates every recipe, rejects anything
that is not data (executable bit, shebang, non-data suffix, symlink,
path traversal in a manifest entry), and only then copies files into
the target library folder. Nothing in a pack is ever run.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from . import __version__
from .recipe import (GhostRecipesError, check_data_only_file,
                     extract_recipe_data, load_recipe, strict_json_loads,
                     validate_data)

PACK_FORMAT = "ghostrecipes-pack"
ALLOWED_SUFFIXES = {".json", ".md", ".txt"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def export_pack(recipe_path, out_dir, force: bool = False) -> dict:
    """Copy one recipe into a new pack folder and write its manifest.

    Returns ``{"out_dir", "manifest"}``. Raises
    :class:`GhostRecipesError` if ``out_dir`` is an existing file,
    or a non-empty folder without ``force``.
    """
    src = Path(recipe_path)
    recipe = load_recipe(src)
    out = Path(out_dir)
    if out.exists() and not out.is_dir():
        raise GhostRecipesError(
            f"export target {out} exists and is not a folder")
    if out.exists() and any(out.iterdir()) and not force:
        raise GhostRecipesError(
            f"export target {out} is not empty; use --force to reuse it")
    out.mkdir(parents=True, exist_ok=True)
    dest = out / src.name
    if dest.is_symlink():
        raise GhostRecipesError(
            f"export target {dest} is a symlink; refusing to write "
            f"through it")
    if src.resolve() != dest.resolve():
        shutil.copyfile(src, dest)
    manifest = {
        "format": PACK_FORMAT,
        "ghostrecipes": __version__,
        "recipes": [recipe.id],
        "files": [{"path": src.name, "sha256": _sha256(dest),
                   "recipe_id": recipe.id, "version": recipe.version}],
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    return {"out_dir": str(out), "manifest": manifest}


def _safe_entry(name: str) -> bool:
    p = Path(name)
    return (not p.is_absolute() and ".." not in p.parts
            and len(p.parts) == 1 and p.name == name)


def import_pack(pack_dir, library_dir, force: bool = False) -> dict:
    """Verify a pack, then copy its recipes into ``library_dir``.

    Everything is verified before anything is written: manifest
    shape, per-file sha256, recipe validity, and the data-only rules
    for every file in the pack folder. A name collision without
    ``force`` also writes nothing. Returns ``{"imported", "library",
    "recipes"}``, where ``recipes`` are the ids verified from the
    pack files themselves, not the manifest's claim.
    """
    pack = Path(pack_dir)
    if not pack.is_dir():
        raise GhostRecipesError(f"pack folder not found: {pack}")
    manifest_path = pack / "manifest.json"
    if not manifest_path.is_file():
        raise GhostRecipesError(f"{pack}: manifest.json missing")
    try:
        manifest = strict_json_loads(
            manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError,
            RecursionError) as exc:
        raise GhostRecipesError(
            f"{pack}: manifest.json invalid: {exc}") from exc
    if not isinstance(manifest, dict):
        raise GhostRecipesError(
            f"{pack}: manifest.json must be a JSON object")
    if manifest.get("format") != PACK_FORMAT:
        raise GhostRecipesError(
            f"{pack}: not a {PACK_FORMAT} pack "
            f"(format={manifest.get('format')!r})")
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        raise GhostRecipesError(f"{pack}: manifest files list is empty")

    # Verify everything before writing anything.
    verified: list[Path] = []
    verified_ids: list[str] = []
    seen_paths: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or not _safe_entry(str(entry.get("path", ""))):
            raise GhostRecipesError(
                f"{pack}: unsafe or malformed manifest entry: {entry!r}")
        if entry["path"] in seen_paths:
            raise GhostRecipesError(
                f"{pack}: duplicate manifest entry: {entry['path']}")
        seen_paths.add(entry["path"])
        if not (entry["path"].endswith(".recipe.json")
                or entry["path"].endswith(".recipe.md")):
            raise GhostRecipesError(
                f"{pack}: pack entry is not a recipe file name "
                f"(<id>.recipe.json or <id>.recipe.md): {entry['path']}")
        fpath = pack / entry["path"]
        if fpath.is_symlink() or not fpath.is_file():
            raise GhostRecipesError(f"{pack}: pack entry missing or a "
                                    f"symlink: {entry['path']}")
        for err in check_data_only_file(fpath):
            raise GhostRecipesError(err)
        if _sha256(fpath) != entry.get("sha256"):
            raise GhostRecipesError(
                f"{pack}: sha256 mismatch for {entry['path']}")
        data = extract_recipe_data(fpath)
        errors, _ = validate_data(data, source=entry["path"])
        if errors:
            raise GhostRecipesError(
                f"{pack}: recipe {entry['path']} is invalid: "
                + "; ".join(errors))
        if entry.get("recipe_id") not in (None, data.get("id")):
            raise GhostRecipesError(
                f"{pack}: manifest recipe_id {entry.get('recipe_id')!r} "
                f"does not match recipe id {data.get('id')!r}")
        verified.append(fpath)
        verified_ids.append(data.get("id"))
    # Refuse stray non-data files anywhere in the pack folder. Every
    # file, listed in the manifest or not, must pass the full
    # data-only rules: allowed suffix, no executable bit, no shebang.
    # Before the polish round only the suffix was checked here, so an
    # executable shebang .txt rode along unchallenged.
    for p in sorted(pack.rglob("*")):
        if p.is_symlink():
            raise GhostRecipesError(f"{pack}: symlink in pack: {p}")
        if p.is_file():
            if p.suffix.lower() not in ALLOWED_SUFFIXES:
                raise GhostRecipesError(
                    f"{pack}: non-data file in pack: {p} "
                    f"(allowed: .json, .md, .txt)")
            for err in check_data_only_file(p):
                raise GhostRecipesError(err)

    library = Path(library_dir)
    if library.exists() and not library.is_dir():
        raise GhostRecipesError(
            f"import library {library} exists and is not a folder")
    library.mkdir(parents=True, exist_ok=True)
    for fpath in verified:
        dest = library / fpath.name
        if dest.is_symlink():
            # copyfile would follow the link and overwrite its target
            # outside the library, even a dangling one. Never write
            # through a symlink, --force or not.
            raise GhostRecipesError(
                f"{dest} is a symlink; refusing to import over it "
                f"(nothing was imported)")
        if dest.exists() and not force:
            raise GhostRecipesError(
                f"{dest} already exists in the library; "
                f"use --force to overwrite (nothing was imported)")
    imported = []
    for fpath in verified:
        dest = library / fpath.name
        shutil.copyfile(fpath, dest)
        imported.append(str(dest))
    # Report the ids that were actually verified in the pack files,
    # never the manifest's own unverified claim about them.
    return {"imported": imported, "library": str(library),
            "recipes": verified_ids}
