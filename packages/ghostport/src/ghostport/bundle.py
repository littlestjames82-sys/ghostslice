"""Per-unit bundle, GhostSlice-bundle shaped.

Layout: manifest.json + PROMPT.md + files/<rel> + UNIT.md
- unit files: full
- already-sequenced dependency units (earlier in the plan): signatures
- not-yet-ported caller units (later in the plan): signatures
- covering tests: full
Signatures slicing is extractive (AST): imports, class/function signatures
and first docstring lines. Nothing in the source project is modified.
"""
from __future__ import annotations

import ast
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .tokens import METHOD, estimate_tokens


def signatures_slice(text: str) -> str:
    """Return an extractive signatures-only slice of Python source.

    Keeps imports, class and function signatures, and the first line of
    each function docstring. Returns the source unchanged when it does
    not parse, so a bundle never silently drops a file.
    """
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return text
    out = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            out.append(ast.unparse(node))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            header = f"{'async def' if isinstance(node, ast.AsyncFunctionDef) else 'def'} {node.name}({ast.unparse(node.args)})"
            if node.returns:
                header += f" -> {ast.unparse(node.returns)}"
            out.append(header + ": ...")
            doc = ast.get_docstring(node)
            if doc:
                out.append(f'    """{doc.splitlines()[0]}"""')
        elif isinstance(node, ast.ClassDef):
            out.append(f"class {node.name}: ...")
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out.append(f"    def {sub.name}({ast.unparse(sub.args)}): ...")
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            out.append(ast.unparse(node).split("=")[0].strip() + " = ...")
    return "\n".join(out) + ("\n" if out else "")


def build_unit_bundle(project: Path, plan: dict, unit_id: str, out: Path) -> dict:
    """Write the bundle for ``unit_id`` into ``out`` and return its manifest.

    The manifest gains a ``bundle_manifest_sha256`` entry (the hash of
    the written manifest.json) before it is returned. Raises ValueError
    when ``unit_id`` is not a unit in ``plan``. Source files are read
    only; nothing in ``project`` is modified.
    """
    project, out = Path(project), Path(out)
    units = {u["id"]: u for u in plan["units"]}
    if unit_id not in units:
        raise ValueError(f"unknown unit: {unit_id} (known: {', '.join(sorted(units)) or 'none'})")
    unit = units[unit_id]
    mode_by_file: dict[str, str] = {}
    for f in unit["files"]:
        mode_by_file[f] = "full"
    for test in unit["covering_tests"]:
        mode_by_file[test] = "full"
    for other in plan["units"]:
        if other["id"] == unit_id:
            continue
        if other["id"] in unit["depends_on_units"] or other["id"] in unit["caller_units"]:
            for f in other["files"]:
                mode_by_file.setdefault(f, "signatures")
    out.mkdir(parents=True, exist_ok=True)
    (out / "files").mkdir(exist_ok=True)
    project_root = project.resolve()
    files_root = (out / "files").resolve()
    entries, prompt_parts = [], []
    for rel, mode in sorted(mode_by_file.items()):
        src = project / rel
        if not src.is_file():
            continue
        # Containment: a crafted/hand-edited plan entry such as "../evil.py"
        # (or an absolute path, or a symlink out of the tree) used to be read
        # from outside the project, copied into PROMPT.md, and written
        # outside the bundle's files/ directory. Refuse escaping entries.
        src_resolved = src.resolve()
        dest_resolved = (files_root / rel).resolve()
        if not src_resolved.is_relative_to(project_root):
            raise ValueError(f"bundle: file escapes the project: {rel}")
        if not dest_resolved.is_relative_to(files_root):
            raise ValueError(f"bundle: destination escapes the bundle: {rel}")
        original = src.read_text(encoding="utf-8", errors="replace")
        sliced = original if mode == "full" else signatures_slice(original)
        dest = out / "files" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(sliced, encoding="utf-8")
        entries.append({"path": rel, "mode": mode,
                        "original_tokens": estimate_tokens(original),
                        "sliced_tokens": estimate_tokens(sliced),
                        "sha256": hashlib.sha256(sliced.encode("utf-8")).hexdigest()})
        prompt_parts.append(f"## {rel} ({mode})\n\n```python\n{sliced}```\n")
    manifest = {
        "tool": "ghostport", "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": str(project), "token_method": METHOD,
        "unit": unit_id,
        "files": entries,
        "total_original_tokens": sum(e["original_tokens"] for e in entries),
        "total_sliced_tokens": sum(e["sliced_tokens"] for e in entries),
        "total_saved_tokens": sum(e["original_tokens"] - e["sliced_tokens"] for e in entries),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    (out / "PROMPT.md").write_text(f"# GhostPort unit {unit_id}\n\n" + "\n".join(prompt_parts), encoding="utf-8")
    (out / "UNIT.md").write_text(render_unit_md(plan, unit), encoding="utf-8")
    digest = hashlib.sha256((out / "manifest.json").read_bytes()).hexdigest()
    manifest["bundle_manifest_sha256"] = digest
    return manifest


def render_unit_md(plan: dict, unit: dict) -> str:
    """Render the UNIT.md checklist for one unit of ``plan`` as text."""
    test_cmd = plan.get("profile", {}).get("test_command") or "(none configured in .ghostslice.json port.test_command)"
    lines = [f"# UNIT {unit['id']} (order {unit['order']} of {len(plan['units'])})", "",
             "GhostPort is a planner: this checklist is for the human or agent doing the port.",
             "GhostPort itself never rewrites code.", "",
             "## Patterns to fix in this unit", ""]
    for hit in unit["hits"]:
        lines.append(f"- {hit['file']}:{hit['line']} [{hit['pattern_id']}] {hit['description']}")
    lines += ["", "## Contract notes (callers and dependencies, included as signatures)", ""]
    if unit["caller_units"]:
        for caller in unit["caller_units"]:
            lines.append(f"- Caller unit {caller} is NOT yet ported in plan order: keep the public contract it uses, or update it when its turn comes.")
    else:
        lines.append("- No touched caller units. Untouched callers may still exist.")
    if unit["depends_on_units"]:
        for dep in unit["depends_on_units"]:
            lines.append(f"- Dependency unit {dep} is sequenced BEFORE this unit: treat its ported form as stable context.")
    if unit["combined_from_cycle"]:
        lines += ["", f"## Cycle note: this unit combines a dependency cycle: {', '.join(unit['cycle_files'])}. Port these files together.", ""]
    lines += ["## Tests", "", f"- Covering tests (method: {unit['covering_test_method']}): "
              f"{', '.join(unit['covering_tests']) or 'none found'}",
              f"- Test command from profile (GhostPort does not run it; GhostVerify post does): {test_cmd}",
              "", "## State", "",
              "- [ ] planned", "- [ ] bundled", "- [ ] ported-claimed (a claim, not proof)",
              "- [ ] verified (ONLY from a GhostVerify post report, recorded via `ghostport verify`)",
              ""]
    return "\n".join(lines)
