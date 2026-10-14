"""Project profile: `.ghostslice.json` in the scanned project root.

Example:
{
  "ignore": ["vendor/**", "*.snap"],
  "modes": {"src/**": "signatures", "docs/**": "full", "**/*.py": "signatures"},
  "model": "claude-sonnet",
  "budget_tokens": 50000,
  "entry_points": ["src/main.py", "src/cli.py"],
  "preset": "claude-code"
}

All fields are optional. The CLI loads the profile automatically when a
command targets a project directory that contains the file.

An optional "auto_shrink" flag (v0.12, default false) makes exports
exclude files detect.py flags as generated, vendored, or minified —
only where the mode would come from the built-in defaults: explicit
selections, per-glob "modes" below, and profile entry_points always
win over auto-shrink. The export CLI's --auto-shrink sets the same
thing for one run.

An optional "redact" flag (v0.17, default false) makes exports
replace flagged secret VALUES in place with `[REDACTED:<kind>:<fp>]`
placeholders instead of shipping them (the file is kept; contrast
--exclude-secrets, which drops flagged files entirely). The export
CLI's --redact / --no-redact override it per run.

An optional "plugins" list (v0.23) names user slicer plugins to
load for this project: paths relative to the project root, each
resolved (symlinks followed) and required to stay inside it.
Loading a plugin EXECUTES it — plugins are user code with full
privileges, named explicitly here or not at all; there is no
auto-discovery. See plugins.py for the contract.

An optional "lint" section (v0.11) tunes the context linter per rule:

  "lint": {
    "L001": {"severity": "error", "threshold_tokens": 5000},
    "L006": "off"
  }

Each rule id maps to a severity string ("off" | "info" | "warn" |
"error") or an object with a "severity" plus rule-specific numeric
options (the allowed option names live in lint.RULES). Unknown rule
ids, severities, option names, or non-positive option values are a
loud ValueError at load time — a typo'd rule id must never silently
disable (or fail to disable) a rule.
"""
from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass, field
from pathlib import Path

from .textio import decode_bytes, sniff_bom

PROFILE_NAME = ".ghostslice.json"
PRESETS = ("claude-code", "aider", "generic", "cursor", "copilot",
           "anthropic-xml", "json")


def match_glob(pattern: str, rel: str) -> bool:
    """Match a glob against a posix relative path.

    Supports fnmatch globs on the full path and on the basename (when the
    pattern has no slash), `dir/**` as "everything under dir", and a
    leading `**/` as "at any depth".
    """
    pat = pattern.replace("\\", "/").strip()
    rel = rel.replace("\\", "/")
    if not pat:
        return False
    if pat.endswith("/**"):
        prefix = pat[:-3].rstrip("/")
        return rel == prefix or rel.startswith(prefix + "/")
    if fnmatch.fnmatch(rel, pat):
        return True
    if pat.startswith("**/") and fnmatch.fnmatch(rel, pat[3:]):
        return True
    if "/" not in pat and fnmatch.fnmatch(Path(rel).name, pat):
        return True
    # "src/*.py" should also match deeper via fnmatch's * crossing / on posix
    return False


LINT_SEVERITIES = ("off", "info", "warn", "error")


@dataclass
class Profile:
    ignore: list[str] = field(default_factory=list)
    modes: dict[str, str] = field(default_factory=dict)
    model: str | None = None
    budget_tokens: int | None = None
    entry_points: list[str] = field(default_factory=list)
    preset: str | None = None
    # v0.12: opt-in auto-shrink — files the detect.py flags mark as
    # generated/vendored/minified resolve to exclude in exports
    # unless an explicit selection or profile mode says otherwise.
    auto_shrink: bool = False
    # v0.17: opt-in redact-in-place for exports (see module docstring).
    redact: bool = False
    # v0.23: user slicer plugins to load for this project (paths
    # relative to the project root; see module docstring).
    plugins: list[str] = field(default_factory=list)
    path: str | None = None  # where it was loaded from, if any
    # v0.11: normalised lint config {rule_id: {"severity": str, option: number}}
    lint: dict = field(default_factory=dict)

    def is_ignored(self, rel: str) -> bool:
        return any(match_glob(p, rel) for p in self.ignore)

    def mode_for(self, rel: str) -> str | None:
        """Last matching glob wins, mirroring .gitignore precedence."""
        mode = None
        for pat, m in self.modes.items():
            if match_glob(pat, rel):
                mode = m
        return mode

    def to_dict(self) -> dict:
        return {
            "ignore": self.ignore, "modes": self.modes, "model": self.model,
            "budget_tokens": self.budget_tokens,
            "entry_points": self.entry_points, "preset": self.preset,
            "auto_shrink": self.auto_shrink, "redact": self.redact,
            "plugins": self.plugins,
            "path": self.path, "lint": self.lint,
        }


def _parse_lint_section(raw, candidate: Path) -> dict:
    """Validate + normalise the profile's "lint" section.

    Rule ids and allowed option names come from lint.RULES (imported
    lazily: lint.py depends on the exporter/scanner stack, and this
    keeps profile.py importable without it). Anything unrecognised is
    a loud ValueError, never a silent ignore.
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"{candidate}: 'lint' must be an object mapping rule ids to settings")
    from .lint import RULES
    out: dict = {}
    for rule_id, cfg in raw.items():
        if rule_id not in RULES:
            raise ValueError(
                f"{candidate}: unknown lint rule {rule_id!r} "
                f"(known: {', '.join(sorted(RULES))})")
        if isinstance(cfg, str):
            cfg = {"severity": cfg}
        if not isinstance(cfg, dict):
            raise ValueError(
                f"{candidate}: lint rule {rule_id} must be a severity string or an object")
        allowed_options = set(RULES[rule_id]["options"])
        norm: dict = {}
        for key, val in cfg.items():
            if key == "severity":
                if val not in LINT_SEVERITIES:
                    raise ValueError(
                        f"{candidate}: lint rule {rule_id}: unknown severity {val!r} "
                        f"(choose from {', '.join(LINT_SEVERITIES)})")
                norm["severity"] = val
            elif key in allowed_options:
                if isinstance(val, bool) or not isinstance(val, (int, float)) or val <= 0:
                    raise ValueError(
                        f"{candidate}: lint rule {rule_id}: option {key!r} "
                        f"must be a positive number")
                norm[key] = val
            else:
                raise ValueError(
                    f"{candidate}: lint rule {rule_id}: unknown option {key!r} "
                    f"(allowed: severity{', ' if allowed_options else ''}"
                    f"{', '.join(sorted(allowed_options))})")
        out[rule_id] = norm
    return out


def load_profile(root: str | Path) -> Profile:
    root = Path(root)
    candidate = root / PROFILE_NAME if root.is_dir() else root.parent / PROFILE_NAME
    if not candidate.is_file():
        return Profile()
    # v0.21: a malformed profile is a user error with a message,
    # never a traceback — invalid JSON and wrong-typed fields all
    # become ValueError naming the file and the field (the CLI maps
    # ValueError to exit 2 for every command).
    try:
        blob = candidate.read_bytes()
    except OSError as exc:
        raise ValueError(f"{candidate}: cannot read profile: {exc}") from exc
    if sniff_bom(blob) is not None:
        # A BOM is explicit intent (Windows editors write UTF-8
        # BOMs): decode through the shared helper, BOM stripped.
        raw = decode_bytes(blob)[0]
    else:
        try:
            raw = blob.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(
                f"{candidate}: profile is not valid UTF-8: {exc}") from exc
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise ValueError(f"{candidate}: invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{candidate}: profile must be a JSON object")

    def _str_list(key: str) -> list:
        val = data.get(key) or []
        if not isinstance(val, list) or \
                any(not isinstance(v, str) for v in val):
            raise ValueError(
                f"{candidate}: {key!r} must be a list of strings")
        return list(val)

    modes_raw = data.get("modes") or {}
    if not isinstance(modes_raw, dict) or any(
            not isinstance(k, str) or not isinstance(v, str)
            for k, v in modes_raw.items()):
        raise ValueError(
            f"{candidate}: 'modes' must be an object mapping glob "
            "patterns to mode names")
    model = data.get("model")
    if model is not None and not isinstance(model, str):
        raise ValueError(f"{candidate}: 'model' must be a string")
    preset = data.get("preset")
    if preset is not None and preset not in PRESETS:
        raise ValueError(f"{candidate}: unknown preset {preset!r} (choose from {', '.join(PRESETS)})")
    auto_shrink = data.get("auto_shrink", False)
    if not isinstance(auto_shrink, bool):
        raise ValueError(f"{candidate}: 'auto_shrink' must be true or false, got {auto_shrink!r}")
    redact = data.get("redact", False)
    if not isinstance(redact, bool):
        raise ValueError(f"{candidate}: 'redact' must be true or false, got {redact!r}")
    budget = data.get("budget_tokens")
    if budget is not None:
        if isinstance(budget, bool) or \
                not isinstance(budget, (int, float, str)):
            raise ValueError(
                f"{candidate}: 'budget_tokens' must be a number")
        try:
            budget = int(budget)
        except (TypeError, ValueError):
            raise ValueError(
                f"{candidate}: 'budget_tokens' must be a number, "
                f"got {budget!r}") from None
    return Profile(
        ignore=_str_list("ignore"),
        modes=dict(modes_raw),
        model=model,
        budget_tokens=budget,
        entry_points=_str_list("entry_points"),
        preset=preset,
        auto_shrink=auto_shrink,
        redact=redact,
        plugins=_str_list("plugins"),
        path=str(candidate),
        lint=_parse_lint_section(data.get("lint"), candidate),
    )
