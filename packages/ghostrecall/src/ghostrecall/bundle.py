"""Combined bundle export + check.

Layout:
  <out>/manifest.json   merged manifest (code + memory items)
  <out>/PROMPT.md       single merged prompt (code prompt, then memory)
  <out>/RECALL.md       human recall report (selected / not selected /
                         conflicts / blocked, with reasons)
  <out>/files/<file>    sliced memory items, relative names flattened
  <out>/slice_manifest.json  copy of the GhostSlice manifest, if a code
                         bundle was supplied via --slice-bundle

Memory items with secret findings are blocked (excluded, recorded).
Items without valid provenance are never written. Superseded items
are recorded in the manifest as excluded, never as current content.
"""
from __future__ import annotations
import hashlib, json
from pathlib import Path

from . import __version__
from .modes import slice_item
from .profile import load_profile
from .recall import select
from .sources import collect_items
from .tokens import METHOD, estimate, sha256_text

def _flat_name(item, idx: int) -> str:
    base = item.provenance.path.replace(":", "_").replace("/", "__")
    return f"{idx:03d}_{base}"

def _load_slice_bundle(slice_bundle):
    if not slice_bundle:
        return None, [], ""
    sb = Path(slice_bundle)
    mf = sb / "manifest.json"
    if not mf.exists():
        raise ValueError(f"slice bundle has no manifest.json: {slice_bundle}")
    try:
        data = json.loads(mf.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"slice bundle manifest unreadable: {slice_bundle}: {e}") from e
    if not isinstance(data, dict):
        raise ValueError(f"slice bundle manifest must be a JSON object: {slice_bundle}")
    files = data.get("files", [])
    if not isinstance(files, list):
        raise ValueError(f"slice bundle manifest 'files' must be a list: {slice_bundle}")
    prompt = ""
    pp = sb / "PROMPT.md"
    if pp.exists():
        prompt = pp.read_text(encoding="utf-8", errors="replace")
    code_items = []
    for f in files:
        if not isinstance(f, dict):
            raise ValueError(f"slice bundle manifest file entry must be an object: {slice_bundle}")
        code_items.append({
            "id": "code-" + str(f.get("path", "")),
            "source_type": "code",
            "path": f.get("path", ""),
            "mode": f.get("mode", "full"),
            "original_tokens": f.get("original_tokens", f.get("tokens_original")),
            "sliced_tokens": f.get("sliced_tokens", f.get("tokens")),
            "sha256": f.get("sha256"),
            "exported_file": None,
            "provenance": {"path": f.get("path", ""), "line": 1},
        })
    return data, code_items, prompt

def build_bundle(project, out, task: str = "", fit: int | None = None,
                 slice_bundle=None, mode: str | None = None) -> dict:
    """Build a bundle for *project* in *out* and return its manifest dict.

    Writes manifest.json, PROMPT.md, RECALL.md and the sliced items
    under ``files/`` (plus slice_manifest.json when *slice_bundle* is
    given). With *fit*, memory first downgrades to decision-only and
    then drops lowest-ranked non-pinned items; pinned rules are kept
    even if the budget is exceeded. Blocked and superseded items are
    recorded as excluded, never written as content. Also appends one
    line to the project's .ghostrecall-history.jsonl ledger.
    """
    from .sources import assert_project_root
    if fit is not None:
        # fit=0 used to be silently ignored and a negative fit silently
        # dropped everything; a budget must be a positive token count.
        if isinstance(fit, bool) or not isinstance(fit, (int, float)) \
                or int(fit) != fit or fit <= 0:
            raise ValueError(f"fit must be a positive token budget, got {fit!r}")
        fit = int(fit)
    root = assert_project_root(project)
    profile = load_profile(root)
    mode = mode or profile.get("default_mode", "full")
    items = collect_items(root, include_git=bool(profile.get("include_git", True)),
                          git_limit=int(profile.get("git_limit", 200)))
    selected, not_selected, conflicts = select(items, task, profile, mode=mode)

    memory_budget = None
    if fit:
        frac = float(profile.get("memory_budget_fraction", 0.2))
        memory_budget = int(fit * frac) if slice_bundle else int(fit)

    entries = []
    files_dir = Path(out) / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    total_sliced = 0
    kept, downgraded = [], []
    # First pass at requested mode; downgrade to decision-only on fit.
    for idx, entry in enumerate(selected):
        it = entry["item"]
        if it.status == "superseded":
            # Defence in depth (REPORT_B F1): select() already excludes
            # superseded items, but a superseded item must NEVER be
            # written as bundle content or marked pinned, whatever the
            # caller handed us. Record it as excluded instead.
            if not any(e["item"].id == it.id for e in not_selected):
                not_selected.append({"item": it, "reason": "superseded",
                                     "superseded_by": it.superseded_by})
            continue
        if it.blocked:
            continue
        sliced = slice_item(it, mode)
        entries.append((entry, mode, sliced))
    if memory_budget:
        total = sum(estimate(s) for _e, _m, s in entries)
        if total > memory_budget:
            new_entries = []
            for entry, m, s in entries:
                if m != "decision-only" and not entry["pinned"]:
                    s2 = slice_item(entry["item"], "decision-only")
                    new_entries.append((entry, "decision-only", s2))
                    downgraded.append(entry["item"].id)
                else:
                    new_entries.append((entry, m, s))
            entries = new_entries
            total = sum(estimate(s) for _e, _m, s in entries)
        if total > memory_budget:  # drop lowest-ranked non-pinned
            entries.sort(key=lambda t: (not t[0]["pinned"], -t[0]["score"]))
            while entries and sum(estimate(s) for _e, _m, s in entries) > memory_budget:
                popped = None
                for i in range(len(entries) - 1, -1, -1):
                    if not entries[i][0]["pinned"]:
                        popped = entries.pop(i); break
                if popped is None:
                    break
                not_selected.append({"item": popped[0]["item"], "reason": "over fit budget"})
            total = sum(estimate(s) for _e, _m, s in entries)

    manifest_items = []
    prompt_parts: list[str] = []
    for idx, (entry, m, sliced) in enumerate(entries):
        it = entry["item"]
        fname = _flat_name(it, idx)
        (files_dir / fname).write_text(sliced, encoding="utf-8")
        manifest_items.append({
            "id": it.id, "source_type": it.source_type, "path": it.provenance.path,
            "mode": m, "original_tokens": estimate(it.text),
            "sliced_tokens": estimate(sliced), "sha256": sha256_text(sliced),
            "exported_file": f"files/{fname}",
            "provenance": it.provenance.to_dict(),
            "pinned": entry["pinned"], "score": entry["score"],
            "status": it.status, "title": it.title,
        })
        total_sliced += estimate(sliced)
        prompt_parts.append(f"\n\n## [{it.source_type}] {it.title} "
                            f"(source: {it.provenance.path}"
                            + (f":{it.provenance.line}" if it.provenance.line else "")
                            + (f", commit {it.provenance.commit[:10]}" if it.provenance.commit else "")
                            + f", mode: {m})\n\n{sliced}")
        kept.append(it.id)

    excluded = [{
        "id": e["item"].id, "path": e["item"].provenance.path,
        "source_type": e["item"].source_type, "mode": "exclude",
        "reason": e["reason"], "status": e["item"].status,
        "provenance": e["item"].provenance.to_dict(),
        "secret_findings": e["item"].secret_findings,
    } for e in not_selected]

    slice_manifest, code_items, code_prompt = _load_slice_bundle(slice_bundle)
    out_path = Path(out)
    out_path.mkdir(parents=True, exist_ok=True)
    merged_prompt = ""
    if code_prompt:
        merged_prompt += "# Code context (GhostSlice bundle)\n\n" + code_prompt
    merged_prompt += "\n\n# Project memory (GhostRecall)\n" + "".join(prompt_parts)
    prompt_text = merged_prompt.lstrip("\n")
    (out_path / "PROMPT.md").write_text(prompt_text, encoding="utf-8")
    if slice_manifest is not None:
        (out_path / "slice_manifest.json").write_text(
            json.dumps(slice_manifest, indent=2), encoding="utf-8")

    manifest = {
        "tool": "ghostrecall", "version": __version__, "kind": "combined-bundle",
        "task": task, "estimator": METHOD,
        "prompt_sha256": sha256_text(prompt_text),
        "memory_budget": memory_budget, "fit": fit,
        "items": code_items + manifest_items,
        "excluded": excluded,
        "conflicts": conflicts,
        "downgraded": downgraded,
        "totals": {
            "memory_original_tokens": sum(i["original_tokens"] for i in manifest_items),
            "memory_sliced_tokens": total_sliced,
            "memory_items": len(manifest_items),
            "code_items": len(code_items),
            "prompt_tokens_estimate": estimate(prompt_text),
        },
    }
    (out_path / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    report = [f"# GhostRecall report\n\nTask: {task or '(none)'}\n",
              f"Memory items selected: {len(manifest_items)} "
              f"({total_sliced} estimated sliced tokens)\n"]
    report.append("\n## Selected\n")
    for i in manifest_items:
        pin = " [pinned rule]" if i["pinned"] else ""
        report.append(f"- {i['title']} ({i['source_type']}, {i['path']}, mode {i['mode']}){pin}")
    report.append("\n## Not selected\n")
    for e in excluded:
        report.append(f"- {e['path']}: {e['reason']}")
    if conflicts:
        report.append("\n## Conflicts / superseded\n")
        for c in conflicts:
            if c.get("type") == "possible-contradiction":
                report.append(f"- {c['type']}: {c.get('current', '')} vs "
                              f"{c.get('other', '')} (signal: {c.get('signal', '')}, "
                              f"shared terms: {', '.join(c.get('shared_terms', []))}, "
                              f"opposing terms: {', '.join(c.get('opposing_terms', []))}). {c['note']}")
            else:
                report.append(f"- {c['type']}: {c.get('current', '')} supersedes/relates {c.get('superseded', '')}. {c['note']}")
    (out_path / "RECALL.md").write_text("\n".join(report) + "\n", encoding="utf-8")

    _append_ledger(root, manifest)
    return manifest

def _append_ledger(root: Path, manifest: dict) -> None:
    try:
        line = json.dumps({"tool": "ghostrecall", "version": __version__,
                           "task": manifest["task"], "totals": manifest["totals"],
                           "items": [i["id"] for i in manifest["items"]
                                     if i["source_type"] != "code"]})
        with open(root / ".ghostrecall-history.jsonl", "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass

def check_bundle(bundle) -> tuple[bool, list[str]]:
    """Verify the bundle folder at *bundle* against its manifest.json.

    Returns ``(ok, problems)``: ok is True only when every exported
    file is present with a matching sha256 and estimated token count,
    every item carries provenance, and PROMPT.md matches the recorded
    prompt hash and token estimate.
    """
    b = Path(bundle)
    problems: list[str] = []
    mf = b / "manifest.json"
    if not mf.exists():
        return False, ["manifest.json missing"]
    try:
        data = json.loads(mf.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return False, [f"manifest unreadable: {e}"]
    if not isinstance(data, dict):
        return False, ["manifest is not a JSON object"]
    raw_items = data.get("items", [])
    if not isinstance(raw_items, list):
        return False, ["manifest 'items' is not a list"]
    for item in raw_items:
        if not isinstance(item, dict):
            problems.append(f"manifest item is not an object: {item!r}")
            continue
        ef = item.get("exported_file")
        if not ef:
            continue  # code items live in the referenced Slice bundle
        p = b / ef
        if not p.is_file():
            problems.append(f"missing exported file: {ef}")
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            problems.append(f"unreadable exported file: {ef}: {e}")
            continue
        if hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest() != item.get("sha256"):
            problems.append(f"sha256 mismatch: {ef}")
        if estimate(text) != item.get("sliced_tokens"):
            problems.append(f"token total mismatch: {ef} "
                            f"(manifest {item.get('sliced_tokens')}, actual {estimate(text)})")
        prov = item.get("provenance") or {}
        if not isinstance(prov, dict):
            problems.append(f"provenance missing: {item.get('id')}")
            prov = {}
        if not (prov.get("commit") or (prov.get("path") and prov.get("line"))):
            problems.append(f"provenance missing: {item.get('id')}")
    prompt_path = b / "PROMPT.md"
    if not prompt_path.is_file():
        problems.append("PROMPT.md missing")
    else:
        # F4: PROMPT.md is bundle content, not a bystander. Verify it
        # against the manifest like any exported file: the recorded
        # prompt sha256 when present, and always the recorded
        # totals.prompt_tokens_estimate (present in manifests written
        # before prompt_sha256 existed, so tampering with an older
        # bundle is caught too).
        try:
            prompt_text = prompt_path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            problems.append(f"PROMPT.md unreadable: {e}")
            return (not problems), problems
        recorded_sha = data.get("prompt_sha256")
        if recorded_sha and sha256_text(prompt_text) != recorded_sha:
            problems.append("sha256 mismatch: PROMPT.md")
        totals = data.get("totals")
        expected_tokens = totals.get("prompt_tokens_estimate") if isinstance(totals, dict) else None
        if expected_tokens is not None and estimate(prompt_text) != expected_tokens:
            problems.append(f"token total mismatch: PROMPT.md "
                            f"(manifest {expected_tokens}, actual {estimate(prompt_text)})")
    return (not problems), problems
