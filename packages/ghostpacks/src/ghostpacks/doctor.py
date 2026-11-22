"""Doctor checks for GhostPacks, mirroring `ghostslice doctor`.

For a pack: lint, GhostSlice version-range compatibility against a
stated current version, Bench freshness, plugin references that exist
locally (checked for presence only, never loaded or run).

For a project: profile parses under the GhostSlice schema, lockfile
parses, every recorded pack still lints from its recorded source when
that source is still on disk, and no recorded pack is left half-merged
(profile hash drift is reported as a warning with the remedy, matching
remove's clean-reversal rule).

Out-of-range or stale findings are warnings with the range/date
printed, never silent passes and never hard failures on their own.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from .manager import load_lockfile, load_project_profile
from .pack import (_score_claim, find_packs, lint_pack, load_pack)

DEFAULT_SLICE_VERSION = "1.0.6"
STALE_DAYS = 365
BENCH_STALE_DAYS = 180


def _version_tuple(text: str) -> tuple:
    parts = []
    for piece in str(text).strip().lstrip("v").split("."):
        m = re.match(r"\d+", piece)
        parts.append(int(m.group()) if m else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def version_in_range(version: str, range_spec: str | None) -> bool | None:
    """Evaluate a simple range like '>=1.0.0,<2.0.0'. None = unknown
    spec shape (reported, not guessed)."""
    if not range_spec:
        return None
    cur = _version_tuple(version)
    for clause in str(range_spec).split(","):
        clause = clause.strip()
        if not clause:
            continue
        m = re.match(r"(>=|<=|==|>|<)?\s*(\S+)$", clause)
        if not m:
            return None
        op, want = m.group(1) or "==", _version_tuple(m.group(2))
        ok = {">=": cur >= want, "<=": cur <= want, ">": cur > want,
              "<": cur < want, "==": cur == want}[op]
        if not ok:
            return False
    return True


def doctor_pack(pack_dir, slice_version=DEFAULT_SLICE_VERSION,
                today=None) -> dict:
    """Check one pack folder; returns {target, kind, checks, ok}.

    Each check is {name, status, detail} with status ok / warn / error.
    """
    today = today or date.today()
    errors, warnings = lint_pack(pack_dir)
    checks = [{"name": "lint", "status": "ok" if not errors else "error",
               "detail": "; ".join(errors) if errors else "pack is valid"}]
    if errors:
        return {"target": str(pack_dir), "kind": "pack",
                "checks": checks, "ok": False}
    pack = load_pack(pack_dir)
    in_range = version_in_range(slice_version, pack.slice_range)
    if pack.slice_range is None:
        checks.append({"name": "ghostslice-range", "status": "warn",
                       "detail": "pack names no GhostSlice version range"})
    elif in_range:
        checks.append({"name": "ghostslice-range", "status": "ok",
                       "detail": f"GhostSlice {slice_version} is inside "
                                 f"the pack range {pack.slice_range}"})
    elif in_range is False:
        checks.append({"name": "ghostslice-range", "status": "warn",
                       "detail": f"GhostSlice {slice_version} is OUTSIDE "
                                 f"the pack range {pack.slice_range}"})
    else:
        checks.append({"name": "ghostslice-range", "status": "warn",
                       "detail": f"cannot parse pack range {pack.slice_range!r}"})
    pack_date = pack.manifest.get("date")
    if isinstance(pack_date, str):
        try:
            age = (today - date.fromisoformat(pack_date)).days
            if age > STALE_DAYS:
                checks.append({"name": "freshness", "status": "warn",
                               "detail": f"pack date {pack_date} is {age} days old; "
                                         "stack packs rot as frameworks release majors"})
            else:
                checks.append({"name": "freshness", "status": "ok",
                               "detail": f"pack date {pack_date}"})
        except ValueError:
            checks.append({"name": "freshness", "status": "warn",
                           "detail": f"unparseable pack date {pack_date!r}"})
    score, report = _score_claim(pack.manifest)
    if pack.score_status == "unscored":
        checks.append({"name": "bench", "status": "warn",
                       "detail": "unscored: no Bench report backs this pack; "
                                 "treat its savings as unmeasured"})
    else:
        bench_date = None
        if isinstance(pack.manifest.get("bench"), dict):
            bench_date = pack.manifest["bench"].get("date")
        detail = f"scored ({score}) from {report}"
        status = "ok"
        if isinstance(bench_date, str):
            try:
                age = (today - date.fromisoformat(bench_date)).days
                detail += f", bench date {bench_date}"
                if age > BENCH_STALE_DAYS:
                    status = "warn"
                    detail += f" is {age} days old; re-bench before trusting it"
            except ValueError:
                pass
        checks.append({"name": "bench", "status": status, "detail": detail})
    for ref in pack.profile.get("plugins") or []:
        exists = (pack.path / ref).is_file()
        checks.append({"name": "plugin-ref", "status": "ok" if exists else "warn",
                       "detail": f"plugin reference {ref!r} "
                                 + ("exists in the pack folder (presence checked only, "
                                    "never loaded)" if exists else
                                    "is not in the pack folder; a project must supply it locally")})
    return {"target": str(pack_dir), "kind": "pack", "checks": checks,
            "ok": all(c["status"] != "error" for c in checks)}


def doctor_project(project, library_dirs=(), slice_version=DEFAULT_SLICE_VERSION,
                   today=None) -> dict:
    """Check one project folder; same report shape as doctor_pack.

    Also lists the packs available in *library_dirs* as informational
    checks. Doctor never raises on a broken profile or lockfile: the
    failure becomes an error check instead.
    """
    project = Path(project)
    checks = []
    if not project.is_dir():
        return {"target": str(project), "kind": "project",
                "checks": [{"name": "target", "status": "error",
                            "detail": "not a project folder"}],
                "ok": False}
    try:
        _profile, raw = load_project_profile(project)
        checks.append({"name": "profile", "status": "ok",
                       "detail": "profile parses under the GhostSlice schema"
                                 if raw is not None else
                                 "no .ghostslice.json yet (packs can create one)"})
        profile_ok = True
    except Exception as exc:  # loud in output, doctor itself must not crash
        checks.append({"name": "profile", "status": "error", "detail": str(exc)})
        profile_ok = False
    try:
        lock = load_lockfile(project)
        checks.append({"name": "lockfile", "status": "ok",
                       "detail": f"{len(lock['packs'])} pack merge(s) recorded"})
    except Exception as exc:
        checks.append({"name": "lockfile", "status": "error", "detail": str(exc)})
        lock = {"packs": []}
    import hashlib
    current_hash = None
    profile_path = project / ".ghostslice.json"
    if profile_path.is_file():
        current_hash = hashlib.sha256(profile_path.read_bytes()).hexdigest()
    for entry in lock["packs"]:
        pid = entry.get("pack_id", "?")
        source = entry.get("source")
        if source and Path(source).is_dir():
            errs, _w = lint_pack(source)
            checks.append({"name": f"pack:{pid}", "status": "error" if errs else "ok",
                           "detail": "; ".join(errs) if errs else
                                     f"recorded source {source} still lints clean"})
        else:
            checks.append({"name": f"pack:{pid}", "status": "warn",
                           "detail": f"recorded source {source!r} is no longer on "
                                     "disk; the lockfile entry and backup remain "
                                     "the record of the merge"})
        if entry is lock["packs"][-1] and current_hash and \
                current_hash != entry.get("profile_hash_after"):
            checks.append({"name": f"drift:{pid}", "status": "warn",
                           "detail": "profile was edited after the latest merge; "
                                     "`remove` will refuse a clean reversal and "
                                     "say why (use --force only deliberately)"})
    for folder in find_packs(library_dirs):
        try:
            pack = load_pack(folder)
        except Exception:
            continue
        checks.append({"name": f"available:{pack.id}", "status": "ok",
                       "detail": pack.summary_line()})
    return {"target": str(project), "kind": "project", "checks": checks,
            "ok": profile_ok and all(c["status"] != "error" for c in checks)}


def format_report(report: dict) -> str:
    """Render a doctor report dict as the plain-text block the CLI prints."""
    lines = [f"ghostpacks doctor: {report['target']} ({report['kind']})"]
    for check in report["checks"]:
        lines.append(f"  [{check['status'].upper():5}] {check['name']}: {check['detail']}")
    lines.append("doctor: " + ("OK" if report["ok"] else "problems found"))
    return "\n".join(lines)
