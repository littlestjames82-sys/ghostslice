"""Bundle generation, shards.json + PLAN.md writers, plan check, and
the GhostBus-shaped manifest export (a FILE only: nothing is sent,
no relay is contacted, dispatch is always recorded as false).
"""
from __future__ import annotations
import hashlib, json
from pathlib import Path

from .project import find_cycle
from .slicing import signatures_of
from .tokens import estimate_tokens, ESTIMATOR_NOTE
from . import __version__

def _sha(text: str) -> str:
    """Return the SHA-256 hex digest of *text* encoded as UTF-8."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def _levels(shards):
    """Iterative topological levels over final shard dicts.
    Returns (parallel_groups, max_parallelism, {id: level}). Bounded
    passes: a leftover dependency cycle cannot loop forever."""
    levels = {s["id"]: 0 for s in shards}
    for _ in range(len(shards)):
        changed = False
        for s in shards:
            deps = [levels[d] for d in s.get("depends_on", []) if d in levels]
            if deps:
                lv = 1 + max(deps)
                if lv > levels[s["id"]]:
                    levels[s["id"]] = lv; changed = True
        if not changed:
            break
    groups: dict[int, list[str]] = {}
    for s in shards:
        groups.setdefault(levels[s["id"]], []).append(s["id"])
    pg = [sorted(groups[k]) for k in sorted(groups)]
    return pg, max((len(g) for g in pg), default=0), levels

def _within(base: Path, target: Path) -> bool:
    """True when target resolves inside base (no '..' / symlink escape)."""
    try:
        target.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False

def compute_schedule_analytics(shards) -> dict:
    """Planning-side schedule analysis over a plan's dependency graph.

    Pure graph arithmetic on the shards as written: no shard is run,
    dispatched, or timed. Estimated tokens are used only as a relative
    work proxy (labelled as such), never as a wall-clock prediction.

    Returns total work, the critical path (the dependency chain whose
    summed estimated tokens are largest, in dependency-first order),
    its cost as the makespan lower bound under unlimited parallelism,
    the implied parallel speedup over doing all work sequentially,
    the single largest (bottleneck) shard, and the per-parallel-group
    makespan (the largest shard in each group). Deterministic: ties
    break on the lexicographically smallest path / shard id. A cyclic
    graph (a `check` failure) yields empty path fields and
    ``has_cycle: True`` instead of a bogus schedule.
    """
    rows = list(shards or [])
    ids = sorted(s["id"] for s in rows if s.get("id"))
    by_id = {s["id"]: s for s in rows if s.get("id")}
    cost = {i: int(by_id[i].get("estimated_tokens") or 0) for i in ids}
    deps = {i: sorted(d for d in (by_id[i].get("depends_on") or []) if d in by_id)
            for i in ids}
    total = sum(cost.values())
    bottleneck = None
    if ids:
        b = min(ids, key=lambda i: (-cost[i], i))
        bottleneck = {"shard": b, "estimated_tokens": cost[b]}
    groups: dict[str, int] = {}
    for i in ids:
        g = by_id[i].get("parallel_group")
        if g is not None:
            groups[str(g)] = max(groups.get(str(g), 0), cost[i])
    # Kahn topological order (dependency first), sorted for determinism.
    indeg = {i: len(deps[i]) for i in ids}
    dependents: dict[str, list[str]] = {i: [] for i in ids}
    for i in ids:
        for d in deps[i]:
            dependents[d].append(i)
    ready = sorted(i for i in ids if indeg[i] == 0)
    order: list[str] = []
    while ready:
        n = ready.pop(0)
        order.append(n)
        for m in sorted(dependents[n]):
            indeg[m] -= 1
            if indeg[m] == 0:
                ready.append(m)
        ready.sort()
    if len(order) != len(ids):
        return {"basis": "estimated_tokens as a relative work proxy; "
                         "not a wall-clock prediction",
                "total_work_tokens": total, "critical_path": [],
                "critical_path_tokens": None, "critical_path_length": 0,
                "makespan_tokens": None, "parallel_speedup": None,
                "bottleneck": bottleneck, "group_makespan_tokens": groups,
                "has_cycle": True}
    best_cost: dict[str, int] = {}
    best_path: dict[str, list[str]] = {}
    for i in order:
        cand = [(best_cost[d], best_path[d]) for d in deps[i]]
        if cand:
            # largest cost wins; ties -> lexicographically smallest path
            cand.sort(key=lambda cp: (-cp[0], cp[1]))
            pc, pp = cand[0]
            best_cost[i] = pc + cost[i]
            best_path[i] = pp + [i]
        else:
            best_cost[i] = cost[i]
            best_path[i] = [i]
    crit_path: list[str] = []
    crit_cost = 0
    if ids:
        ranked = sorted(ids, key=lambda i: (-best_cost[i], best_path[i]))
        crit_path = best_path[ranked[0]]
        crit_cost = best_cost[ranked[0]]
    return {"basis": "estimated_tokens as a relative work proxy; "
                     "not a wall-clock prediction",
            "total_work_tokens": total,
            "critical_path": crit_path,
            "critical_path_tokens": crit_cost,
            "critical_path_length": len(crit_path),
            "makespan_tokens": crit_cost,
            "parallel_speedup": (round(total / crit_cost, 3) if crit_cost else 1.0),
            "bottleneck": bottleneck,
            "group_makespan_tokens": groups,
            "has_cycle": False}

def split_if_needed(shard: dict, files, budget: int):
    """Fit step: if owned full content exceeds budget, try splitting
    the owned set into two halves by file (graph reason recorded).
    Returns (list_of_bundle_specs, unfittable_reason_or_None).
    A single file whose full content alone exceeds budget cannot be
    split further at file granularity: unfittable.
    Each spec: dict(files=[(rel, mode)], est_tokens, orig_tokens)
    """
    owns = shard["owns_files"]
    def spec_for(rels, shared):
        entries = []
        for r in rels:
            entries.append((r, "full", files[r].text))
        for r in shared:
            entries.append((r, "signatures", signatures_of(files[r].text, files[r].language)))
        est = sum(estimate_tokens(t) for _, _, t in entries)
        orig = sum(estimate_tokens(files[r].text) for r, _, _ in entries)
        return {"entries": entries, "est": est, "orig": orig}
    whole = spec_for(owns, shard["shared_files_readonly"])
    if whole["est"] <= budget:
        return [whole], None
    big = [r for r in owns if estimate_tokens(files[r].text) > budget]
    if big:
        return [whole], (f"single file(s) {big} exceed per-shard budget "
                         f"{budget} estimated tokens at full mode; cannot split below file granularity")
    if len(owns) < 2:
        return [whole], "owned set exceeds budget and cannot be split further"
    half = len(owns) // 2
    subs = [spec_for(sorted(owns)[:half], shard["shared_files_readonly"]),
            spec_for(sorted(owns)[half:], shard["shared_files_readonly"])]
    if all(s["est"] <= budget for s in subs):
        shard.setdefault("rules_fired", []).append(
            "fit-split: shard exceeded budget; split by owned-file halves")
        return subs, None
    return [whole], "owned set exceeds budget even after one fit-split"

def write_bundle(bundle_dir: Path, shard: dict, spec, bundle_task: str):
    """Write one shard bundle's ``files/`` tree under *bundle_dir*.

    Returns ``(rows, prompt_text)``: ``rows`` are the manifest rows
    (path, mode, token estimates, sha256; ``original_tokens`` is
    filled in by the caller) and ``prompt_text`` is the content for
    the bundle's ``PROMPT.md``. The caller writes ``manifest.json``
    and ``PROMPT.md`` itself; see :func:`write_plan`.
    """
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "files").mkdir(exist_ok=True)
    rows = []
    prompt_parts = [f"# Shard: {shard['title']}\n\n{bundle_task}\n"]
    for rel, mode, content in spec["entries"]:
        dest = bundle_dir / "files" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        orig = spec  # placeholder replaced below
        rows.append({"path": rel, "mode": mode,
                     "original_tokens": None, "sliced_tokens": estimate_tokens(content),
                     "sha256": _sha(content)})
        prompt_parts.append(f"\n## {rel} ({mode})\n\n```\n{content}\n```\n")
    return rows, "".join(prompt_parts)

def write_plan(plan: dict, project_root, out_dir):
    """Write shards/ output: per-shard bundles, shards.json, PLAN.md,
    bus-manifest.json. Returns (plan_summary_dict, exit_code).
    exit 1 if partial/unfittable (Slice --fit style discipline)."""
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    files = plan["files"]; budget = plan["budget_tokens"]
    final_shards = []
    id_map: dict[str, list[str]] = {}
    any_unfit = False
    for shard in plan["shards"]:
        specs, unfit = split_if_needed(shard, files, budget)
        if unfit:
            any_unfit = True
            plan["partial"] = True
            plan["conflicts"].append(f"unfittable: {shard['id']}: {unfit}")
        id_map[shard["id"]] = [shard["id"] if len(specs) == 1
                               else f"{shard['id']}-part{k+1}"
                               for k in range(len(specs))]
        for k, spec in enumerate(specs):
            sid = id_map[shard["id"]][k]
            bdir = out / sid
            rows, prompt = write_bundle(bdir, shard, spec, shard["task"])
            for row in rows:
                row["original_tokens"] = estimate_tokens(files[row["path"]].text)
            manifest = {
                "tool": "ghostshard-bundle", "ghostshard_version": __version__,
                "shard_id": sid, "files": rows,
                "total_original_tokens": sum(r["original_tokens"] for r in rows),
                "total_sliced_tokens": sum(r["sliced_tokens"] for r in rows),
                "estimator": ESTIMATOR_NOTE,
            }
            (bdir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            (bdir / "PROMPT.md").write_text(prompt, encoding="utf-8")
            fs = dict(shard)
            fs["id"] = sid
            fs["bundle"] = sid
            fs["estimated_tokens"] = manifest["total_sliced_tokens"]
            fs["original_tokens"] = manifest["total_original_tokens"]
            fs["unfittable"] = bool(unfit) if len(specs) == 1 else False
            fs.pop("_own_orig", None)
            if len(specs) > 1:
                fs["owns_files"] = sorted(r["path"] for r in rows if r["mode"] == "full")
                fs["shared_files_readonly"] = sorted(r["path"] for r in rows if r["mode"] != "full")
            final_shards.append(fs)
    # A fit-split renames a shard to <id>-partN: every depends_on that
    # named the original id must be expanded to ALL its parts (the
    # dependent needs the whole original shard's work), and parallel
    # groups must be recomputed over the final ids. Without this the
    # written plan fails `check` with unknown-shard errors and the
    # bus manifest points at shards that do not exist.
    for fs in final_shards:
        deps: list[str] = []
        for dep in fs.get("depends_on", []):
            for target in id_map.get(dep, [dep]):
                if target != fs["id"] and target not in deps:
                    deps.append(target)
        fs["depends_on"] = sorted(deps)
    parallel_groups, max_parallelism, levels = _levels(final_shards)
    for fs in final_shards:
        fs["parallel_group"] = levels[fs["id"]]
    plan_out = {
        "tool": "ghostshard", "version": __version__,
        "mode": plan["mode"],
        "mode_label": ("user-split (heuristic assignment of user subtasks to files)"
                       if plan["mode"] == "user-split"
                       else "auto-clustered (heuristic graph clustering, not a designed split)"),
        "project": str(project_root),
        "partial": plan["partial"],
        "budget_tokens_per_shard": budget,
        "estimator": ESTIMATOR_NOTE,
        "parallel_groups": parallel_groups,
        "max_parallelism": max_parallelism,
        "conflicts": plan["conflicts"],
        "shards": final_shards,
        "analytics": compute_schedule_analytics(final_shards),
        "totals": {
            "estimated_tokens": sum(s["estimated_tokens"] for s in final_shards),
            "original_tokens": sum(s["original_tokens"] for s in final_shards),
            "note": "totals are sums over per-shard bundle manifests; shared read-only files are counted once per shard that carries them",
        },
    }
    (out / "shards.json").write_text(json.dumps(plan_out, indent=2), encoding="utf-8")
    (out / "PLAN.md").write_text(render_plan_md(plan_out), encoding="utf-8")
    write_bus_manifest(out, plan_out)
    return plan_out, (1 if plan_out["partial"] else 0)

def render_plan_md(p: dict) -> str:
    """Render the human-readable ``PLAN.md`` text for a plan dict.

    Includes the mode label, a shard table, a Mermaid dependency
    diagram, conflicts and rules fired, and token totals.
    """
    lines = ["# GhostShard Plan", "",
             f"Mode: **{p['mode']}** - {p['mode_label']}",
             f"Partial: **{p['partial']}**",
             f"Max useful parallelism: **{p['max_parallelism']}** (largest parallel group)",
             f"Per-shard budget: {p['budget_tokens_per_shard']} estimated tokens",
             f"_{p['estimator']}_", "",
             "Planner only: this plan dispatches nothing and runs no agents.", "",
             "## Shards", "",
             "| Shard | Owns | Depends on | Est. tokens | Parallel group |",
             "|---|---|---|---|---|"]
    for s in p["shards"]:
        lines.append(f"| {s['id']} | {', '.join(s['owns_files']) or '-'} | "
                     f"{', '.join(s['depends_on']) or '-'} | {s['estimated_tokens']} | {s['parallel_group']} |")
    lines += ["", "## Dependency diagram", "", "```mermaid", "graph TD"]
    if not any(s["depends_on"] for s in p["shards"]):
        for s in p["shards"]:
            lines.append(f'    {s["id"].replace("-", "_")}["{s["id"]}"]')
    for s in p["shards"]:
        for d in s["depends_on"]:
            lines.append(f'    {d.replace("-", "_")} --> {s["id"].replace("-", "_")}')
    lines += ["```", ""]
    a = p.get("analytics")
    if a:
        lines += ["## Schedule analysis", "",
                  f"_{a.get('basis', '')}_", "",
                  f"Total work: {a.get('total_work_tokens')} estimated tokens",
                  f"Critical path: {' -> '.join(a.get('critical_path') or []) or '-'} "
                  f"({a.get('critical_path_tokens')} estimated tokens, "
                  f"{a.get('critical_path_length')} shard(s))",
                  f"Makespan lower bound (unlimited parallelism): {a.get('makespan_tokens')} estimated tokens",
                  f"Parallel speedup vs sequential: {a.get('parallel_speedup')}x"]
        if a.get("bottleneck"):
            lines.append(f"Bottleneck shard: {a['bottleneck']['shard']} "
                         f"({a['bottleneck']['estimated_tokens']} estimated tokens)")
        if a.get("has_cycle"):
            lines.append("WARNING: dependency cycle present; no schedule computed (see `check`).")
        lines += [""]
    lines += ["## Conflicts and rules fired", ""]
    items = list(p["conflicts"])
    for s in p["shards"]:
        items += [f"{s['id']}: {r}" for r in s.get("rules_fired", [])]
    lines += [f"- {i}" for i in items] or ["- none"]
    lines += ["", f"Total estimated tokens (sum of shard bundles): {p['totals']['estimated_tokens']}",
              f"Total original tokens: {p['totals']['original_tokens']}", ""]
    return "\n".join(lines)

def write_bus_manifest(out_dir, plan_out: dict) -> Path:
    """Write ``bus-manifest.json`` into *out_dir* and return its path.

    GhostBus-shaped job manifest. A FILE ONLY: nothing is sent, no
    relay is contacted, and every job carries ``"dispatch": false``
    plus the ``placeholder-seatbelt-review`` approval class.
    """
    jobs = [{
        "job_id": s["id"], "bundle_path": s["bundle"],
        "task": s["task"], "depends_on": s["depends_on"],
        "approval_class": "placeholder-seatbelt-review",
        "dispatch": False,
    } for s in plan_out["shards"]]
    doc = {"kind": "ghostbus-job-manifest", "ghostshard_version": __version__,
           "note": "File only. GhostShard never sends this; hand it to GhostBus at a separate gate.",
           "jobs": jobs}
    path = Path(out_dir) / "bus-manifest.json"
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return path

# ---------------------------------------------------------------- check
def check_plan(folder) -> dict:
    """Validate a plan folder and return the check result dict.

    Checks bundle manifests against their files (sha256 and token
    totals), unique shard ids, unique file ownership, that every
    ``depends_on`` target exists, that the dependency graph is
    acyclic, that ``shards.json`` estimates match the bundle
    manifests, that a present ``analytics`` block recomputes exactly
    from the shards, and that every job in a present bus manifest
    still carries ``dispatch: false``. Returns ``{"ok": bool,
    "errors": [str, ...], "shards_checked": int, "cycle": list |
    None}``. A missing or invalid ``shards.json`` returns ``ok:
    False`` with one error.

    Check consumes folders it did not write (hand-built, copied,
    possibly hostile), so it must NEVER raise on malformed input:
    every defect becomes an entry in errors. Paths taken from
    shards.json / manifests are containment-checked so a crafted
    plan cannot make check read files outside the folder.
    """
    folder = Path(folder)
    errors: list[str] = []
    sj = folder / "shards.json"
    if not sj.is_file():
        return {"ok": False, "errors": ["shards.json not found"]}
    try:
        plan = json.loads(sj.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
        return {"ok": False, "errors": [f"shards.json is not valid JSON: {e}"]}
    if not isinstance(plan, dict):
        return {"ok": False, "errors": ["shards.json is not a JSON object"]}
    raw_shards = plan.get("shards", [])
    if not isinstance(raw_shards, list):
        return {"ok": False, "errors": ["shards.json: 'shards' is not a list"]}
    shards = []
    for i, s in enumerate(raw_shards):
        if not isinstance(s, dict) or not isinstance(s.get("id"), str) or not s["id"]:
            errors.append(f"shards.json: shard entry {i} is malformed (missing string 'id')")
            continue
        shards.append(s)
    ids = [s["id"] for s in shards]
    if len(ids) != len(set(ids)):
        errors.append("duplicate shard ids")
    owners: dict[str, str] = {}
    for s in shards:
        owns = s.get("owns_files", [])
        if not isinstance(owns, list):
            errors.append(f"{s['id']}: 'owns_files' is not a list"); owns = []
        for f in owns:
            if f in owners:
                errors.append(f"ownership violation: {f} owned by both {owners[f]} and {s['id']}")
            owners[f] = s["id"]
        deps = s.get("depends_on", [])
        if not isinstance(deps, list):
            errors.append(f"{s['id']}: 'depends_on' is not a list"); deps = []
        for dep in deps:
            if dep not in ids:
                errors.append(f"{s['id']} depends on unknown shard {dep}")
    graph = {s["id"]: sorted(s.get("depends_on", [])) if isinstance(s.get("depends_on", []), list) else []
             for s in shards}
    cyc = find_cycle(graph)
    if cyc:
        errors.append("dependency cycle detected: " + " -> ".join(cyc))
    # Analytics, when present, must be exactly what the shards imply:
    # a hand-edited critical path or speedup is a stale plan, not a plan.
    if isinstance(plan.get("analytics"), dict):
        expected = compute_schedule_analytics(shards)
        for key, want in expected.items():
            if plan["analytics"].get(key) != want:
                errors.append(
                    f"analytics mismatch: {key} is {plan['analytics'].get(key)!r}, "
                    f"recomputed {want!r} from the shards")
    for s in shards:
        bundle = s.get("bundle", s["id"])
        if not isinstance(bundle, str) or not bundle:
            errors.append(f"{s['id']}: 'bundle' is malformed"); continue
        bdir = folder / bundle
        if not _within(folder, bdir):
            errors.append(f"{s['id']}: bundle path escapes plan folder: {bundle}"); continue
        mf = bdir / "manifest.json"
        if not mf.is_file():
            errors.append(f"{s['id']}: manifest.json missing"); continue
        try:
            man = json.loads(mf.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
            errors.append(f"{s['id']}: manifest.json is not valid JSON: {e}"); continue
        if not isinstance(man, dict):
            errors.append(f"{s['id']}: manifest.json is not a JSON object"); continue
        rows = man.get("files", [])
        if not isinstance(rows, list):
            errors.append(f"{s['id']}: manifest 'files' is not a list"); rows = []
        tot_s = tot_o = 0
        for row in rows:
            if (not isinstance(row, dict)
                    or not isinstance(row.get("path"), str)
                    or not isinstance(row.get("sha256"), str)
                    or not isinstance(row.get("sliced_tokens"), int)
                    or isinstance(row.get("sliced_tokens"), bool)
                    or not isinstance(row.get("original_tokens"), int)
                    or isinstance(row.get("original_tokens"), bool)):
                errors.append(f"{s['id']}: malformed manifest row: {row!r:.80}")
                continue
            fpath = bdir / "files" / row["path"]
            if not _within(bdir / "files", fpath):
                errors.append(f"{s['id']}: bundle file path escapes bundle: {row['path']}"); continue
            if not fpath.is_file():
                errors.append(f"{s['id']}: bundle file missing {row['path']}"); continue
            try:
                data = fpath.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError) as e:
                errors.append(f"{s['id']}: bundle file unreadable {row['path']}: {e}"); continue
            if _sha(data) != row["sha256"]:
                errors.append(f"{s['id']}: sha256 mismatch {row['path']}")
            if estimate_tokens(data) != row["sliced_tokens"]:
                errors.append(f"{s['id']}: sliced token mismatch {row['path']}")
            tot_s += row["sliced_tokens"]; tot_o += row["original_tokens"]
        if tot_s != man.get("total_sliced_tokens"):
            errors.append(f"{s['id']}: manifest sliced total mismatch")
        if tot_o != man.get("total_original_tokens"):
            errors.append(f"{s['id']}: manifest original total mismatch")
        if s.get("estimated_tokens") not in (None, man.get("total_sliced_tokens")):
            errors.append(f"{s['id']}: shards.json estimated tokens do not match bundle manifest")
    # Hard rule (planner-only): if a bus manifest is present, every job
    # in it must still carry dispatch: false. A tampered manifest that
    # flips dispatch must fail check, never pass silently.
    bm = folder / "bus-manifest.json"
    if bm.is_file():
        try:
            doc = json.loads(bm.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
            errors.append(f"bus-manifest.json is not valid JSON: {e}")
        else:
            if not isinstance(doc, dict) or doc.get("kind") != "ghostbus-job-manifest":
                errors.append("bus-manifest.json: unexpected kind (not a ghostbus-job-manifest)")
            jobs = doc.get("jobs", []) if isinstance(doc, dict) else []
            if not isinstance(jobs, list):
                errors.append("bus-manifest.json: 'jobs' is not a list")
            else:
                for j in jobs:
                    if not isinstance(j, dict) or j.get("dispatch") is not False:
                        jid = j.get("job_id", "?") if isinstance(j, dict) else "?"
                        errors.append(f"bus-manifest.json: job {jid} does not carry dispatch: false")
    return {"ok": not errors, "errors": errors,
            "shards_checked": len(shards),
            "cycle": cyc}
