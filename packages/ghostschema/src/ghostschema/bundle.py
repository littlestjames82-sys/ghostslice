"""Bundle writing: reduced spec (or SDL outline) + manifest.json +
SCHEMA.md. Writes only inside the output directory. The input spec
is never modified.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .loader import SchemaError
from .tokens import METHOD, estimate_tokens


def build_manifest(loaded, treatment, result, sliced_text):
    """Build the manifest dict for one run.

    ``treatment`` is ``"reduced"`` for JSON specs or ``"outline"``
    for SDL. ``result`` is the slicer or outliner result (selection,
    kept, dropped, unresolved, warnings). Token figures are estimates
    for the untouched source text and for ``sliced_text``, stamped
    with the estimator method that produced them.
    """
    original_tokens = estimate_tokens(loaded.text)
    sliced_tokens = estimate_tokens(sliced_text)
    return {
        "tool": "ghostschema",
        "version": __version__,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": {
            "path": str(loaded.path),
            "name": loaded.path.name,
            "sha256": loaded.sha256,
            "bytes": loaded.size_bytes,
        },
        "format": loaded.format,
        "treatment": treatment,
        "token_method": METHOD,
        "original_tokens": original_tokens,
        "sliced_tokens": sliced_tokens,
        "saved_tokens": original_tokens - sliced_tokens,
        "selection": result["selection"],
        "kept": result["kept"],
        "dropped": result["dropped"],
        "unresolved_refs": result["unresolved"],
        "warnings": result["warnings"],
    }


def render_schema_md(manifest):
    """Render a manifest as the human-readable ``SCHEMA.md`` summary."""
    src = manifest["source"]
    lines = [
        f"# GhostSchema bundle: {src['name']}",
        "",
        f"Format: {manifest['format']}  ",
        f"Treatment: {manifest['treatment']}  ",
        f"Source sha256: {src['sha256']}  ",
        f"Tokens (estimated, {manifest['token_method']}): "
        f"{manifest['original_tokens']} -> {manifest['sliced_tokens']} "
        f"(saved {manifest['saved_tokens']})",
        "",
    ]
    if manifest["treatment"] == "outline":
        lines += [
            "This bundle is an OUTLINE of the types reachable for the "
            "selection. It is not a complete reduced schema.",
            "",
        ]
    sel = manifest["selection"]
    lines.append(f"Selection mode: {sel['mode']}")
    if sel.get("task"):
        lines.append(f"Task: {sel['task']}")
    if sel.get("select"):
        lines.append(f"Selected ids: {', '.join(sel['select'])}")
    lines.append("")
    for heading, data in (("Kept", manifest["kept"]), ("Dropped", manifest["dropped"])):
        lines.append(f"## {heading}")
        for key, value in data.items():
            if isinstance(value, list):
                if value:
                    for item in value:
                        lines.append(f"- {key}: {item}")
                else:
                    lines.append(f"- {key}: (none)")
            else:
                lines.append(f"- {key}: {value}")
        lines.append("")
    if manifest["unresolved_refs"]:
        lines.append("## Unresolved references (remote, never fetched)")
        for item in manifest["unresolved_refs"]:
            extra = " [also missing locally]" if item.get("missing_local") else ""
            via = f" via {item['via']}" if item.get("via") else ""
            lines.append(f"- {item['ref']} (referenced from {item['from']}{via}){extra}")
        lines.append("")
    if manifest["warnings"]:
        lines.append("## Warnings")
        for warning in manifest["warnings"]:
            lines.append(f"- {warning}")
        lines.append("")
    lines.append(
        "A reduced spec is a reading aid for an agent, not a deployable "
        "API contract. Do not ship it as the API's source of truth."
    )
    return "\n".join(lines) + "\n"


def write_bundle(outdir, files, manifest):
    """Write a bundle directory: ``files`` plus manifest.json and SCHEMA.md.

    Creates the directory if needed. Writes only inside ``outdir``;
    raises SchemaError if ``outdir`` exists and is not a directory.
    Returns the output path.
    """
    out = Path(outdir)
    if out.exists() and not out.is_dir():
        raise SchemaError(f"output path exists and is not a directory: {out}")
    try:
        out.mkdir(parents=True, exist_ok=True)
        for name, text in files.items():
            (out / name).write_text(text, encoding="utf-8")
        (out / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        (out / "SCHEMA.md").write_text(
            render_schema_md(manifest), encoding="utf-8")
    except OSError as exc:
        raise SchemaError(f"cannot write bundle to {out}: {exc}")
    return out
