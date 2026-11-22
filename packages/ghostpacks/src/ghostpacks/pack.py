"""Pack format and lint for GhostPacks.

A pack folder holds exactly the kind of files a human can read top to
bottom in minutes:

    pack.json      manifest: id, version, kind, stack, dates, score
    profile.json   a GhostSlice profile fragment (the payload)
    NOTES.md       optional tuning rationale (plain text)
    bench-*.json   optional GhostBench report backing a claimed score

Hard rules enforced here (PLAN.md, GhostPacks v0.1):
- ``kind`` must be exactly ``"context"`` so a context pack can never be
  mistaken for a GhostGuard / GhostLang policy or permission pack.
- Data only: no executable files, no scripts, no shebang files, and
  no file with an executable permission bit anywhere in the folder.
- No absolute paths anywhere in the manifest or the profile fragment.
- A pack that claims a Bench score must reference a Bench report file
  that exists inside the pack, and lint opens that report and checks
  it: the report must be a JSON object, its ``score`` field must equal
  the claimed score, and it must name the reference project the score
  was measured on. A report outside the pack folder (via ``..`` or a
  symlink), a non-numeric claim, or a mismatched report backs nothing.
  A pack with no score is *unscored* and is labelled that way
  everywhere, never silently presented as scored.
- The profile fragment is validated against the live GhostSlice
  profile schema (top-level keys, mode names, presets, lint rules and
  options, floor sections): an unknown key fails loudly, by name.
"""
from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass, field
from datetime import date as _date
from pathlib import Path

KIND = "context"
MODES = ("full", "signatures", "interfaces", "structure",
         "strip-tests", "exclude", "headings")
PRESETS = ("claude-code", "aider", "generic", "cursor", "copilot",
           "anthropic-xml", "json")
LINT_SEVERITIES = ("off", "info", "warn", "error")
# Mirrors ghostslice lint.RULES (rule id -> allowed numeric options).
LINT_RULES = {
    "L001": {"threshold_tokens"},
    "L002": {"min_savings_tokens", "min_savings_fraction"},
    "L003": set(), "L004": set(), "L005": set(),
    "L006": {"line_chars"},
    "L007": set(), "L008": set(), "L009": set(),
    "L010": {"tiny_tokens", "tiny_count"},
}
FLOOR_SECTIONS = {"duplicates": {"near_min_chars"},
                  "ci": {"duplicates_floor_tokens"}}
PROFILE_KEYS = {"ignore", "modes", "model", "budget_tokens",
                "entry_points", "preset", "auto_shrink", "redact",
                "plugins", "lint", "duplicates", "ci"}
DATA_SUFFIXES = {".json", ".md", ".txt"}
EXECUTABLE_SUFFIXES = {".py", ".sh", ".bash", ".zsh", ".js", ".mjs",
                       ".cjs", ".ts", ".tsx", ".jsx", ".exe", ".com",
                       ".bat", ".cmd", ".ps1", ".rb", ".pl", ".php",
                       ".jar", ".class", ".so", ".dylib", ".dll",
                       ".wasm", ".bin"}
MAX_EYEBALL_BYTES = 256 * 1024
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")


class GhostPacksError(ValueError):
    """A user-facing pack/profile error (CLI maps this to exit 2,
    or exit 1 in lint output, never a traceback)."""


def _is_absolute(value: str) -> bool:
    return (value.startswith("/") or value.startswith("\\")
            or value.startswith("~") or bool(_DRIVE_RE.match(value)))


def _walk_strings(value, trail=""):
    if isinstance(value, str):
        yield trail, value
    elif isinstance(value, dict):
        for key, val in value.items():
            yield from _walk_strings(val, f"{trail}.{key}" if trail else key)
    elif isinstance(value, list):
        for idx, val in enumerate(value):
            yield from _walk_strings(val, f"{trail}[{idx}]")


def validate_profile_fragment(data, where="profile fragment",
                                strict=True) -> dict:
    """Validate a GhostSlice profile fragment. Returns it unchanged.

    Mirrors ghostslice/profile.py's loud discipline, plus, in strict
    mode (packs), an unknown-top-level-key check and an absolute-path
    ban (GhostSlice's loader tolerates extra keys; a *pack* must not
    smuggle one past a merge). Non-strict mode is for a user's own
    existing project profile: types and mode names are still checked,
    unknown keys are preserved, and absolute paths are left to the
    caller (init-pack strips them before strict validation)."""
    if not isinstance(data, dict):
        raise GhostPacksError(f"{where}: must be a JSON object")
    if strict:
        for key in data:
            if key not in PROFILE_KEYS:
                raise GhostPacksError(
                    f"{where}: unknown profile key {key!r} "
                    f"(allowed: {', '.join(sorted(PROFILE_KEYS))})")

    def _str_list(key):
        val = data.get(key) or []
        if not isinstance(val, list) or any(not isinstance(v, str) for v in val):
            raise GhostPacksError(f"{where}: {key!r} must be a list of strings")
        if strict:
            for v in val:
                if _is_absolute(v):
                    raise GhostPacksError(
                        f"{where}: {key!r} entry {v!r} is an absolute path; "
                        "pack paths must be relative")
        return val

    _str_list("ignore")
    _str_list("entry_points")
    _str_list("plugins")
    modes = data.get("modes") or {}
    if not isinstance(modes, dict) or any(
            not isinstance(k, str) or not isinstance(v, str)
            for k, v in modes.items()):
        raise GhostPacksError(
            f"{where}: 'modes' must be an object mapping glob patterns to mode names")
    for pat, mode in modes.items():
        if strict and _is_absolute(pat):
            raise GhostPacksError(f"{where}: modes pattern {pat!r} is an absolute path")
        if mode not in MODES:
            raise GhostPacksError(
                f"{where}: unknown mode {mode!r} for pattern {pat!r} "
                f"(choose from {', '.join(MODES)})")
    model = data.get("model")
    if model is not None and not isinstance(model, str):
        raise GhostPacksError(f"{where}: 'model' must be a string")
    preset = data.get("preset")
    if preset is not None and preset not in PRESETS:
        raise GhostPacksError(
            f"{where}: unknown preset {preset!r} (choose from {', '.join(PRESETS)})")
    budget = data.get("budget_tokens")
    if budget is not None:
        if isinstance(budget, bool) or not isinstance(budget, int) or budget <= 0:
            raise GhostPacksError(
                f"{where}: 'budget_tokens' must be a positive whole number")
    for flag in ("auto_shrink", "redact"):
        if flag in data and not isinstance(data[flag], bool):
            raise GhostPacksError(f"{where}: {flag!r} must be true or false")
    lint = data.get("lint")
    if lint is not None:
        if not isinstance(lint, dict):
            raise GhostPacksError(f"{where}: 'lint' must be an object of rule settings")
        for rule_id, cfg in lint.items():
            if rule_id not in LINT_RULES:
                raise GhostPacksError(
                    f"{where}: unknown lint rule {rule_id!r} "
                    f"(known: {', '.join(sorted(LINT_RULES))})")
            if isinstance(cfg, str):
                cfg = {"severity": cfg}
            if not isinstance(cfg, dict):
                raise GhostPacksError(
                    f"{where}: lint rule {rule_id} must be a severity string or an object")
            for opt, val in cfg.items():
                if opt == "severity":
                    if val not in LINT_SEVERITIES:
                        raise GhostPacksError(
                            f"{where}: lint rule {rule_id}: unknown severity {val!r}")
                elif opt in LINT_RULES[rule_id]:
                    if isinstance(val, bool) or not isinstance(val, (int, float)) or val <= 0:
                        raise GhostPacksError(
                            f"{where}: lint rule {rule_id}: option {opt!r} must be a positive number")
                else:
                    raise GhostPacksError(
                        f"{where}: lint rule {rule_id}: unknown option {opt!r}")
    for section, allowed in FLOOR_SECTIONS.items():
        raw = data.get(section)
        if raw is None:
            continue
        if not isinstance(raw, dict):
            raise GhostPacksError(f"{where}: {section!r} must be an object")
        for key, val in raw.items():
            if key not in allowed:
                raise GhostPacksError(
                    f"{where}: unknown {section} option {key!r} "
                    f"(allowed: {', '.join(sorted(allowed))})")
            if isinstance(val, bool) or not isinstance(val, int) or val <= 0:
                raise GhostPacksError(
                    f"{where}: {section} option {key!r} must be a positive whole number")
    return data


def _is_real_date(value) -> bool:
    """True only for a real calendar date in YYYY-MM-DD form (the
    regex alone happily accepts 2026-02-30)."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return False
    try:
        _date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _valid_score(score) -> bool:
    return (not isinstance(score, bool)
            and isinstance(score, (int, float))
            and math.isfinite(score) and score >= 0)


def _is_finite_number(value) -> bool:
    return (isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value))


def _bench_report_errors(manifest: dict, root: Path) -> list:
    """Cross-check a claimed Bench score against its report file.

    Merged harden + deepen verification: a claim is backed only when
    every check holds.

    - The claimed score is a finite, non-negative number (a string,
      bool, dict, or negative value backs nothing).
    - The report path is relative and resolves to a file *inside*
      the pack folder, so a ``..`` segment or a symlink cannot
      borrow a report from elsewhere.
    - The report parses as a JSON object.
    - Its ``score`` field is present, is itself a valid score, and
      equals the claimed score (the harden lane alone accepted a
      report carrying no score of its own; the deepen lane requires
      the field, and the stricter rule wins).
    - It names the reference project the run measured
      (``reference_project``, or a non-empty ``reference_projects``
      list).
    - A ``savings_percent`` field, when present, is a number
      between 0 and 100.

    Returns a list of error strings; empty means the claim is backed
    (or that no report is named and no score is claimed)."""
    errs = []
    score, report = _score_claim(manifest)
    if score is not None and not _valid_score(score):
        errs.append(
            f"pack.json: claimed Bench score must be a finite number "
            f"and non-negative, got {score!r}")
    if report is None:
        if score is not None:
            errs.append("pack.json: pack claims a Bench score but names "
                        "no bench_report file")
        return errs
    if not isinstance(report, str) or not report:
        errs.append(f"pack.json: bench_report must be a relative path "
                    f"inside the pack, got {report!r}")
        return errs
    if _is_absolute(report):
        errs.append(f"pack.json: bench_report {report!r} must be a "
                    "relative path inside the pack")
        return errs
    root_resolved = Path(root).resolve()
    candidate = (root_resolved / report).resolve()
    if not candidate.is_relative_to(root_resolved):
        errs.append(
            f"pack.json: bench_report {report!r} points outside the "
            "pack folder; the report backing a score must live in the pack")
        return errs
    if not candidate.is_file():
        if score is not None:
            errs.append(
                f"pack.json: pack claims score {score!r} but its Bench "
                f"report {report!r} is not in the pack folder")
        else:
            errs.append(
                f"pack.json: bench_report {report!r} is named but not "
                "in the pack folder")
        return errs
    try:
        data = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        errs.append(
            f"pack.json: Bench report {report!r} is not readable JSON: "
            f"{exc}")
        return errs
    if not isinstance(data, dict):
        errs.append(
            f"pack.json: Bench report {report!r} must be a JSON object")
        return errs
    if score is not None:
        ref = data.get("reference_project")
        refs = data.get("reference_projects")
        has_ref = (isinstance(ref, str) and bool(ref.strip())) or (
            isinstance(refs, list)
            and any(isinstance(v, str) and v.strip() for v in refs))
        if not has_ref:
            errs.append(
                f"pack.json: Bench report {report!r} names no "
                "reference_project; a score must state what project "
                "it was measured on")
        if "score" not in data:
            errs.append(
                f"pack.json: Bench report {report!r} contains no "
                "'score' field to back the claimed score")
        elif not _valid_score(data["score"]):
            errs.append(
                f"pack.json: Bench report {report!r} carries an "
                f"invalid score {data['score']!r}; a report score "
                "must be a finite number and non-negative")
        elif _valid_score(score) and float(data["score"]) != float(score):
            errs.append(
                f"pack.json: claimed Bench score {score!r} does not "
                f"match the score {data['score']!r} in Bench report "
                f"{report!r}")
    savings = data.get("savings_percent")
    if savings is not None and (
            not _is_finite_number(savings) or not 0 <= savings <= 100):
        errs.append(
            f"pack.json: Bench report {report!r} 'savings_percent' "
            f"must be a number between 0 and 100, got {savings!r}")
    return errs


def _score_claim(manifest: dict):
    """Return (claimed_score_or_None, bench_report_name_or_None)."""
    score = None
    for key in ("score", "bench_score"):
        if manifest.get(key) is not None:
            score = manifest[key]
    bench = manifest.get("bench")
    report = manifest.get("bench_report")
    if isinstance(bench, dict):
        if bench.get("score") is not None:
            score = bench["score"]
        report = report or bench.get("report")
    return score, report


@dataclass
class Pack:
    """A loaded pack: its folder, parsed manifest, and profile fragment.

    Use :func:`load_pack` to build one; direct construction skips the
    manifest and fragment validation that loader performs.
    """
    path: Path
    manifest: dict
    profile: dict

    @property
    def id(self) -> str:
        """Pack id from the manifest (folder name when absent)."""
        return self.manifest.get("id", self.path.name)

    @property
    def version(self) -> str:
        """Manifest version string ("?" when absent)."""
        return self.manifest.get("version", "?")

    @property
    def stack_tags(self) -> list:
        """Stack tags, from the first of stack_tags / stack / tags that is set."""
        for key in ("stack_tags", "stack", "tags"):
            val = self.manifest.get(key)
            if isinstance(val, list):
                return [str(v) for v in val]
            if isinstance(val, str):
                return [val]
        return []

    @property
    def slice_range(self) -> str | None:
        """Declared GhostSlice version range, or None when the pack states none."""
        for key in ("ghostslice", "ghostslice_range", "compatible_ghostslice"):
            if isinstance(self.manifest.get(key), str):
                return self.manifest[key]
        compat = self.manifest.get("compatible")
        if isinstance(compat, dict) and isinstance(compat.get("ghostslice"), str):
            return compat["ghostslice"]
        return None

    @property
    def claimed_score(self):
        """Bench score the manifest claims, or None when it claims none."""
        return _score_claim(self.manifest)[0]

    @property
    def bench_report(self) -> str | None:
        """Name of the Bench report file the manifest references, or None."""
        return _score_claim(self.manifest)[1]

    @property
    def score_status(self) -> str:
        """"scored" only with a valid claimed score AND a Bench report
        inside the pack that actually backs it (see
        _bench_report_errors)."""
        score, report = _score_claim(self.manifest)
        if (_valid_score(score) and report
                and not _bench_report_errors(self.manifest, self.path)):
            return "scored"
        return "unscored"

    def summary_line(self) -> str:
        """One-line label: id, version, kind, score status, and stack tags."""
        tags = ", ".join(self.stack_tags) or "no stack tags"
        return (f"{self.id} {self.version} (kind: {KIND}, {self.score_status}) "
                f"[{tags}]")


def _read_json(path: Path, what: str) -> dict:
    """Read *path* as a JSON object, raising GhostPacksError on any failure."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise GhostPacksError(f"{path}: cannot read {what}: {exc}") from exc
    except ValueError as exc:
        raise GhostPacksError(f"{path}: invalid JSON in {what}: {exc}") from exc
    if not isinstance(data, dict):
        raise GhostPacksError(f"{path}: {what} must be a JSON object")
    return data


def load_pack(pack_dir) -> Pack:
    """Load a pack folder (manifest + profile fragment, both validated)."""
    root = Path(pack_dir)
    if not root.is_dir():
        raise GhostPacksError(f"{root}: not a pack folder")
    manifest_file = root / "pack.json"
    profile_file = root / "profile.json"
    if not manifest_file.is_file():
        raise GhostPacksError(f"{root}: missing pack.json manifest")
    if not profile_file.is_file():
        raise GhostPacksError(f"{root}: missing profile.json fragment")
    manifest = _read_json(manifest_file, "pack manifest")
    profile = _read_json(profile_file, "profile fragment")
    errs = _manifest_errors(manifest, root)
    if errs:
        raise GhostPacksError("; ".join(errs))
    validate_profile_fragment(profile, where=str(profile_file))
    return Pack(path=root, manifest=manifest, profile=profile)


def _manifest_errors(manifest: dict, root: Path) -> list:
    """All manifest problems as strings (empty list = the manifest is valid).

    Shared by load_pack (which raises on the first joined list) and
    lint_pack (which reports every problem at once).
    """
    errs = []
    pid = manifest.get("id")
    if not isinstance(pid, str) or not _ID_RE.match(pid):
        errs.append(f"pack.json: 'id' must be a simple id like 'python-library', got {pid!r}")
    ver = manifest.get("version")
    if not isinstance(ver, str) or not _VERSION_RE.match(ver):
        errs.append(f"pack.json: 'version' must look like 0.1.0, got {ver!r}")
    if manifest.get("kind") != KIND:
        errs.append(
            f"pack.json: 'kind' must be {KIND!r} (context pack), "
            f"got {manifest.get('kind')!r}; policy/permission packs are not context packs")
    date = manifest.get("date")
    if date is not None and not _is_real_date(date):
        errs.append(f"pack.json: 'date' must be a real date as YYYY-MM-DD, got {date!r}")
    if manifest.get("bench") is not None and not isinstance(manifest.get("bench"), dict):
        errs.append("pack.json: 'bench' must be an object with 'score' and 'report'")
    bench_date = None
    if isinstance(manifest.get("bench"), dict):
        bench_date = manifest["bench"].get("date")
        if bench_date is not None and not _is_real_date(bench_date):
            errs.append(f"pack.json: bench date must be a real date as YYYY-MM-DD, got {bench_date!r}")
    for trail, value in _walk_strings(manifest):
        if value and _is_absolute(value):
            errs.append(f"pack.json: {trail} is an absolute path ({value!r}); pack paths must be relative")
    errs.extend(_bench_report_errors(manifest, root))
    for key in ("stack_tags", "stack", "tags", "reference_projects"):
        val = manifest.get(key)
        if val is not None and not isinstance(val, (str, list)):
            errs.append(f"pack.json: {key!r} must be a string or a list of strings")
    return errs


def lint_pack(pack_dir) -> tuple:
    """Lint a pack folder. Returns (errors, warnings): lists of strings.

    An empty errors list means the pack is valid. Warnings cover
    eyeball-ability and freshness only; they never block a merge on
    their own."""
    root = Path(pack_dir)
    errors: list = []
    warnings: list = []
    if not root.is_dir():
        return [f"{root}: not a pack folder"], warnings
    # Data-only sweep over every file in the folder. Hidden files are
    # NOT exempt: a dot-prefixed script (.evil.py, an executable
    # .hidden.txt) is exactly the kind of file this sweep exists to
    # catch. Symlinks are rejected outright (a pack is self-contained
    # data; a link can point at anything on the reader's machine),
    # and non-regular files (fifos, sockets, devices) are rejected
    # without being read, since reading one could block forever.
    for item in sorted(root.rglob("*")):
        rel = item.relative_to(root).as_posix()
        if item.is_symlink():
            errors.append(f"{rel}: symlink in a pack; packs are self-contained data only and a symlink can point outside the pack")
            continue
        if item.is_dir():
            continue
        if not item.is_file():
            errors.append(f"{rel}: not a regular file; packs are data only")
            continue
        suffix = item.suffix.lower()
        if suffix in EXECUTABLE_SUFFIXES:
            errors.append(f"{rel}: executable/script file in a pack; packs are data only")
        elif suffix not in DATA_SUFFIXES:
            errors.append(f"{rel}: non-data file type {suffix or '(none)'} in a pack; "
                          f"allowed: {', '.join(sorted(DATA_SUFFIXES))}")
        try:
            mode = item.stat().st_mode
        except OSError:
            continue
        if mode & 0o111:
            errors.append(f"{rel}: has an executable permission bit; packs are data only")
        try:
            head = item.read_bytes()[:2]
        except OSError:
            head = b""
        if head == b"#!":
            errors.append(f"{rel}: starts with a shebang; packs are data only")
        try:
            if item.stat().st_size > MAX_EYEBALL_BYTES:
                warnings.append(f"{rel}: over {MAX_EYEBALL_BYTES} bytes; a pack should be readable in minutes")
        except OSError:
            pass
    manifest_file = root / "pack.json"
    profile_file = root / "profile.json"
    if not manifest_file.is_file():
        errors.append("missing pack.json manifest")
    if not profile_file.is_file():
        errors.append("missing profile.json fragment")
    if errors or not (manifest_file.is_file() and profile_file.is_file()):
        return errors, warnings
    try:
        manifest = _read_json(manifest_file, "pack manifest")
        errors.extend(_manifest_errors(manifest, root))
    except GhostPacksError as exc:
        errors.append(str(exc))
    try:
        profile = _read_json(profile_file, "profile fragment")
        validate_profile_fragment(profile, where="profile.json")
    except GhostPacksError as exc:
        errors.append(str(exc))
    return errors, warnings


def find_packs(library_dirs) -> list:
    """All valid-or-not pack folders under the given library dirs.

    Returns a list of Paths (folders containing a pack.json), sorted,
    de-duplicated. Never touches the network: local folders only."""
    found = []
    seen = set()
    for base in library_dirs:
        base = Path(base)
        if not base.is_dir():
            continue
        candidates = [base] if (base / "pack.json").is_file() else \
            sorted(p for p in base.iterdir() if p.is_dir())
        for cand in candidates:
            if (cand / "pack.json").is_file():
                key = str(cand.resolve())
                if key not in seen:
                    seen.add(key)
                    found.append(cand)
    return found


def default_library_dirs(explicit=None) -> list:
    """Library search path: explicit dir, $GHOSTPACKS_LIBRARY,
    ~/.ghostpacks, and the starter packs bundled with this checkout."""
    dirs = []
    if explicit:
        dirs.append(Path(explicit))
    env = os.environ.get("GHOSTPACKS_LIBRARY")
    if env:
        dirs.append(Path(env))
    dirs.append(Path.home() / ".ghostpacks")
    bundled = Path(__file__).resolve().parents[2] / "packs"
    if bundled.is_dir():
        dirs.append(bundled)
    return dirs


def resolve_pack(name_or_path, library_dirs) -> Path:
    """Resolve a pack argument: a folder path wins, else a pack id
    looked up in the library dirs."""
    cand = Path(name_or_path)
    if (cand / "pack.json").is_file():
        return cand
    for folder in find_packs(library_dirs):
        try:
            manifest = _read_json(folder / "pack.json", "pack manifest")
        except GhostPacksError:
            continue
        if manifest.get("id") == name_or_path or folder.name == name_or_path:
            return folder
    raise GhostPacksError(
        f"pack {name_or_path!r} not found: not a pack folder and no pack "
        f"with that id in the local library")
