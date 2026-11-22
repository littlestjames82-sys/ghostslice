"""Human-readable rendering of a doctor report. Names only."""
from __future__ import annotations


def render_text(report: dict) -> str:
    """Render a ``check`` report as grouped, human-readable text
    ending with the verdict and the names-only statement."""
    c = report["counts"]
    out = []
    out.append(f"GhostEnv check: {report['project']}")
    for label in ("env", "example"):
        info = report["files"][label]
        state = "present" if info["present"] else "MISSING"
        out.append(f"  {label} file: {info['path']} [{state}]")
    out.append(
        f"  names: {c['used_in_code']} used in code, "
        f"{c['defined_in_env']} in .env, "
        f"{c['documented_in_example']} in example "
        f"({c['files_scanned']} files scanned, "
        f"{c['dynamic_read_sites']} dynamic read sites)")
    f = report["findings"]

    def section(title, items, fmt):
        if items:
            out.append(f"{title}:")
            for item in items:
                out.append(f"  - {fmt(item)}")

    section("MISSING-IN-ENV (hard)", f["missing_in_env_hard"],
            lambda i: f"{i['name']}  ({i['reason']}; first site "
                      f"{i['sites'][0]['file']}:{i['sites'][0]['line']})")
    section("missing-in-env (soft, has default)", f["missing_in_env_soft"],
            lambda i: f"{i['name']}  ({i['reason']})")
    section("missing-in-example", f["missing_in_example"],
            lambda i: i["name"])
    section("stale-in-env", f["stale_in_env"],
            lambda i: f"{i['name']}  ({i['note']})")
    section("stale-in-example", f["stale_in_example"],
            lambda i: i["name"])
    section("case-mismatch (likely typo pair)", f["case_mismatch"],
            lambda i: " vs ".join(i["names"]))
    section("duplicate definitions", f["duplicate"],
            lambda i: f"{i['name']} in {i['where']} file, "
                      f"lines {', '.join(str(x) for x in i['lines'])}")
    section("malformed lines (no variable name; content never "
            "shown)", f["malformed"],
            lambda i: f"{i['where']} file, lines "
                      f"{', '.join(str(x) for x in i['lines'])}")
    if f["external"]:
        out.append(f"external (host/CI provided): "
                   f"{', '.join(f['external'])}")
    out.append(f"Verdict: {report['verdict']}")
    out.append(report["names_only_statement"])
    return "\n".join(out)


def render_scan_text(report: dict) -> str:
    """Render a ``scan`` report as text: each name used in code
    with its first read site, plus any dynamic read sites."""
    out = [f"GhostEnv scan: {report['project']}",
           "Used in code:"]
    usages: dict[str, list] = {}
    for u in report["usages"]:
        usages.setdefault(u["name"], []).append(u)
    for name in report["sets"]["used_in_code"]:
        sites = usages.get(name, [])
        first = sites[0] if sites else None
        where = f" ({first['file']}:{first['line']}" + \
            (f", +{len(sites) - 1} more)" if len(sites) > 1 else ")") \
            if first else ""
        out.append(f"  - {name}{where}")
    if report["dynamic_sites"]:
        out.append(f"Dynamic read sites (name not a literal, not "
                   f"resolved): {len(report['dynamic_sites'])}")
        for d in report["dynamic_sites"]:
            out.append(f"  - {d['file']}:{d['line']}")
    out.append(report["names_only_statement"])
    return "\n".join(out)
