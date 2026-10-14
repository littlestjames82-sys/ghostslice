"""Doctor (v1.0): one-screen environment + project health check.

`ghostslice doctor <project>` answers "is this setup healthy, and
if not, what do I do about it?" in one pass: the Python runtime
vs the supported floor, the GhostSlice version (and, in a source
checkout, whether pyproject.toml agrees with it), the token
estimator stamp, the local price table, the project profile, the
content cache, the savings ledger, the plugins the profile names,
git hygiene, and workspace detection.

Every check reports ok / warn / fail plus a one-line remedy for
warn and fail. Doctor NEVER writes: it reads files and stats, and
the only code it runs beyond GhostSlice's own parsers is the
plugin load — deliberately, because "will this project's plugins
load?" is only answerable by loading them exactly the way every
other command does (plugins are user code; see the trust warning
in README "Plugins"). Exit semantics: 0 = no failed check,
1 = at least one fail, 2 = usage errors (handled by the CLI).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from . import __version__
from .tokens import METHOD, METHOD_VERSION

# The supported Python floor. Kept in step with pyproject.toml's
# requires-python; the version-agreement check below flags drift
# between the package version and pyproject, and the README states
# the same floor — three tellings of one fact, this is the code one.
MIN_PYTHON = (3, 10)

OK, WARN, FAIL = "ok", "warn", "fail"


def _check(cid: str, label: str, status: str, detail: str,
           remedy: str | None = None) -> dict:
    out = {"id": cid, "label": label, "status": status, "detail": detail}
    if remedy:
        out["remedy"] = remedy
    return out


def _project_section_version(pyproject: Path) -> tuple[str | None, str | None]:
    """(name, version) from a pyproject's [project] table, parsed
    with a deliberately small line reader: stdlib tomllib exists
    only on 3.11+, and doctor must run on the 3.10 floor. Only the
    [project] table's own name/version lines count; anything
    ambiguous returns None rather than a guess."""
    try:
        text = pyproject.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None, None
    name = version = None
    in_project = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            in_project = stripped == "[project]"
            continue
        if not in_project:
            continue
        m = re.match(r'^(name|version)\s*=\s*"([^"]*)"', stripped)
        if m:
            if m.group(1) == "name":
                name = m.group(2)
            else:
                version = m.group(2)
    return name, version


def checkout_pyproject() -> Path | None:
    """The pyproject.toml of a GhostSlice SOURCE CHECKOUT, when the
    running code lives in one (src/ghostslice -> repo root). None
    for an installed build, where there is no checkout to agree
    with."""
    cand = Path(__file__).resolve().parents[2] / "pyproject.toml"
    if not cand.is_file():
        return None
    name, _version = _project_section_version(cand)
    return cand if name == "ghostslice" else None


def _required_python() -> tuple[int, int]:
    """The floor the running build declares: Requires-Python from
    installed metadata when present, else MIN_PYTHON."""
    try:
        import importlib.metadata as md
        req = md.metadata("ghostslice").get("Requires-Python")
    except Exception:
        req = None
    if req:
        m = re.search(r">=\s*(\d+)\.(\d+)", req)
        if m:
            return int(m.group(1)), int(m.group(2))
    return MIN_PYTHON


def _python_check() -> dict:
    req = _required_python()
    cur = (sys.version_info.major, sys.version_info.minor)
    detail = (f"Python {sys.version.split()[0]} "
              f"(requires >={req[0]}.{req[1]})")
    if cur >= req:
        return _check("python", "Python runtime", OK, detail)
    return _check(
        "python", "Python runtime", FAIL, detail,
        f"run GhostSlice with Python {req[0]}.{req[1]} or newer")


def _version_check() -> dict:
    label = "GhostSlice version"
    py = checkout_pyproject()
    if py is None:
        return _check("version", label, OK,
                      f"{__version__} (installed build; no source "
                      "checkout to cross-check)")
    _name, py_version = _project_section_version(py)
    if py_version is None:
        return _check("version", label, WARN,
                      f"{__version__}; pyproject.toml states no "
                      "project version",
                      "set version in pyproject.toml [project] to "
                      f"{__version__}")
    if py_version != __version__:
        return _check(
            "version", label, FAIL,
            f"package reports {__version__} but pyproject.toml "
            f"says {py_version}",
            "align the two: bump pyproject.toml [project] version "
            "or ghostslice.__version__ so they match")
    return _check("version", label, OK,
                  f"{__version__} (pyproject.toml agrees)")


def _estimator_check() -> dict:
    return _check("estimator", "Token estimator", OK,
                  f"method v{METHOD_VERSION}: {METHOD}")


def _prices_check() -> dict:
    """Independent of the CLI's own load: doctor re-reads the file
    the resolver picks, so a corrupt price table is a reported
    fail here instead of a dead CLI."""
    from .pricing import find_prices_file, models
    label = "Price table"
    path = find_prices_file()
    if not Path(path).is_file():
        return _check("prices", label, FAIL,
                      f"no prices file found (resolver picked {path})",
                      "restore prices.json next to the package (or "
                      "in the working directory)")
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return _check("prices", label, FAIL,
                      f"{path}: cannot parse ({exc})",
                      "fix prices.json: it must be a JSON object "
                      "with an as_of date and a models list")
    if not isinstance(data, dict):
        return _check("prices", label, FAIL,
                      f"{path}: top level is not a JSON object",
                      "fix prices.json: it must be a JSON object "
                      "with an as_of date and a models list")
    found = models(data)
    as_of = data.get("as_of")
    if not found:
        return _check("prices", label, FAIL,
                      f"{path}: no models listed",
                      "add at least one model entry to prices.json "
                      "(id, input_per_mtok_usd, output_per_mtok_usd)")
    if not as_of:
        return _check("prices", label, WARN,
                      f"{path}: {len(found)} model(s), but no as_of "
                      "date stamped",
                      "add an \"as_of\" date to prices.json so cost "
                      "lines can be labelled honestly")
    return _check("prices", label, OK,
                  f"{len(found)} model(s), prices as of {as_of} "
                  f"(local snapshot, not live): {path}")


def _profile_check(root: Path) -> tuple[dict, object | None]:
    """Returns (check, profile-or-None). The profile object rides
    along so the plugins check reads the same parse."""
    from .profile import PROFILE_NAME, load_profile
    label = "Profile"
    candidate = root / PROFILE_NAME
    if not candidate.is_file():
        return _check("profile", label, OK,
                      "no .ghostslice.json; built-in defaults apply"), None
    try:
        profile = load_profile(root)
    except ValueError as exc:
        return _check("profile", label, FAIL, str(exc),
                      "fix the field named above, or regenerate "
                      "with `ghostslice init --force`"), None
    keys = [k for k, v in profile.to_dict().items()
            if v not in (None, [], {}, False) and k != "path"]
    detail = ("valid .ghostslice.json"
              + (f" (sets: {', '.join(keys)})" if keys else " (all defaults)"))
    return _check("profile", label, OK, detail), profile


def _cache_check(root: Path) -> dict:
    from .cache import CACHE_DIR_NAME, cache_stats
    label = "Content cache"
    target = root / CACHE_DIR_NAME
    if target.exists() and not target.is_dir():
        return _check("cache", label, WARN,
                      f"{CACHE_DIR_NAME} exists but is not a directory",
                      f"remove the file {target} so the cache can "
                      "be created")
    stats = cache_stats(root)
    if not stats["entries"]:
        return _check("cache", label, OK,
                      "no cache yet (created on first scan/export)")
    return _check("cache", label, OK,
                  f"{stats['entries']} entr(ies), "
                  f"{stats['bytes']:,} bytes in {stats['dir']}")


def _ledger_check(root: Path) -> dict:
    from .ledger import LEDGER_NAME, estimator_mix, summary
    label = "Savings ledger"
    if not (root / LEDGER_NAME).is_file():
        return _check("ledger", label, OK,
                      "no runs recorded yet (exports append to "
                      f"{LEDGER_NAME})")
    data = summary(root)
    parts = [f"{data['runs']} recorded run(s)"]
    status, remedy = OK, None
    if data["corrupt_lines"]:
        status = WARN
        parts.append(f"{data['corrupt_lines']} corrupt line(s) "
                     "skipped on read")
        remedy = ("corrupt lines are ignored by every reader; "
                  "trim them from .ghostslice-history.jsonl if "
                  "the warning bothers you")
    mix = estimator_mix(data["records"])
    if mix["mixed"]:
        status = WARN
        parts.append("estimator mix: totals across estimator "
                     "versions are not directly comparable")
        remedy = remedy or ("nothing to fix: new records are "
                            "stamped; treat cross-version trends "
                            "as approximate (see `history --trend`)")
    return _check("ledger", label, status, "; ".join(parts), remedy)


def _plugins_check(root: Path, profile) -> dict:
    label = "Plugins"
    named = list(getattr(profile, "plugins", None) or []) if profile else []
    if not named:
        return _check("plugins", label, OK,
                      "none configured (plugins load only when "
                      "named; there is no auto-discovery)")
    from . import plugins as plugins_mod
    try:
        pset = plugins_mod.load_for_project(root, profile=profile)
    except plugins_mod.PluginError as exc:
        return _check("plugins", label, FAIL, str(exc),
                      "fix the plugin named above; every command "
                      "refuses to run while a named plugin fails "
                      "to load")
    langs = ", ".join(sorted({p.language for p in pset.plugins}))
    return _check("plugins", label, OK,
                  f"{len(pset.plugins)} plugin(s) load cleanly "
                  f"(languages: {langs}); loaded to verify, the "
                  "same way any command loads them")


def _git_check(root: Path) -> dict:
    label = "Git"
    if not (root / ".git").exists():
        return _check("git", label, OK,
                      "not a git repository; .gitignore checks "
                      "skipped")
    ignore_file = root / ".gitignore"
    lines = []
    if ignore_file.is_file():
        try:
            lines = [ln.strip().strip("/")
                     for ln in ignore_file.read_text(
                         encoding="utf-8", errors="replace").splitlines()]
        except OSError:
            lines = []
    wanted = [".claude_context", ".ghostslice-cache"]
    missing = [w for w in wanted
               if not any(ln == w or ln == w + "/" or ln.endswith("/" + w)
                          for ln in lines)]
    if missing:
        return _check("git", label, WARN,
                      "repository; .gitignore does not cover: "
                      + ", ".join(missing),
                      "add `" + "` and `".join(m + "/" for m in missing)
                      + "` to .gitignore so bundles and caches stay "
                      "out of commits")
    return _check("git", label, OK,
                  "repository; .gitignore covers .claude_context/ "
                  "and .ghostslice-cache/")


def _workspace_check(root: Path) -> dict:
    from .workspaces import detect_workspaces
    label = "Workspaces"
    try:
        info = detect_workspaces(root)
    except Exception as exc:  # detection must never kill doctor
        return _check("workspace", label, WARN,
                      f"workspace detection failed: {exc}",
                      "check the workspace manifests "
                      "(package.json, pnpm-workspace.yaml, "
                      "Cargo.toml, go.work, pyproject.toml)")
    named = [p for p in info.packages if p.path]
    if not named:
        return _check("workspace", label, OK,
                      "single-package project (no workspace "
                      "members detected)")
    detail = (f"{len(named)} package(s) detected"
              + ("; declared in workspace manifests" if info.declared
                 else "; inferred from layout"))
    status, remedy = OK, None
    if info.missing:
        status = WARN
        detail += (f"; {len(info.missing)} declared member(s) "
                   "missing on disk")
        remedy = ("create the missing member directories or trim "
                  "the workspace declaration")
    if info.warnings:
        status = WARN
        detail += f"; {len(info.warnings)} detection warning(s)"
        remedy = remedy or ("see `ghostslice scan` workspace "
                            "warnings for the details")
    return _check("workspace", label, status, detail, remedy)


def run_doctor(root: str | Path) -> dict:
    """All checks for `root`, as data. Read-only."""
    root = Path(root)
    profile_check, profile = _profile_check(root)
    checks = [
        _python_check(),
        _version_check(),
        _estimator_check(),
        _prices_check(),
        profile_check,
        _cache_check(root),
        _ledger_check(root),
        _plugins_check(root, profile),
        _git_check(root),
        _workspace_check(root),
    ]
    counts = {OK: 0, WARN: 0, FAIL: 0}
    for c in checks:
        counts[c["status"]] += 1
    return {
        "root": str(root),
        "version": __version__,
        "checks": checks,
        "counts": counts,
        "ok": counts[FAIL] == 0,
    }


def doctor_exit_code(payload: dict) -> int:
    return 0 if payload["ok"] else 1
