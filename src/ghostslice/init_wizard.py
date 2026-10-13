"""`ghostslice init` (v0.15): generate a tuned .ghostslice.json.

The wizard analyses a project with the tool's OWN engines — scan,
the import graph, entries.find_entry_candidates, detect.py flags,
exporter.resolve_modes via lint — and writes a profile where every
section is justified by printed evidence. It invents nothing: no
model is ever guessed, no threshold is pinned without a pattern
behind it, and the file it writes is loaded back through the real
profile loader before init reports success.

Section policy (conservative on purpose — a wrong profile entry is
worse than a missing one):

  entry_points  the top entry-point candidates (cap 5), each with
                the signal that nominated it (entries.py).
  ignore        vendored directory trees (detect.py path evidence):
                location is objective, so these leave every scan.
  modes         per-glob suggestions ONLY on strong evidence:
                - directories whose files are ALL flagged generated
                  (and single generated files in mixed dirs) ->
                  "exclude";
                - config-heavy directories (>= 70% config/data files
                  by count, >= 3 files, >= 500 estimated tokens) ->
                  "structure" (keys kept, values dropped).
                Docs stay full and tests stay strip-tests: those are
                already the built-in defaults, so pinning them would
                be noise.
  budget_tokens --budget wins. Otherwise the proposal is the current
                default-sliced total x 1.25, rounded up to two
                significant figures — headroom for growth, tight
                enough for check-budget / lint to catch a context
                blow-up. Below a 5,000-token sliced total a budget
                is noise and the section is omitted (the omission is
                printed, with the number).
  model         only from --model. Omitted otherwise: the tool
                default applies and init never invents a preference.
  lint          omitted in this version. A lint section pins a rule
                only when a project shows a *pattern* (e.g. a tree
                full of giant lines worth an L006 threshold), and
                the honest default for v1 is to leave lint at its
                documented defaults rather than freeze today's noise
                into config. The top lint findings are still printed
                as "biggest wins" guidance below.

The "biggest wins" list (top 3) mixes wins the profile itself banks
(ignored/excluded/structure-sliced tokens) with the largest
remaining lint findings — guidance only; init changes nothing in
the project except writing the profile file itself.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from .configslice import CONFIG_LANGUAGES
from .entries import find_entry_candidates
from .exporter import estimate_context_tokens
from .graph import build_graph
from .profile import PROFILE_NAME, Profile, load_profile
from .scanner import scan
from .slicer import slice_text

ENTRY_CAP = 5
MODE_ENTRY_CAP = 10
TINY_SLICED_TOTAL = 5000
BUDGET_HEADROOM = 1.25
CONFIG_DIR_MIN_FILES = 3
CONFIG_DIR_MIN_SHARE = 0.7
CONFIG_DIR_MIN_TOKENS = 500


def round_budget(n: float) -> int:
    """Round a token budget UP to two significant figures."""
    n = int(math.ceil(n))
    if n <= 0:
        return 0
    step = 10 ** max(0, len(str(n)) - 2)
    return int(math.ceil(n / step) * step)


# ---------------------------------------------------------------------------
# analysis
# ---------------------------------------------------------------------------

def _dir_stats(files) -> dict[str, dict]:
    """Aggregate per-directory stats over every ancestor directory."""
    dirs: dict[str, dict] = {}
    for f in files:
        parts = f.path.split("/")[:-1]
        for i in range(1, len(parts) + 1):
            d = "/".join(parts[:i])
            st = dirs.setdefault(d, {
                "files": 0, "tokens": 0, "generated": 0, "vendored": 0,
                "vendored_path": 0, "config": 0, "entries": [],
            })
            st["files"] += 1
            st["tokens"] += f.tokens
            st["entries"].append(f)
            if f.is_generated:
                st["generated"] += 1
            if f.is_vendored:
                st["vendored"] += 1
                if f.detect_evidence.get("vendored", "").startswith("vendored path"):
                    st["vendored_path"] += 1
            if f.language in CONFIG_LANGUAGES:
                st["config"] += 1
    return dirs


def _outermost(dirs: list[str]) -> list[str]:
    """Drop any dir that has an accepted ancestor in the list."""
    keep = []
    for d in sorted(dirs, key=lambda x: (x.count("/"), x)):
        if not any(d == k or d.startswith(k + "/") for k in keep):
            keep.append(d)
    return keep


def analyze_project(root, *, budget_override: int | None = None,
                    model_id: str | None = None,
                    scan_result=None, graph=None) -> dict:
    """Run the full analysis; returns the sections + evidence the
    profile would contain, before any interactive trimming."""
    root = Path(root)
    if scan_result is None:
        scan_result = scan(root)
    if graph is None:
        graph = build_graph(scan_result)
    _before, sliced_total = estimate_context_tokens(root)
    dirs = _dir_stats(scan_result.files)

    # -- entry points -------------------------------------------------
    candidates = find_entry_candidates(scan_result, graph=graph)
    top_entries = candidates[:ENTRY_CAP]
    entry_points = [c["path"] for c in top_entries]
    entry_why = [
        f"{c['path']}: {'; '.join(c['signals'])} (score {c['score']})"
        for c in top_entries
    ]
    if len(candidates) > ENTRY_CAP:
        entry_why.append(
            f"(+{len(candidates) - ENTRY_CAP} more candidate(s) below "
            f"the cap of {ENTRY_CAP} were left out)")

    # -- ignore: vendored trees (path evidence) -----------------------
    vendored_dirs = [d for d, st in dirs.items()
                     if st["files"] and st["vendored"] == st["files"]
                     and st["vendored_path"] > 0]
    vendored_dirs = _outermost(vendored_dirs)
    ignore = [f"{d}/**" for d in vendored_dirs]
    ignore_why = [
        f"{d}/: every scanned file ({dirs[d]['files']}) is flagged "
        f"vendored by path; ignoring it keeps ~{dirs[d]['tokens']:,} "
        f"estimated tokens out of every scan"
        for d in vendored_dirs
    ]
    ignored_prefixes = tuple(d + "/" for d in vendored_dirs)

    def _under_ignored(path: str) -> bool:
        return any(path.startswith(p) for p in ignored_prefixes)

    # -- modes: generated -> exclude ----------------------------------
    modes: dict[str, str] = {}
    mode_why: list[str] = []
    mode_spend: list[tuple[int, str, str]] = []  # (tokens, glob, why)
    generated_dirs = [d for d, st in dirs.items()
                      if st["files"] and st["generated"] == st["files"]
                      and not _under_ignored(d + "/x")]
    generated_dirs = _outermost(generated_dirs)
    covered_generated: set[str] = set()
    for d in generated_dirs:
        mode_spend.append((dirs[d]["tokens"], f"{d}/**",
                           f"{d}/: all {dirs[d]['files']} file(s) are flagged "
                           f"generated (detect.py header markers); exclude "
                           f"keeps ~{dirs[d]['tokens']:,} estimated tokens out"))
        for f in dirs[d]["entries"]:
            covered_generated.add(f.path)
    for f in scan_result.files:
        if f.is_generated and f.path not in covered_generated \
                and not _under_ignored(f.path):
            mode_spend.append((f.tokens, f.path,
                               f"{f.path}: flagged generated "
                               f"({f.detect_evidence.get('generated', 'marker')}); "
                               f"exclude keeps ~{f.tokens:,} estimated tokens out"))
    # -- modes: config-heavy dirs -> structure -------------------------
    config_dirs = [d for d, st in dirs.items()
                   if st["files"] >= CONFIG_DIR_MIN_FILES
                   and st["config"] / st["files"] >= CONFIG_DIR_MIN_SHARE
                   and st["tokens"] >= CONFIG_DIR_MIN_TOKENS
                   and not _under_ignored(d + "/x")
                   and d not in generated_dirs
                   # audit G10 F2: a config dir under a generated dir
                   # would fight the parent's exclude glob
                   # (profile modes are last-match-wins).
                   and not any(d.startswith(g + "/") for g in generated_dirs)]
    config_dirs = _outermost(config_dirs)
    structure_savings: dict[str, int] = {}
    for d in config_dirs:
        saved = 0
        for f in dirs[d]["entries"]:
            if f.language in CONFIG_LANGUAGES:
                try:
                    text = Path(f.abspath).read_text(encoding="utf-8", errors="replace")
                    saved += f.tokens - slice_text(f.path, text, "structure").sliced_tokens
                except OSError:
                    continue
        structure_savings[d] = max(0, saved)
        mode_spend.append((dirs[d]["tokens"], f"{d}/**",
                           f"{d}/: {dirs[d]['config']} of {dirs[d]['files']} files are "
                           f"config/data (yaml/toml/json/sql/shell); structure keeps "
                           f"keys only, saving ~{structure_savings[d]:,} of "
                           f"~{dirs[d]['tokens']:,} estimated tokens"))
    mode_spend.sort(key=lambda t: (-t[0], t[1]))
    capped = mode_spend[:MODE_ENTRY_CAP]
    generated_globs = {f"{d}/**" for d in generated_dirs} | {
        f.path for f in scan_result.files
        if f.is_generated and f.path not in covered_generated
        and not _under_ignored(f.path)}
    for _tokens, glob, _why in capped:
        modes[glob] = "exclude" if glob in generated_globs else "structure"
    # Audit G10 F4: verify every suggested glob actually matches its
    # intended target through the profile matcher — a file name with
    # fnmatch metacharacters (gen[1].py) would otherwise produce a
    # profile that claims an effect exports never apply.
    dropped_globs: list[str] = []
    if modes:
        probe_profile = Profile(modes=dict(modes))
        for glob, mode in list(modes.items()):
            target = glob[:-3] + "/__probe__" if glob.endswith("/**") else glob
            if probe_profile.mode_for(target) != mode:
                dropped_globs.append(glob)
                del modes[glob]
    kept = [(t, g, w) for t, g, w in capped if g in modes]
    mode_why = [why for _t, _g, why in kept]
    if len(mode_spend) > MODE_ENTRY_CAP:
        mode_why.append(
            f"(+{len(mode_spend) - MODE_ENTRY_CAP} lower-value mode "
            f"suggestion(s) left out by the cap of {MODE_ENTRY_CAP})")
    if dropped_globs:
        mode_why.append(
            f"(dropped mode suggestion(s) whose glob does not match "
            f"its target through the profile matcher: "
            f"{', '.join(dropped_globs)})")

    # -- budget ---------------------------------------------------------
    if budget_override is not None:
        budget_tokens: int | None = budget_override
        budget_why = (f"{budget_tokens:,} estimated tokens, from --budget "
                      f"(current default sliced context is {sliced_total:,})")
    elif sliced_total < TINY_SLICED_TOTAL:
        budget_tokens = None
        budget_why = (f"omitted: the default sliced context is only "
                      f"{sliced_total:,} estimated tokens "
                      f"(< {TINY_SLICED_TOTAL:,}), so a budget would be noise")
    else:
        budget_tokens = round_budget(sliced_total * BUDGET_HEADROOM)
        budget_why = (f"current default sliced context is {sliced_total:,} "
                      f"estimated tokens; budget set to {budget_tokens:,} "
                      f"(x{BUDGET_HEADROOM} headroom, rounded up) so "
                      f"check-budget catches context growth")

    # -- lint: evidence + wins ------------------------------------------
    from .lint import lint_project
    lint_payload = lint_project(root, profile=Profile(),
                                scan_result=scan_result, graph=graph)

    wins: list[dict] = []
    for d in vendored_dirs:
        wins.append({"tokens": dirs[d]["tokens"],
                     "text": f"ignore {d}/ (vendored): keeps ~{dirs[d]['tokens']:,} "
                             f"estimated tokens out of every scan"})
    for _tokens, glob, _why in kept:
        if modes.get(glob) == "exclude":
            wins.append({"tokens": _tokens,
                         "text": f"exclude {glob} (generated): keeps "
                                 f"~{_tokens:,} estimated tokens out of context"})
        elif modes.get(glob) == "structure":
            d = glob[:-3]
            wins.append({"tokens": structure_savings.get(d, 0),
                         "text": f"structure mode for {glob}: saves "
                                 f"~{structure_savings.get(d, 0):,} estimated tokens "
                                 f"(keys kept, values dropped)"})
    for f in lint_payload["findings"]:
        if f["savings"] <= 0 or f["path"] is None:
            continue
        if _under_ignored(f["path"]) or f["path"] in covered_generated:
            continue
        wins.append({"tokens": f["savings"],
                     "text": f"{f['rule']} {f['path']}: {f['action']} "
                             f"(~{f['savings']:,} estimated tokens)"})
    wins.sort(key=lambda w: (-w["tokens"], w["text"]))
    wins = [w for w in wins if w["tokens"] > 0][:3]

    return {
        "root": str(scan_result.root),
        "scan_files": len(scan_result.files),
        "scan_tokens": scan_result.total_tokens,
        "sliced_tokens": sliced_total,
        "candidates": candidates,
        "entry_points": entry_points,
        "entry_why": entry_why,
        "ignore": ignore,
        "ignore_why": ignore_why,
        "modes": modes,
        "mode_why": mode_why,
        "budget_tokens": budget_tokens,
        "budget_why": budget_why,
        "budget_locked": budget_override is not None,
        "model": model_id,
        "model_why": (f"{model_id}, from --model" if model_id else
                      "omitted: no --model given; the tool default applies "
                      "and init never invents a model preference"),
        "lint_why": ("omitted: lint stays at its documented defaults; "
                     "no single rule pattern was strong enough to pin "
                     "(findings are in the wins below)"),
        "lint_counts": lint_payload["counts"],
        "wins": wins,
    }


def assemble_profile(analysis: dict) -> dict:
    """The profile dict in the repo's canonical field order."""
    data: dict = {}
    if analysis["ignore"]:
        data["ignore"] = analysis["ignore"]
    if analysis["modes"]:
        data["modes"] = analysis["modes"]
    if analysis["model"]:
        data["model"] = analysis["model"]
    if analysis["budget_tokens"] is not None:
        data["budget_tokens"] = analysis["budget_tokens"]
    if analysis["entry_points"]:
        data["entry_points"] = analysis["entry_points"]
    return data


def justification_lines(analysis: dict) -> list[str]:
    lines = []
    for why in analysis["ignore_why"]:
        lines.append(f"ignore: {why}")
    for why in analysis["mode_why"]:
        lines.append(f"modes: {why}")
    lines.append(f"model: {analysis['model_why']}")
    lines.append(f"budget_tokens: {analysis['budget_why']}")
    for why in analysis["entry_why"]:
        lines.append(f"entry_points: {why}")
    lines.append(f"lint: {analysis['lint_why']}")
    return lines


# ---------------------------------------------------------------------------
# interactive trimming
# ---------------------------------------------------------------------------

def _ask(input_fn, out, prompt: str) -> str:
    print(prompt, end="", file=out, flush=True)
    try:
        return (input_fn() or "").strip()
    except (EOFError, StopIteration):
        return ""


def _interactive_trim(analysis: dict, input_fn, out) -> None:
    """Ask per section and trim `analysis` in place. Defaults match
    the --yes analysis exactly (empty answer = accept)."""
    cands = analysis["candidates"]
    if cands:
        top = analysis["entry_points"]
        ans = _ask(input_fn, out,
                   f"Entry points: include these {len(top)} "
                   f"({', '.join(top)})? [Y/n/count] ")
        if ans.lower() in ("n", "no"):
            analysis["entry_points"] = []
            analysis["entry_why"] = ["dropped interactively"]
        elif ans.isdigit():
            k = max(0, min(int(ans), len(cands)))
            analysis["entry_points"] = [c["path"] for c in cands[:k]]
            analysis["entry_why"] = [
                f"{c['path']}: {'; '.join(c['signals'])} (score {c['score']})"
                for c in cands[:k]] or ["dropped interactively"]
    if analysis["ignore"] or analysis["modes"]:
        ans = _ask(input_fn, out,
                   f"File rules: apply {len(analysis['ignore'])} ignore "
                   f"glob(s) and {len(analysis['modes'])} mode glob(s)? [Y/n] ")
        if ans.lower() in ("n", "no"):
            analysis["ignore"] = []
            analysis["ignore_why"] = []
            analysis["modes"] = {}
            analysis["mode_why"] = ["dropped interactively"]
    if analysis.get("budget_locked"):
        pass  # --budget pre-answers this section (audit G10 F3)
    elif analysis["budget_tokens"] is not None:
        ans = _ask(input_fn, out,
                   f"Budget: [{analysis['budget_tokens']}] tokens "
                   f"(Enter = accept, 'none' = omit, or a number) ")
        if ans.lower() == "none":
            analysis["budget_tokens"] = None
            analysis["budget_why"] = "omitted interactively"
        elif ans.isdigit() and int(ans) > 0:
            analysis["budget_tokens"] = int(ans)
            analysis["budget_why"] = f"{int(ans):,} estimated tokens, set interactively"
    else:
        ans = _ask(input_fn, out,
                   "Budget: [none] (Enter = omit, or a number of tokens) ")
        if ans.isdigit() and int(ans) > 0:
            analysis["budget_tokens"] = int(ans)
            analysis["budget_why"] = f"{int(ans):,} estimated tokens, set interactively"


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------

def _existing_summary(existing: Profile) -> list[str]:
    parts = []
    if existing.ignore:
        parts.append(f"{len(existing.ignore)} ignore glob(s)")
    if existing.modes:
        parts.append(f"{len(existing.modes)} mode glob(s)")
    if existing.model:
        parts.append(f"model {existing.model}")
    if existing.budget_tokens is not None:
        parts.append(f"budget_tokens {existing.budget_tokens:,}")
    if existing.entry_points:
        parts.append(f"{len(existing.entry_points)} entry point(s)")
    if existing.preset:
        parts.append(f"preset {existing.preset}")
    if existing.auto_shrink:
        parts.append("auto_shrink on")
    if existing.lint:
        parts.append(f"lint section ({len(existing.lint)} rule(s))")
    return parts or ["(no settings — an empty profile)"]


def run_init(root, *, yes: bool = False, force: bool = False,
             dry_run: bool = False, budget: int | None = None,
             model_id: str | None = None, interactive: bool = False,
             input_fn=None, out=None, err=None) -> tuple[int, dict | None]:
    """Generate (or preview) a .ghostslice.json for `root`.

    Returns (exit_code, payload). Exit codes: 0 written / previewed,
    2 refused (an existing profile without --force). Raises
    FileNotFoundError for a missing project directory."""
    out = out if out is not None else sys.stdout
    err = err if err is not None else sys.stderr
    root_p = Path(root)
    if not root_p.is_dir():
        raise FileNotFoundError(f"init: no such project directory: {root}")
    target = root_p / PROFILE_NAME

    if target.exists() and not target.is_file():
        print(f"init: {target} exists but is not a file — refusing "
              f"to touch it.", file=err)
        return 2, {"existing": str(target), "written": False}

    if target.is_file() and not force:
        try:
            existing = load_profile(root_p)
            summary = "; ".join(_existing_summary(existing))
        except Exception as exc:  # a corrupt existing file still blocks
            summary = f"(existing file could not be parsed: {exc})"
        print(f"init: {target} already exists — refusing to overwrite "
              f"without --force.", file=err)
        print(f"  existing profile: {summary}", file=err)
        return 2, {"existing": str(target), "written": False}

    analysis = analyze_project(root_p, budget_override=budget,
                               model_id=model_id)
    if interactive:
        _interactive_trim(analysis, input_fn or input, out)
    data = assemble_profile(analysis)
    text = json.dumps(data, indent=2) + "\n"
    payload = {
        "profile": data,
        "justifications": justification_lines(analysis),
        "wins": analysis["wins"],
        "written": False,
        "path": str(target),
        "interactive": interactive,
        "analysis": {
            "scan_files": analysis["scan_files"],
            "scan_tokens": analysis["scan_tokens"],
            "sliced_tokens": analysis["sliced_tokens"],
            "candidates": analysis["candidates"],
            "lint_counts": analysis["lint_counts"],
        },
    }

    print(f"init: analysed {analysis['scan_files']} file(s), "
          f"{analysis['scan_tokens']:,} estimated tokens "
          f"({analysis['sliced_tokens']:,} sliced by default).", file=out)
    if dry_run:
        print(f"\nWould write {target} (dry run — nothing written):", file=out)
        print(text, end="", file=out)
    else:
        try:
            target.write_text(text, encoding="utf-8")
        except OSError as exc:
            print(f"init: could not write {target}: {exc}", file=err)
            return 2, payload
        loaded = load_profile(root_p)
        ok = (loaded.ignore == data.get("ignore", [])
              and loaded.modes == data.get("modes", {})
              and loaded.model == data.get("model")
              and loaded.budget_tokens == data.get("budget_tokens")
              and loaded.entry_points == data.get("entry_points", []))
        if not ok:
            print(f"init: written profile failed its round-trip through "
                  f"the profile loader: {target}", file=err)
            return 2, payload
        payload["written"] = True
        print(f"\nWrote {target} (verified: loads through the profile "
              f"loader, sections intact).", file=out)
        print(text, end="", file=out)
    print("\nWhy these settings:", file=out)
    for line in payload["justifications"]:
        print(f"  {line}", file=out)
    if payload["wins"]:
        print("\nBiggest wins available (guidance only — init applied "
              "nothing beyond the profile above):", file=out)
        for w in payload["wins"]:
            print(f"  - {w['text']}", file=out)
    return 0, payload
