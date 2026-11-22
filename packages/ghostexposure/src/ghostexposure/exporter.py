"""Bundle export and verification.

Bundle layout:
  files/<rel>     exported copies (surface full, context signatures for Python)
  manifest.json   Slice-style per-file manifest (mode, tokens, sha256)
  exposure.json   partition, inventory hash, surface pack, redactions, limits
  EXPOSURE.md     human-readable hand-off document
  PROMPT.md       concatenated exported files
Transforms happen in the exported copy only. The source tree is never altered.
"""
import ast
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from . import CANNOT_PROVE_STATEMENT, COVERAGE_STATEMENT, __version__
from .inventory import build_inventory, estimate_tokens, inventory_hash
from .partition import (
    build_partition,
    load_profile_pins,
    partition_counts,
    pattern_coverage,
)
from .secrets import find_literals, redact_text
from .tokens import METHOD as TOKEN_METHOD
from .tokens import language_for


class ExportError(ValueError):
    pass


def signatures_source(text):
    """Reduce Python source to its signature outline.

    Keeps import lines, function and class signatures with the first
    line of each docstring, and assignment targets, replacing bodies
    with ``...``. This is the form graph-context files take in a
    bundle. Returns ``text`` unchanged when it does not parse.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return text
    out = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            out.append(ast.unparse(node))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node)
            prefix = ("async def" if isinstance(node, ast.AsyncFunctionDef)
                      else "def")
            sig = f"{prefix} {node.name}({ast.unparse(node.args)}):"
            if node.returns is not None:
                sig = sig[:-1] + f" -> {ast.unparse(node.returns)}:"
            out.append(sig)
            if doc:
                out.append(f'    """{doc.splitlines()[0]}"""')
            out.append("    ...")
        elif isinstance(node, ast.ClassDef):
            out.append(f"class {node.name}:")
            doc = ast.get_docstring(node)
            if doc:
                out.append(f'    """{doc.splitlines()[0]}"""')
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    sub_prefix = ("async def"
                                  if isinstance(sub, ast.AsyncFunctionDef)
                                  else "def")
                    ret = (f" -> {ast.unparse(sub.returns)}"
                           if sub.returns is not None else "")
                    out.append(f"    {sub_prefix} {sub.name}"
                               f"({ast.unparse(sub.args)}){ret}: ...")
            out.append("    ...")
        elif isinstance(node, ast.Assign):
            try:
                out.append(ast.unparse(node).split("=")[0].strip() + " = ...")
            except Exception:
                pass
        elif isinstance(node, ast.AnnAssign):
            # Annotated assignments (``x: int = 5``) are AnnAssign, not
            # Assign: they were silently dropped from signatures output.
            try:
                if node.value is not None:
                    out.append(ast.unparse(node).split("=")[0].strip()
                               + " = ...")
                else:
                    out.append(ast.unparse(node))
            except Exception:
                pass
    return "\n".join(out) + "\n"


def _sha(data_bytes):
    """Return the sha256 hex digest of ``data_bytes``."""
    return hashlib.sha256(data_bytes).hexdigest()


def export_bundle(project, out_dir, pack, allow_unredacted=False,
                  exclude_conflicts=False, pins=None):
    """Export a bundle for ``project`` and return its record.

    Writes ``files/``, ``manifest.json``, ``exposure.json``,
    ``EXPOSURE.md``, and ``PROMPT.md`` under ``out_dir``. Surface
    files are exported in full; context files are exported at
    signatures (Python) or in full (other languages); binary surface
    or context files are carried verbatim. Secret-shaped literals in
    exported text are redacted unless ``allow_unredacted`` is true;
    either choice is recorded. ``pins`` defaults to the project's
    ``.ghostslice.json`` pins. Transforms happen in the exported
    copies only; the source project is never altered.

    Returns a dict with ``out``, ``counts``, ``redactions``,
    ``manifest``, and ``exposure``.

    Raises ExportError when unresolved conflicts remain and
    ``exclude_conflicts`` is false, or when ``out_dir`` already
    exists and is not empty.
    """
    project = Path(project).resolve()
    out = Path(out_dir).resolve()
    pins = pins if pins is not None else load_profile_pins(project)
    entries = build_inventory(project)
    # Exclude the output folder itself if it lives inside the project
    try:
        out_rel = out.relative_to(project).as_posix()
        entries = [e for e in entries
                   if not (e["path"] == out_rel or e["path"].startswith(out_rel + "/"))]
    except ValueError:
        pass
    partition = build_partition(entries, pack, pins)
    counts = partition_counts(partition)
    conflicts = [d for d in partition if d["decision"] == "conflict"]
    if conflicts and not exclude_conflicts:
        names = ", ".join(d["path"] for d in conflicts)
        raise ExportError(
            f"unresolved conflicts (surface match + user pin-out): {names}. "
            "Change the pin or the pack, or re-run with --exclude-conflicts "
            "to record an explicit decision to leave them out.")
    by_path = {e["path"]: e for e in entries}
    if out.exists() and not out.is_dir():
        raise ExportError(f"output path exists and is not a folder: {out}")
    if out.exists() and any(out.iterdir()):
        raise ExportError(f"output folder exists and is not empty: {out}")
    (out / "files").mkdir(parents=True, exist_ok=True)

    manifest_files = []
    redactions = []
    prompt_parts = []
    total_in_tokens = 0
    total_original_tokens = 0
    for d in partition:
        if d["decision"] not in ("surface", "context"):
            continue
        entry = by_path[d["path"]]
        text = entry.get("text")
        mode = "full" if d["decision"] == "surface" else "signatures"
        if text is None:
            # Binary surface/context files are carried verbatim under
            # files/, but they are not sliced text: GhostSlice excludes
            # binaries from its bundles, so the GhostSlice-shaped
            # record for one is mode "exclude" with sliced_tokens 0
            # (the mode GhostSlice's checker skips, and the only one
            # that validates for a payload whose bytes are not UTF-8
            # slice text). The Exposure-side record keeps the raw
            # sha256 above, so verify_bundle still hashes the exact
            # carried bytes; "binary"/"carried_verbatim" say why the
            # mode reads "exclude" for a file that is present.
            raw = (project / d["path"]).read_bytes()
            dest = out / "files" / d["path"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(raw)
            manifest_files.append({
                "path": d["path"], "mode": "exclude", "decision": d["decision"],
                "language": language_for(d["path"]), "package": "",
                "binary": True, "carried_verbatim": True,
                "reasons": d["reasons"],
                "original_tokens": 0, "sliced_tokens": 0,
                "original_estimated_tokens": 0,
                "exported_estimated_tokens": 0, "sha256": _sha(raw)})
            continue
        if mode == "signatures" and d["path"].endswith(".py"):
            exported_text = signatures_source(text)
        elif mode == "signatures":
            exported_text = text
            mode = "full"
        else:
            exported_text = text
        findings = find_literals(exported_text)
        file_redactions = []
        if findings and not allow_unredacted:
            exported_text = redact_text(exported_text, findings)
            for f in findings:
                file_redactions.append({"path": d["path"], "line": f["line"],
                                        "type": f["type"]})
        elif findings and allow_unredacted:
            for f in findings:
                file_redactions.append({"path": d["path"], "line": f["line"],
                                        "type": f["type"],
                                        "unredacted_by_explicit_flag": True})
        redactions.extend(file_redactions)
        data = exported_text.encode("utf-8")
        dest = out / "files" / d["path"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        exp_tokens = estimate_tokens(exported_text, d["path"])
        total_in_tokens += exp_tokens
        total_original_tokens += d["estimated_tokens"]
        manifest_files.append({
            "path": d["path"], "mode": mode, "decision": d["decision"],
            "language": language_for(d["path"]), "package": "",
            "reasons": d["reasons"],
            # GhostSlice bundle schema (ghostslice/exporter.py): the
            # per-file token fields and totals below are what
            # `ghostslice check` validates, recomputing sliced_tokens
            # from the exported text with GhostSlice's estimator.
            "original_tokens": d["estimated_tokens"],
            "sliced_tokens": exp_tokens,
            # GhostExposure's original field names, kept so existing
            # readers of this manifest keep working.
            "original_estimated_tokens": d["estimated_tokens"],
            "exported_estimated_tokens": exp_tokens, "sha256": _sha(data)})
        prompt_parts.append(f"\n\n===== {d['path']} ({mode}) =====\n{exported_text}")

    inv_hash = inventory_hash(entries)
    manifest = {"tool": "ghostexposure", "version": __version__,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "root": str(project),
                "token_method": TOKEN_METHOD,
                "files": manifest_files,
                # GhostSlice totals schema: top-level integers that
                # `ghostslice check` requires and recomputes against.
                "total_original_tokens": total_original_tokens,
                "total_sliced_tokens": total_in_tokens,
                "total_saved_tokens": total_original_tokens - total_in_tokens,
                "totals": {"files_in_bundle": len(manifest_files),
                           "original_tokens": total_original_tokens,
                           "sliced_tokens": total_in_tokens,
                           "exported_estimated_tokens": total_in_tokens}}
    exposure = {
        "tool": "ghostexposure", "version": __version__,
        "surface_pack": {"id": pack["id"], "version": pack["version"],
                         "date": pack["date"],
                         "patterns": pack["patterns"]},
        "inventory_hash": inv_hash,
        "inventory_sha256": inv_hash,
        "inventory_file_count": len(entries),
        "surface": {"id": pack["id"], "version": pack["version"],
                    "date": pack["date"]},
        "files": partition,
        "partition": partition,
        "pattern_coverage": pattern_coverage(partition, pack),
        "counts": counts,
        "redactions": redactions,
        "allow_unredacted": bool(allow_unredacted),
        "conflicts_excluded_by_explicit_flag": bool(conflicts and exclude_conflicts),
        "coverage_limits": pack.get("coverage_limits", []),
        "coverage_statement": COVERAGE_STATEMENT,
        "cannot_prove_statement": CANNOT_PROVE_STATEMENT,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n",
                                       encoding="utf-8")
    (out / "exposure.json").write_text(json.dumps(exposure, indent=2) + "\n",
                                       encoding="utf-8")
    (out / "PROMPT.md").write_text(
        "# GhostExposure bundle\n" + "".join(prompt_parts) + "\n",
        encoding="utf-8")
    (out / "EXPOSURE.md").write_text(
        render_exposure_md(exposure, manifest), encoding="utf-8")
    return {"out": str(out), "counts": counts, "redactions": redactions,
            "manifest": manifest, "exposure": exposure}


def render_exposure_md(exposure, manifest):
    """Render the human-readable ``EXPOSURE.md`` for a bundle.

    ``exposure`` and ``manifest`` are the dicts written alongside it
    as ``exposure.json`` and ``manifest.json``. The document lists the
    surface definition in full, the partition counts, the inventory
    hash, the redaction count, both limit statements, and the
    receiver verification instructions. Returns the Markdown text.
    """
    sp = exposure["surface_pack"]
    lines = [
        "# GhostExposure bundle",
        "",
        "This document describes a bundle of files prepared for review. "
        "It records what the bundle contains and what it does not contain. "
        "It makes no statement about the quality of the code in the bundle.",
        "",
        "## Surface definition used",
        f"- Pack: {sp['id']} version {sp['version']} dated {sp['date']}",
        "- Patterns (id, kind, pattern, reason):",
    ]
    for p in sp["patterns"]:
        lines.append(f"  - {p['id']} | {p['kind']} | `{p['pattern']}` | {p['reason']}")
    c = exposure["counts"]
    lines += [
        "",
        "## Counts (from the recorded partition)",
        f"- Files in the source tree inventory: {exposure['inventory_file_count']}",
        f"- Files in bundle: {c['surface']} surface + {c['context']} context "
        f"= {c['surface'] + c['context']}",
        f"- Files not in bundle: {c['out']}",
        f"- Conflicts recorded: {c['conflict']}",
        f"- Exported total: {manifest['totals']['exported_estimated_tokens']} "
        "estimated tokens (estimate from bundle text length, not a measured count)",
        f"- Inventory hash: {exposure['inventory_hash']}",
        f"- Redactions recorded: {len(exposure['redactions'])}"
        + (" (explicit --allow-unredacted was used and is recorded)"
           if exposure["allow_unredacted"] else
           " (secret-shaped literals replaced in exported copies by default)"),
        "",
        "## Pattern coverage (from the recorded partition)",
        "Per pattern, the files recorded as matched in the partition, "
        "with the summed line hits recorded for text patterns. A pattern "
        "listed with no files matched records that outcome only.",
    ]
    coverage = exposure.get("pattern_coverage") or []
    if coverage:
        for cov in coverage:
            files = ", ".join(cov.get("matched_files") or [])
            if files:
                lines.append(
                    f"- {cov['pattern_id']} | {cov['kind']} | "
                    f"matched {cov['matched_file_count']} file(s): {files} | "
                    f"recorded line hits: {cov.get('total_line_hits', 0)}")
            else:
                lines.append(
                    f"- {cov['pattern_id']} | {cov['kind']} | "
                    "no files matched (no matches recorded)")
        unmatched = [c["pattern_id"] for c in coverage
                     if not c.get("matched_files")]
        if unmatched:
            lines.append(
                "- Patterns with no matches recorded: "
                + ", ".join(unmatched))
    else:
        lines.append("- No pattern coverage was recorded in exposure.json.")
    lines += [
        "",
        "## Coverage limits",
        exposure["coverage_statement"],
    ]
    for item in exposure.get("coverage_limits", []):
        lines.append(f"- {item}")
    lines += [
        "",
        "## What verification proves, and what it does not",
        exposure["cannot_prove_statement"],
        "",
        "## How a receiver verifies this bundle",
        "Run, with GhostExposure installed and no network access needed:",
        "",
        "    ghostexposure verify <this-bundle-folder>",
        "",
        "Verification re-reads manifest.json and exposure.json, checks every "
        "exported file hash, checks that the files on disk are exactly the "
        "files recorded as in the bundle, and checks that every file in the "
        "recorded inventory appears exactly once in the partition.",
        "",
    ]
    return "\n".join(lines)


def verify_bundle(bundle_dir):
    """Verify a bundle folder against its manifest and partition.

    Checks that the required bundle files exist, that both limit
    statements are present in ``EXPOSURE.md``, that the partition
    lists every inventory file exactly once and hashes to the
    recorded inventory hash, that the files on disk under ``files/``
    are exactly the manifest set with matching hashes, and that the
    partition in-set equals the manifest set.

    Returns ``(ok, problems, notes)``: ``ok`` is True only when
    ``problems`` is empty; each problem names the file or record that
    disagrees; ``notes`` always carries the cannot-prove and coverage
    statements.
    """
    bundle = Path(bundle_dir).resolve()
    problems, notes = [], []
    for name in ("manifest.json", "exposure.json", "EXPOSURE.md"):
        if not (bundle / name).exists():
            problems.append(f"missing bundle file: {name}")
    if problems:
        return False, problems, notes
    # A corrupt or tampered bundle must fail verification with the
    # discrepancy named, not crash the verifier: parse defensively and
    # report malformed JSON / malformed entries as problems.
    try:
        manifest = json.loads(
            (bundle / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        problems.append(f"manifest.json is not valid JSON: {e}")
        manifest = None
    try:
        exposure = json.loads(
            (bundle / "exposure.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        problems.append(f"exposure.json is not valid JSON: {e}")
        exposure = None
    if problems:
        return False, problems, notes
    if not isinstance(manifest, dict):
        problems.append("manifest.json is not a JSON object")
    if not isinstance(exposure, dict):
        problems.append("exposure.json is not a JSON object")
    if problems:
        return False, problems, notes
    try:
        md = (bundle / "EXPOSURE.md").read_text(encoding="utf-8")
    except (OSError, ValueError) as e:
        problems.append(f"EXPOSURE.md cannot be read: {e}")
        return False, problems, notes
    if COVERAGE_STATEMENT.split(":")[0] not in md:
        problems.append("EXPOSURE.md is missing the coverage-limits statement")
    if "cannot prove" not in md:
        problems.append("EXPOSURE.md is missing the cannot-prove statement")
    # Partition completeness: every inventory path exactly once
    partition = exposure.get("partition", [])
    if not isinstance(partition, list):
        problems.append("exposure.json partition is not a list")
        partition = []
    seen = {}
    valid_entries = []
    for d in partition:
        if not isinstance(d, dict) or not isinstance(d.get("path"), str) \
                or not isinstance(d.get("sha256"), str):
            problems.append(
                f"partition entry is missing a path or sha256: "
                f"{str(d)[:80]}")
            continue
        valid_entries.append(d)
        seen[d["path"]] = seen.get(d["path"], 0) + 1
    for path, n in seen.items():
        if n != 1:
            problems.append(f"partition lists {path} {n} times")
    if len(partition) != exposure.get("inventory_file_count"):
        problems.append(
            f"partition has {len(partition)} entries, inventory count is "
            f"{exposure.get('inventory_file_count')}")
    # Inventory hash over recorded partition source hashes
    fake = [{"path": d["path"], "sha256": d["sha256"]}
            for d in sorted(valid_entries, key=lambda x: x["path"])]
    if len(valid_entries) == len(partition) \
            and inventory_hash(fake) != exposure.get("inventory_hash"):
        problems.append("inventory hash does not match the recorded partition")
    # Files on disk under files/ must equal manifest set, hashes must match
    files_root = bundle / "files"
    on_disk = set()
    if files_root.is_dir():
        for p in files_root.rglob("*"):
            if p.is_file():
                on_disk.add(p.relative_to(files_root).as_posix())
    manifest_files = manifest.get("files", [])
    if not isinstance(manifest_files, list):
        problems.append("manifest.json files is not a list")
        manifest_files = []
    manifest_by_path = {}
    for f in manifest_files:
        if not isinstance(f, dict) or not isinstance(f.get("path"), str) \
                or not isinstance(f.get("sha256"), str):
            problems.append("manifest entry is missing a path or sha256")
            continue
        if f["path"] in manifest_by_path:
            problems.append(f"manifest lists {f['path']} more than once")
        manifest_by_path[f["path"]] = f
    for path in sorted(set(manifest_by_path) - on_disk):
        problems.append(f"recorded in bundle but missing on disk: {path}")
    for path in sorted(on_disk - set(manifest_by_path)):
        problems.append(f"present on disk but not recorded in bundle: {path}")
    for path, f in manifest_by_path.items():
        p = files_root / path
        if p.exists() and _sha(p.read_bytes()) != f["sha256"]:
            problems.append(f"hash mismatch for bundled file: {path}")
    # Pattern coverage, when recorded, must agree with the partition.
    # Bundles written before this evidence was recorded carry no
    # pattern_coverage key and are not failed for its absence.
    if "pattern_coverage" in exposure:
        recorded = exposure.get("pattern_coverage") or []
        # Merge note (harden x deepen): recompute from the validated
        # entries and read the recorded pack/coverage defensively, so a
        # corrupt bundle still fails with named problems here instead
        # of crashing the coverage check on malformed records.
        surface_pack = exposure.get("surface_pack")
        if not isinstance(surface_pack, dict):
            surface_pack = {}
        pack_patterns = surface_pack.get("patterns", [])
        if not isinstance(pack_patterns, list):
            pack_patterns = []
        pack_patterns = [
            p for p in pack_patterns
            if isinstance(p, dict) and isinstance(p.get("id"), str)
            and all(k in p for k in ("id", "kind", "pattern", "reason"))]
        expected = pattern_coverage(
            valid_entries, {"patterns": pack_patterns})
        expected_by_id = {c["pattern_id"]: c for c in expected}
        recorded_by_id = {}
        for cov in recorded:
            if not isinstance(cov, dict):
                problems.append(
                    "pattern coverage entry is not an object: "
                    f"{str(cov)[:80]}")
                continue
            pid = cov.get("pattern_id")
            if not isinstance(pid, (str, int, float, bool, type(None))):
                problems.append(
                    "pattern coverage entry has a non-scalar "
                    f"pattern_id: {str(pid)[:80]}")
                pid = repr(pid)
            if pid in recorded_by_id:
                problems.append(
                    f"pattern coverage lists {pid} more than once")
            recorded_by_id[pid] = cov
        for pid in sorted(set(expected_by_id) - set(recorded_by_id),
                          key=str):
            problems.append(
                f"pattern coverage is missing pattern: {pid}")
        for pid in sorted(set(recorded_by_id) - set(expected_by_id),
                          key=str):
            problems.append(
                f"pattern coverage lists unknown pattern: {pid}")
        for pid, exp in expected_by_id.items():
            rec = recorded_by_id.get(pid)
            if rec is None:
                continue
            for field in ("matched_files", "matched_file_count",
                          "total_line_hits", "total_occurrences"):
                if rec.get(field) != exp[field]:
                    problems.append(
                        f"pattern coverage does not match the recorded "
                        f"partition for: {pid} ({field})")
                    break
    # Partition in-set must equal manifest set
    in_set = {d["path"] for d in valid_entries
              if d.get("decision") in ("surface", "context")}
    if in_set != set(manifest_by_path):
        for path in sorted(in_set.symmetric_difference(set(manifest_by_path))):
            problems.append(f"partition/manifest disagreement for: {path}")
    notes.append(CANNOT_PROVE_STATEMENT)
    notes.append(COVERAGE_STATEMENT)
    return (not problems), problems, notes
