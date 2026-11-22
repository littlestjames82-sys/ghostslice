"""Target renderers and losses accounting.

Every renderer keeps the manifest's file order and shows each file's mode
label in a section header. Anything a target cannot carry is named in the
losses list, which the CLI writes to LOSSES.md in the output directory.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import __version__
from .bundle import Bundle, BundleFile

TARGETS = ("agents", "cursor", "copilot", "generic")

TARGET_ARTIFACTS = {
    "agents": "AGENTS.md",
    "cursor": ".cursor/rules/*.mdc (one per top-level directory group)",
    "copilot": ".github/copilot-instructions.md",
    "generic": "prompt.md",
}


def _fence(body: str, language: str) -> str:
    """A fenced code block whose fence is longer than any backtick run
    inside the body, so bodies containing ``` do not break the block."""
    longest = 0
    for m in re.finditer(r"`+", body):
        longest = max(longest, len(m.group(0)))
    ticks = "`" * max(3, longest + 1)
    lang = "" if language in ("", "text", "notebook") else language
    return f"{ticks}{lang}\n{body}\n{ticks}"


def _header_lines(bundle: Bundle, target: str) -> list[str]:
    """The conversion header every artifact opens with: provenance,
    project name, the manifest's token totals when recorded, and the
    warning that a non-full slice mode is not the full source."""
    m = bundle.manifest
    total_after = m.get("total_sliced_tokens")
    total_before = m.get("total_original_tokens")
    saved = m.get("total_saved_tokens")
    lines = [
        f"Converted by GhostConvert {__version__} from a GhostSlice bundle "
        f"(target: {target}). Do not edit the source bundle; regenerate "
        f"from it instead.",
        f"Project: {bundle.project_name}",
    ]
    if total_after is not None and total_before is not None:
        saved_clause = f", saved {saved}" if saved is not None else ""
        lines.append(
            f"Estimated tokens: {total_after} sliced (was {total_before}"
            f"{saved_clause}). Token counts are estimates from the source "
            f"manifest (method: {m.get('token_method', 'unknown')}).")
    lines.append(
        "Each file keeps its GhostSlice slice mode in its header. A file "
        "marked signatures, symbols, interfaces, or strip-tests is NOT the "
        "full source. See LOSSES.md in this output for what this format "
        "could not carry from the manifest.")
    return lines


def _section(f: BundleFile, heading: str = "##") -> str:
    """One file's section: a header carrying its slice mode label,
    then its body in a fenced code block."""
    return (f"{heading} File: {f.path} (mode: {f.mode_label})\n\n"
            f"{_fence(f.body or '', f.language)}\n")


def _render_single(bundle: Bundle, target: str, title: str) -> str:
    parts = [f"# {title}\n"]
    parts.append("\n".join(_header_lines(bundle, target)) + "\n")
    for f in bundle.included:
        if f.body is None:
            continue
        parts.append("\n" + _section(f) + "\n")
    return "".join(parts)


def render_agents(bundle: Bundle) -> str:
    """Render the ``agents`` target: one ``AGENTS.md`` document."""
    return _render_single(bundle, "agents",
                          "AGENTS.md (GhostSlice context, converted)")


def render_copilot(bundle: Bundle) -> str:
    """Render the ``copilot`` target: one Copilot instructions file,
    with the same section discipline as ``agents``."""
    return _render_single(bundle, "copilot",
                          "Copilot instructions (GhostSlice context, converted)")


def render_generic(bundle: Bundle) -> str:
    """Render the ``generic`` target: one plain ``prompt.md``, bodies
    unfenced under ``# File:`` headers, closest to Slice's PROMPT.md."""
    parts = ["# Converted agent context (GhostConvert, from a GhostSlice bundle)\n\n"]
    parts.append("\n".join(_header_lines(bundle, "generic")) + "\n")
    for f in bundle.included:
        if f.body is None:
            continue
        parts.append(f"\n\n---\n\n# File: {f.path} (mode: {f.mode_label})\n\n"
                     f"{f.body}\n")
    return "".join(parts)


def _group_key(path: str) -> str:
    """Cursor grouping key: a path's top-level directory, or ``root``
    for files that sit at the project root."""
    parts = path.split("/")
    return parts[0] if len(parts) > 1 else "root"


def _group_slug(group: str) -> str:
    """Filesystem-safe slug for a group name, used in rule filenames."""
    slug = re.sub(r"[^a-z0-9]+", "-", group.lower()).strip("-")
    return slug or "root"


def render_cursor(bundle: Bundle) -> dict[str, str]:
    """{relative artifact path: text}, one .mdc per top-level group."""
    groups: dict[str, list[BundleFile]] = {}
    for f in bundle.included:
        if f.body is None:
            continue
        groups.setdefault(_group_key(f.path), []).append(f)
    out: dict[str, str] = {}
    used_slugs: set[str] = set()
    for group, members in groups.items():
        slug = _group_slug(group)
        # Distinct groups can slugify to the same name ("My Docs" and
        # "my-docs" both become "my-docs"). Without disambiguation the
        # later group would silently overwrite the earlier rule file
        # and its files would vanish from the output with no loss named.
        base_slug, suffix = slug, 2
        while slug in used_slugs:
            slug = f"{base_slug}-{suffix}"
            suffix += 1
        used_slugs.add(slug)
        globs = ", ".join(f.path for f in members)
        parts = [
            "---\n",
            f"description: GhostSlice context for {group} "
            f"(converted by GhostConvert {__version__})\n",
            f"globs: {globs}\n",
            "alwaysApply: false\n",
            "---\n\n",
            f"<!-- ghostconvert: target=cursor group={group} -->\n\n",
            f"# GhostSlice context: {group}\n\n",
            "\n".join(_header_lines(bundle, "cursor")) + "\n",
        ]
        for f in members:
            parts.append("\n" + _section(f) + "\n")
        out[f".cursor/rules/ghostconvert-{slug}.mdc"] = "".join(parts)
    return out


def compute_losses(bundle: Bundle, target: str) -> list[tuple[str, str]]:
    """(name, detail) pairs naming everything the target did not carry."""
    losses: list[tuple[str, str]] = []
    m = bundle.manifest
    inc = bundle.included

    if bundle.excluded:
        names = ", ".join(
            f.path + (f" ({f.entry['mode_reason']})" if f.entry.get("mode_reason") else "")
            for f in bundle.excluded)
        losses.append((
            "Excluded files (no body in any target)",
            f"{len(bundle.excluded)} file(s) were excluded by GhostSlice and "
            f"appear in the source manifest only: {names}. The receiving "
            f"agent does not see them at all."))
    hashed = [f for f in inc if f.sha256]
    if hashed:
        losses.append((
            "Per-file sha256 hashes",
            f"{len(hashed)} hash value(s) from the manifest are not carried "
            f"by the {target} format, so the converted output cannot be "
            f"verified with `ghostslice check`. Verify the source bundle "
            f"instead."))
    counted = [f for f in inc
               if f.original_tokens is not None or f.sliced_tokens is not None]
    if counted:
        losses.append((
            "Per-file token estimates",
            f"Per-file original/sliced token counts for {len(counted)} "
            f"file(s) are not carried; only the bundle totals appear in "
            f"the header."))
    redact = [f for f in inc if f.entry.get("redactions")]
    if redact or m.get("redaction"):
        detail = ", ".join(f"{f.path} ({f.entry['redactions']} redaction(s))"
                           for f in redact) or "manifest-level redaction block"
        losses.append((
            "Redaction metadata",
            f"Redaction counts and kinds are not carried: {detail}. The "
            f"redacted text itself is what was converted; the record of "
            f"what was redacted lives only in the source manifest."))
    scored = [f for f in inc if "score" in f.entry]
    if scored or m.get("fit"):
        losses.append((
            "Slice scoring and fit metadata",
            "Task scores, score components, and any --fit report from the "
            "manifest are not carried by this format."))
    reasoned = [f for f in inc if f.entry.get("mode_reason")]
    if reasoned:
        losses.append((
            "Mode reasons",
            "Why Slice chose a mode is not carried for: "
            + ", ".join(f.path for f in reasoned) + "."))
    packaged = {f.package for f in inc if f.package}
    if packaged and target != "cursor":
        losses.append((
            "Package grouping",
            f"The manifest groups files into {len(packaged)} package(s); "
            f"the {target} format has no package structure, so files are "
            f"a flat list in manifest order."))
    encoded = [f for f in inc if f.entry.get("source_encoding")]
    if encoded:
        losses.append((
            "Source encodings",
            "These files were not plain UTF-8 in the source project: "
            + ", ".join(f"{f.path} ({f.entry['source_encoding']})"
                        for f in encoded)
            + ". The bundle ships decoded UTF-8 text and that is what "
              "was converted."))
    emptied = [f for f in inc if f.emptied_by_design]
    if emptied:
        losses.append((
            "Files emptied by GhostSlice (no body by design)",
            "GhostSlice shipped no body for these files on purpose; the "
            "manifest shows each one as an empty slice, so nothing was "
            "lost in conversion: "
            + ", ".join(f"{f.path} (mode: {f.mode})" for f in emptied)
            + ". They appear in the source manifest only, and the "
              "receiving agent does not see their content because Slice "
              "chose to send none."))
    missing = [f for f in inc if f.missing_body]
    if missing:
        losses.append((
            "Files with no readable body",
            "No body was found in files/ or PROMPT.md for: "
            + ", ".join(f.path for f in missing)
            + ". They are named in the source manifest but absent from "
              "this conversion."))
    unknown = {}
    for f in bundle.files:
        if f.unknown_mode:
            unknown.setdefault(f.mode, []).append(f.path)
    if unknown:
        detail = "; ".join(
            f"{mode} (on: {', '.join(paths)})"
            for mode, paths in sorted(unknown.items()))
        losses.append((
            "Unrecognized slice modes",
            "These mode labels are not recognized by GhostConvert: "
            + detail + ". Each label is carried verbatim in the section "
              "headers and the files are converted like any other, but "
              "GhostConvert cannot say what slicing the label means; "
              "only the source bundle knows."))
    if bundle.skipped_paths:
        losses.append((
            "Manifest paths outside the bundle",
            "These manifest paths escape the bundle directory and were "
            "not followed: " + ", ".join(bundle.skipped_paths) + "."))
    if target == "cursor":
        losses.append((
            "Cursor rule grouping",
            "Files were regrouped into one rule file per top-level "
            "directory, a structure GhostSlice never made. Manifest order "
            "is kept inside each group, but the interleaving across "
            "groups is not preserved, and rule frontmatter (description, "
            "globs, alwaysApply) is generated by GhostConvert, not Slice."))
        if packaged:
            losses.append((
                "Package grouping",
                "The manifest's package groupings are replaced by the "
                "top-level directory grouping described above."))
    if target in ("agents", "copilot"):
        losses.append((
            "Machine-readable per-file metadata",
            f"The {target} format is a single prose document; beyond the "
            f"mode label in each section header there is no structured "
            f"per-file metadata channel, so language and package fields "
            f"from the manifest are not carried."))
    return losses


def render_losses(bundle: Bundle, target: str,
                  losses: list[tuple[str, str]]) -> str:
    """Render the losses list as the ``LOSSES.md`` shipped with every
    conversion. An empty list still produces a note that says so, so
    the file is never simply absent."""
    parts = [f"# Conversion losses: {target}\n\n",
             f"Source bundle: {bundle.root}\n",
             f"Project: {bundle.project_name}\n",
             f"Converted by GhostConvert {__version__}. This note names "
             f"everything the {target} format could not carry from the "
             f"GhostSlice manifest, so nothing was dropped silently.\n"]
    if not losses:
        parts.append("\nNo losses recorded for this target.\n")
    for name, detail in losses:
        parts.append(f"\n## {name}\n\n{detail}\n")
    return "".join(parts)


def convert(bundle: Bundle, target: str) -> tuple[dict[str, str], list]:
    """{relative artifact path: text} plus the losses list for a target.

    LOSSES.md is included in the returned mapping.
    """
    losses = compute_losses(bundle, target)
    if target == "agents":
        artifacts = {"AGENTS.md": render_agents(bundle)}
    elif target == "copilot":
        artifacts = {".github/copilot-instructions.md": render_copilot(bundle)}
    elif target == "generic":
        artifacts = {"prompt.md": render_generic(bundle)}
    elif target == "cursor":
        artifacts = render_cursor(bundle)
    else:
        raise ValueError(f"unknown target: {target}")
    artifacts["LOSSES.md"] = render_losses(bundle, target, losses)
    return artifacts, losses
