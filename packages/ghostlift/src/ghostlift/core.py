"""Inspect and lift orchestration plus the Slice-style manifest.

Output tree written by lift:

    <out>/
      manifest.json     every file marked lifted, with its tier
      files/<path>      recovered (Tier 1, byte-exact) or lifted
                        (Tier 2, reconstructed) source

Static analysis only. Nothing in this module imports, loads, or
executes an artifact.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import __version__
from .jslift import find_function_boundaries, lift_javascript
from .pyc import parse_pyc, top_level_symbols
from .reconstruct import reconstruct_source
from .sourcemap import SourceMapError, recover_source_map

TIER3_SUFFIXES = {".class", ".dex", ".dll", ".wasm", ".exe", ".so", ".dylib"}
SUPPORTED_SUFFIXES = {".pyc", ".map", ".js"}


class LiftError(ValueError):
    """Raised when a path holds no artifact GhostLift can lift."""


def _sha256(data: bytes) -> str:
    """Hex sha256 digest of ``data``, as recorded in the manifest."""
    return hashlib.sha256(data).hexdigest()


def _token_estimate(text: str) -> int:
    # Same honest label as GhostSlice: an estimate, chars / 4.
    return (len(text) + 3) // 4


def detect_kind(path: Path) -> str:
    """Classify an artifact by filename suffix.

    Returns one of ``"pyc"``, ``"sourcemap"``, ``"javascript"``,
    ``"tier3-bytecode"``, or ``"unknown"``. Classification only looks
    at the suffix; the parsers validate the actual bytes afterwards.
    """
    suffix = path.suffix.lower()
    if suffix == ".pyc":
        return "pyc"
    if suffix == ".map":
        return "sourcemap"
    if suffix == ".js":
        return "javascript"
    if suffix in TIER3_SUFFIXES:
        return "tier3-bytecode"
    return "unknown"


def inspect_artifact(path: Path) -> dict:
    """Report what an artifact is, without lifting it.

    Returns a JSON-ready dict with ``path``, ``kind``, ``size_bytes``,
    ``sha256`` and ``executable_by_ghostlift`` (always ``False``),
    plus, where the kind is recognised: ``tier``, ``tier_name`` and
    ``liftable``, kind-specific details (for a ``.pyc``: magic,
    implied CPython version, embedded filename, top-level symbols;
    for a source map: how many sources are recoverable), and a
    ``note`` or ``error`` explaining any non-liftable result.
    The artifact is parsed as data only; nothing is executed.
    """
    data = path.read_bytes()
    info: dict = {
        "path": str(path),
        "kind": detect_kind(path),
        "size_bytes": len(data),
        "sha256": _sha256(data),
        "executable_by_ghostlift": False,
    }
    kind = info["kind"]
    if kind == "pyc":
        try:
            parsed = parse_pyc(data)
        except Exception as exc:
            info.update({"tier": None, "liftable": False, "error": str(exc)})
            return info
        info.update(
            {
                "tier": 2,
                "tier_name": "structured",
                "liftable": True,
                "magic": parsed.magic,
                "python_version": parsed.python_version,
                "hash_based": parsed.hash_based,
                "embedded_filename": parsed.module.filename,
                "top_level_symbols": top_level_symbols(parsed.module),
            }
        )
        return info
    if kind == "sourcemap":
        try:
            result = recover_source_map(data)
        except SourceMapError as exc:
            info.update({"tier": None, "liftable": False, "error": str(exc)})
            return info
        info.update(
            {
                "tier": 1,
                "tier_name": "exact",
                "liftable": True,
                "map_file": result.map_file,
                "sources_total": result.sources_total,
                "sources_recoverable": len(result.recovered),
                "sources_not_recovered": result.not_recovered,
            }
        )
        return info
    if kind == "javascript":
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            info.update({"tier": 2, "tier_name": "structured", "liftable": False,
                         "error": f"not readable UTF-8 JavaScript: {exc}"})
            return info
        functions = find_function_boundaries(text)
        info.update(
            {
                "tier": 2,
                "tier_name": "structured",
                "liftable": True,
                "function_boundaries": functions,
                "function_count": len(functions),
                "note": (
                    "Tier 2 beautify lift: structure and function boundaries "
                    "are recovered; names destroyed by minification stay destroyed"
                ),
            }
        )
        return info
    if kind == "tier3-bytecode":
        info.update(
            {
                "tier": 3,
                "tier_name": "outline",
                "liftable": False,
                "note": "Tier 3 formats are detected and reported only in v0.1",
            }
        )
        return info
    info.update({"tier": None, "liftable": False, "note": "unrecognised artifact type"})
    return info


def _output_name_for_pyc(path: Path, embedded_filename: str) -> str:
    """Output ``.py`` filename for a lifted ``.pyc``.

    Prefers the source filename recorded inside the artifact; falls
    back to the artifact's own stem, unwrapping ``__pycache__``-style
    names such as ``module.cpython-312.pyc``.
    """
    name = Path(embedded_filename).name if embedded_filename else ""
    if name.endswith(".py"):
        return name
    stem = path.name
    if stem.endswith(".pyc"):
        stem = stem[: -len(".pyc")]
    # __pycache__ style: module.cpython-312 -> module
    if ".cpython-" in stem:
        stem = stem.split(".cpython-", 1)[0]
    if stem.endswith(".py"):
        return stem
    return stem + ".py"


def _unique(rel: str, used: dict[str, int]) -> str:
    """De-duplicate an output path, suffixing repeats with ``-2``, ``-3``..."""
    if rel not in used:
        used[rel] = 1
        return rel
    # Generate candidates until one is genuinely unused, and register
    # each generated name. The old counter-only scheme returned an
    # already-taken name when a literal input (e.g. "a-2.js") collided
    # with a generated one, so two manifest entries shared one path
    # and the later write silently overwrote the earlier file.
    stem, dot, ext = rel.rpartition(".")
    can_split = bool(dot) and "/" not in ext and bool(ext)
    count = used[rel]
    while True:
        count += 1
        candidate = f"{stem}-{count}.{ext}" if can_split else f"{rel}-{count}"
        if candidate not in used:
            used[rel] = count
            used[candidate] = 1
            return candidate


def lift_path(source: Path, out_dir: Path) -> dict:
    """Lift one artifact, or every supported artifact under a folder.

    Writes ``<out_dir>/files/...`` plus ``<out_dir>/manifest.json``
    (see the module docstring) and returns the manifest as a dict.
    Every manifest file entry is watermarked: ``lifted`` is true,
    with its ``tier``, recovery kind, source artifact and that
    artifact's sha256. Artifacts that fail to lift are recorded in
    the manifest's ``failures`` list rather than raising.

    Raises:
        LiftError: ``source`` does not exist, or no supported
            artifact (``.pyc`` / ``.map`` / ``.js``) was found.
    """
    artifacts: list[Path] = []
    if source.is_dir():
        for candidate in sorted(source.rglob("*")):
            if candidate.is_file() and candidate.suffix.lower() in SUPPORTED_SUFFIXES:
                if out_dir in candidate.parents:
                    continue
                artifacts.append(candidate)
    elif source.is_file():
        artifacts.append(source)
    else:
        raise LiftError(f"no such file or folder: {source}")
    if not artifacts:
        raise LiftError(f"no liftable artifacts (.pyc / .map / .js) found under {source}")

    files_dir = out_dir / "files"
    try:
        files_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise LiftError(f"cannot create output folder {out_dir}: {exc}") from exc
    manifest_files: list[dict] = []
    manifest_artifacts: list[dict] = []
    used: dict[str, int] = {}
    failures: list[dict] = []

    for artifact in artifacts:
        try:
            data = artifact.read_bytes()
        except OSError as exc:
            failures.append({"artifact": str(artifact), "error": str(exc)})
            continue
        artifact_sha = _sha256(data)
        kind = detect_kind(artifact)
        manifest_artifacts.append(
            {"path": str(artifact), "kind": kind, "sha256": artifact_sha,
             "size_bytes": len(data)}
        )
        if kind == "pyc":
            try:
                parsed = parse_pyc(data)
            except Exception as exc:
                failures.append({"artifact": str(artifact), "error": str(exc)})
                continue
            # Reconstruction and writing stay inside the guard: one
            # hostile or odd artifact (unencodable names, unwritable
            # target) must be a recorded failure, never a crash that
            # loses every other artifact and the manifest.
            try:
                text = reconstruct_source(parsed.module, artifact.name)
                rel = _unique(
                    _output_name_for_pyc(artifact, parsed.module.filename), used
                )
                payload = text.encode("utf-8")
                target = files_dir / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)
            except Exception as exc:
                failures.append({"artifact": str(artifact), "error": str(exc)})
                continue
            manifest_files.append(
                {
                    "path": rel,
                    "mode": "lifted",
                    "lifted": True,
                    "tier": 2,
                    "tier_name": "structured",
                    "recovery": "structured",
                    "source_artifact": str(artifact),
                    "source_sha256": artifact_sha,
                    "sha256": _sha256(payload),
                    "tokens_estimate": _token_estimate(text),
                    "token_estimate_method": "chars/4 estimate",
                    "python_version": parsed.python_version,
                    "embedded_filename": parsed.module.filename,
                }
            )
        elif kind == "javascript":
            try:
                source_text = data.decode("utf-8")
            except UnicodeDecodeError as exc:
                failures.append(
                    {"artifact": str(artifact),
                     "error": f"not readable UTF-8 JavaScript: {exc}"}
                )
                continue
            functions = find_function_boundaries(source_text)
            # Lift and writing stay inside a guard, like the .pyc
            # branch above (harden lane): one hostile or odd JS
            # artifact must be a recorded failure, never a crash
            # that loses every other artifact and the manifest.
            try:
                text = lift_javascript(source_text, artifact.name)
                rel = _unique(artifact.name, used)
                payload = text.encode("utf-8")
                target = files_dir / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)
            except Exception as exc:
                failures.append({"artifact": str(artifact), "error": str(exc)})
                continue
            manifest_files.append(
                {
                    "path": rel,
                    "mode": "lifted",
                    "lifted": True,
                    "tier": 2,
                    "tier_name": "structured",
                    "recovery": "structured",
                    "source_artifact": str(artifact),
                    "source_sha256": artifact_sha,
                    "sha256": _sha256(payload),
                    "tokens_estimate": _token_estimate(text),
                    "token_estimate_method": "chars/4 estimate",
                    "function_boundaries": functions,
                    "function_count": len(functions),
                }
            )
        elif kind == "sourcemap":
            try:
                result = recover_source_map(data)
            except SourceMapError as exc:
                failures.append({"artifact": str(artifact), "error": str(exc)})
                continue
            for item in result.recovered:
                rel = _unique(item.output_path, used)
                target = files_dir / rel
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(item.content)
                except (OSError, ValueError) as exc:
                    # e.g. a NUL byte or an over-long component in a
                    # sanitised path: record it, keep lifting the rest.
                    failures.append(
                        {
                            "artifact": str(artifact),
                            "error": f"cannot write recovered source {item.original_path}: {exc}",
                        }
                    )
                    continue
                manifest_files.append(
                    {
                        "path": rel,
                        "mode": "lifted",
                        "lifted": True,
                        "tier": 1,
                        "tier_name": "exact",
                        "recovery": "exact",
                        "source_artifact": str(artifact),
                        "source_sha256": artifact_sha,
                        "source_path_in_map": item.original_path,
                        "path_rewritten": item.path_rewritten,
                        "sha256": _sha256(item.content),
                        "tokens_estimate": _token_estimate(
                            item.content.decode("utf-8", "replace")
                        ),
                        "token_estimate_method": "chars/4 estimate",
                    }
                )
            for missing in result.not_recovered:
                failures.append(
                    {
                        "artifact": str(artifact),
                        "error": f"source listed in map has no sourcesContent: {missing}",
                    }
                )

    manifest = {
        "format": "ghostlift-manifest-0.1",
        "tool": "ghostlift",
        "version": __version__,
        "note": (
            "Every file in this tree is LIFTED from a compiled or minified "
            "artifact. Tier 1 files are byte-exact recoveries from a source "
            "map. Tier 2 files are structured reconstructions, NOT original "
            "source. Do not treat any lifted file as original source."
        ),
        "artifacts": manifest_artifacts,
        "files": manifest_files,
        "failures": failures,
        "totals": {
            "files": len(manifest_files),
            "tokens_estimate": sum(f["tokens_estimate"] for f in manifest_files),
            "artifacts": len(manifest_artifacts),
            "failures": len(failures),
        },
    }
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
    except (OSError, ValueError) as exc:
        raise LiftError(f"cannot write manifest in {out_dir}: {exc}") from exc
    return manifest
