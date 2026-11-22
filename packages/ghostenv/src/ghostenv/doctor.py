"""Doctor: compare the three name sets and classify every name.

Sets: used in code / defined in .env / documented in the example file.
Classifications (see PLAN.md): missing-in-env (hard or soft),
missing-in-example, stale-in-env, stale-in-example, case-mismatch,
duplicate, external. Findings carry names and line evidence only.
"""
from __future__ import annotations

from pathlib import Path

from . import NAMES_ONLY_STATEMENT, __version__
from .envparse import (find_example_file, load_config, parse_env_file)
from .scanner import scan_project


def _norm(name: str) -> str:
    """Normalise a name for case-mismatch pairing: upper-case it
    and treat ``-`` and ``_`` as the same separator."""
    return name.upper().replace("-", "_")


def _case_mismatches(sets: dict[str, set[str]]) -> list[dict]:
    """Groups that differ only by case or - vs _, across sets.

    Per PLAN, a mismatch is a name in ONE set differing from a name
    in ANOTHER set. Variants whose set membership is identical (the
    same spellings appear in exactly the same sets, e.g. both TOKEN
    and Token used in code and both defined and documented) are a
    consistent, if ugly, contract - not a mismatch - and are not
    reported.
    """
    membership: dict[str, dict[str, set[str]]] = {}
    for label, names in sets.items():
        for n in names:
            membership.setdefault(_norm(n), {}).setdefault(n, set()).add(
                label)
    pairs = []
    for variants in membership.values():
        if len(variants) < 2:
            continue
        member_sets = {frozenset(s) for s in variants.values()}
        if len(member_sets) > 1:
            pairs.append({"names": sorted(variants)})
    pairs.sort(key=lambda p: p["names"])
    return pairs


def build_report(project, env_file=None, example_file=None) -> dict:
    """Scan *project* and build the full names-only report dict.

    ``env_file`` / ``example_file`` override the defaults
    (``<project>/.env`` and the first example candidate in the
    project root). The returned dict is the JSON report shape:
    name sets, usages, findings grouped by classification,
    counts, ``blocking_reasons``, a one-line ``verdict``, and the
    matching ``exit_code`` (0 complete, 1 blocking findings).
    """
    project = Path(project)
    config = load_config(project)
    external = set(config.get("external") or [])
    scan = scan_project(project, extra_ignore=config.get("ignore"))

    env_path = Path(env_file) if env_file else project / ".env"
    ex_path = (Path(example_file) if example_file
               else find_example_file(project))
    env_res = parse_env_file(env_path)
    ex_res = (parse_env_file(ex_path) if ex_path is not None
              else parse_env_file(project / ".env.example"))

    used = set(scan["by_name"].keys())
    in_env = set(env_res.names)
    in_example = set(ex_res.names)

    findings: dict[str, list] = {
        "missing_in_env_hard": [],
        "missing_in_env_soft": [],
        "missing_in_example": [],
        "stale_in_env": [],
        "stale_in_example": [],
        "case_mismatch": [],
        "duplicate": [],
        "malformed": [],
        "external": sorted(external & (used | in_env | in_example)),
    }

    for name in sorted(used - in_env - external):
        sites = scan["by_name"][name]
        evidence = [{"file": s["file"], "line": s["line"],
                     "kind": s["kind"]} for s in sites]
        # Shell-only usage never makes a hard finding (PLAN: shell is
        # parser-lite, a $NAME is not certainly an env read). A single
        # source location can match several patterns (plain read plus
        # a || fallback marker), so default-ness is per location: a
        # location has a default if any pattern at it found one.
        non_shell = [s for s in sites if s["kind"] != "shell-var"]
        by_loc: dict[tuple, bool] = {}
        for s in non_shell:
            key = (s["file"], s["line"])
            by_loc[key] = by_loc.get(key, False) or s["has_default"]
        if non_shell and all(by_loc.values()):
            findings["missing_in_env_soft"].append(
                {"name": name, "sites": evidence,
                 "reason": "every read site supplies a default"})
        elif non_shell:
            findings["missing_in_env_hard"].append(
                {"name": name, "sites": evidence,
                 "reason": "read in code with no default at one or "
                           "more sites, and not defined in .env"})
        else:
            findings["missing_in_env_soft"].append(
                {"name": name, "sites": evidence,
                 "reason": "shell usage only (parser-lite)"})

    for name in sorted((used | in_env) - in_example - external):
        findings["missing_in_example"].append({"name": name})

    for name in sorted(in_env - used - in_example - external):
        findings["stale_in_env"].append(
            {"name": name,
             "note": "defined locally, not used in code or documented; "
                     "may be read by a tool, script, or host"})
    for name in sorted(in_example - used - in_env - external):
        findings["stale_in_example"].append({"name": name})

    findings["case_mismatch"] = _case_mismatches(
        {"code": used, "env": in_env, "example": in_example})
    mismatched = {n for p in findings["case_mismatch"]
                  for n in p["names"]}

    for label, res in (("env", env_res), ("example", ex_res)):
        for dup in res.duplicates():
            findings["duplicate"].append(
                {"name": dup["name"], "where": label,
                 "lines": dup["lines"]})
        if res.malformed:
            # Line numbers only: the content of a malformed line is
            # never shown (it may be a bare value with no name).
            findings["malformed"].append(
                {"where": label, "lines": list(res.malformed)})

    missing_files = []
    if not env_res.present:
        missing_files.append(".env")
    if not ex_res.present:
        missing_files.append("example file "
                               "(.env.example/.env.sample/.env.template)")

    # Blocking reasons, enumerated so the verdict can name exactly
    # what failed. A missing example file with anything to document
    # is hard too: the next clone cannot discover the contract.
    # (missing-in-example entries while an example file EXISTS are
    # listed as findings but do not block on their own, per PLAN:
    # exit 1 is for hard findings. Soft, stale, and external
    # findings never block.)
    blocking_reasons: list[str] = []
    if findings["missing_in_env_hard"]:
        blocking_reasons.append(
            f"{len(findings['missing_in_env_hard'])} name(s) used in "
            f"code, missing from .env, with no default at a read site")
    if not ex_res.present and findings["missing_in_example"]:
        blocking_reasons.append(
            f"example file missing and "
            f"{len(findings['missing_in_example'])} name(s) "
            f"undocumented")
    if findings["case_mismatch"]:
        blocking_reasons.append(
            f"{len(findings['case_mismatch'])} case-mismatch "
            f"pair(s) across code / .env / example")
    if findings["duplicate"]:
        blocking_reasons.append(
            f"{len(findings['duplicate'])} duplicate "
            f"definition(s)")
    malformed_total = sum(len(m["lines"])
                           for m in findings["malformed"])
    if malformed_total:
        blocking_reasons.append(
            f"{malformed_total} malformed line(s) with no "
            f"variable name")

    counts = {
        "used_in_code": len(used),
        "defined_in_env": len(in_env),
        "documented_in_example": len(in_example),
        "missing_in_env_hard": len(findings["missing_in_env_hard"]),
        "missing_in_env_soft": len(findings["missing_in_env_soft"]),
        "missing_in_example": len(findings["missing_in_example"]),
        "stale_in_env": len(findings["stale_in_env"]),
        "stale_in_example": len(findings["stale_in_example"]),
        "case_mismatch": len(findings["case_mismatch"]),
        "duplicate": len(findings["duplicate"]),
        "malformed": malformed_total,
        "dynamic_read_sites": len(scan["dynamic_sites"]),
        "files_scanned": scan["files_scanned"],
    }
    # Verdict and exit code are derived from the SAME list, so the
    # words can never disagree with the code (polish fix: a
    # duplicate-only project exited 1 while its verdict read
    # "contract complete").
    if blocking_reasons:
        verdict = ("contract incomplete: "
                   + "; ".join(blocking_reasons))
        exit_code = 1
    else:
        verdict = ("contract complete: no blocking findings found "
                   "by static scan")
        exit_code = 0

    return {
        "tool": "ghostenv",
        "version": __version__,
        "project": str(project),
        "names_only_statement": NAMES_ONLY_STATEMENT,
        "files": {
            "env": {"path": env_res.path, "present": env_res.present},
            "example": {"path": ex_res.path,
                        "present": ex_res.present},
        },
        "missing_files": missing_files,
        "sets": {
            "used_in_code": sorted(used),
            "defined_in_env": sorted(in_env),
            "documented_in_example": sorted(in_example),
            "external": sorted(external),
        },
        "usages": scan["findings"],
        "dynamic_sites": scan["dynamic_sites"],
        "findings": findings,
        "case_mismatch_names": sorted(mismatched),
        "counts": counts,
        "blocking_reasons": blocking_reasons,
        "verdict": verdict,
        "exit_code": exit_code,
        "notes": [
            "Static scan only: dynamic reads and tool/host reads are "
            "undercounted by design.",
            "Stale means 'not seen in code', not 'safe to delete'.",
            "Presence only: a present name says nothing about whether "
            "its (never inspected) value is correct.",
        ],
    }
