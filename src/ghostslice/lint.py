"""Context lint (v0.11): a rule engine that flags context waste.

`ghostslice lint <project>` judges the selection an export WOULD
produce — resolved modes come from exporter.resolve_modes, the same
function build_bundle uses, so lint can never drift from the exporter
— and reports findings from small per-rule functions. Every finding
carries a stable rule id, an effective severity (info | warn |
error), the estimated token cost of the issue, an estimate of what
acting on the suggestion recovers, and a concrete action.

Rules reuse the existing engines, never reimplement them: prune
candidates come from graph.recommendations (L003, minus the
duplicate-derived entries, which are L004's), duplicates from
duplicates.find_duplicates (L004), secrets from
secrets_scan.scan_scan_result (L005, redacted metadata only — lint
findings never carry a secret value or even its redacted preview).

Profile tuning lives in the .ghostslice.json "lint" section (see
profile.py): per-rule severity override (including "off") and
rule-specific numeric options. Invalid config is a loud error at
profile load, not a silent ignore.

Totals are honest about overlap: `flagged_tokens` counts each
flagged file's tokens once no matter how many rules flagged it, and
`potential_savings` takes the best (max) saving per flagged file,
so two rules pointing at the same file never double-count it.

Exit-code contract (cli / MCP `exit_code` field): 1 when any
error-severity finding exists; --strict also fails on warnings;
2 is config/usage errors, handled by the caller. Token counts are
estimates (tokens.py method), like everywhere else.
"""
from __future__ import annotations

from pathlib import Path

from .detect import GENERATED_HEADER_LINES, detect_generated, head_of, line_stats
from .duplicates import find_duplicates
from .exporter import SLICABLE, resolve_modes
from .graph import build_graph, recommendations
from .profile import load_profile
from .scanner import scan
from .secrets_scan import scan_scan_result
from .slicer import slice_text
from .tokens import METHOD

_SEV_RANK = {"error": 0, "warn": 1, "info": 2}

# Rule registry: default severity + numeric options with defaults.
# profile.py validates profile "lint" sections against this table.
RULES: dict[str, dict] = {
    "L001": {"severity": "warn", "options": {"threshold_tokens": 20000},
             "title": "oversize-file"},
    "L002": {"severity": "warn",
             "options": {"min_savings_tokens": 2000, "min_savings_fraction": 0.6},
             "title": "full-mode-slicable"},
    "L003": {"severity": "warn", "options": {}, "title": "dead-weight"},
    "L004": {"severity": "warn", "options": {}, "title": "duplicate-content"},
    "L005": {"severity": "error", "options": {}, "title": "secret-in-context"},
    "L006": {"severity": "warn", "options": {"line_chars": 400},
             "title": "giant-line"},
    "L007": {"severity": "warn", "options": {}, "title": "stale-generated"},
    "L008": {"severity": "warn", "options": {}, "title": "test-in-prod-context"},
    "L009": {"severity": "warn", "options": {}, "title": "lockfile-included"},
    "L010": {"severity": "info",
             "options": {"tiny_tokens": 10, "tiny_count": 20},
             "title": "empty-or-tiny-noise"},
}

# v0.12: the generated-marker list and the giant-line stats live in
# detect.py now (GENERATED_MARKERS / line_stats) — the single source
# the scanner flags and --auto-shrink also consume. L006/L007 below
# call those; nothing detection-shaped is computed privately here.


class _Ctx:
    """Shared inputs + lazy per-file text/slice caches for the rules."""

    def __init__(self, result, modes, profile, graph, recs, dups, secrets):
        self.result = result
        self.modes = modes
        self.profile = profile
        self.graph = graph
        self.recs = recs
        self.dups = dups
        self.secrets = secrets
        self.by_path = {f.path: f for f in result.files}
        self._texts: dict[str, str] = {}
        self._sliced: dict[tuple[str, str], int] = {}

    def text(self, entry) -> str:
        if entry.path not in self._texts:
            try:
                self._texts[entry.path] = Path(entry.abspath).read_text(
                    encoding="utf-8", errors="replace")
            except OSError:
                self._texts[entry.path] = ""
        return self._texts[entry.path]

    def sliced_tokens(self, entry, mode: str) -> int:
        key = (entry.path, mode)
        if key not in self._sliced:
            if mode == "full":
                self._sliced[key] = entry.tokens
            elif mode == "exclude":
                self._sliced[key] = 0
            else:
                self._sliced[key] = slice_text(
                    entry.path, self.text(entry), mode).sliced_tokens
        return self._sliced[key]

    def slice_saving(self, entry) -> int:
        """Tokens recovered by slicing this file the default way:
        signatures when slicable, otherwise only exclusion saves."""
        if entry.language in SLICABLE:
            return entry.tokens - self.sliced_tokens(entry, "signatures")
        return entry.tokens


def _finding(rule, severity, path, tokens, savings, message, action) -> dict:
    return {
        "rule": rule, "severity": severity, "path": path,
        "tokens": tokens, "savings": savings,
        "message": message, "action": action,
    }


# ---------------------------------------------------------------------------
# Rules. Each takes (ctx, opts) and returns finding dicts WITHOUT the
# severity stamped (lint_project stamps the effective severity).
# ---------------------------------------------------------------------------

def _rule_l001(ctx, opts):
    thr = opts["threshold_tokens"]
    out = []
    for e in ctx.result.files:
        if ctx.modes[e.path] != "full" or e.tokens <= thr:
            continue
        out.append(_finding(
            "L001", None, e.path, e.tokens, ctx.slice_saving(e),
            f"{e.path} is {e.tokens:,} estimated tokens at full mode "
            f"(oversize threshold {thr:,})",
            "slice it (signatures/structure) or exclude it from the export"))
    return out


def _rule_l002(ctx, opts):
    min_tokens = opts["min_savings_tokens"]
    min_frac = opts["min_savings_fraction"]
    out = []
    for e in ctx.result.files:
        if ctx.modes[e.path] != "full" or e.language not in SLICABLE:
            continue
        saving = e.tokens - ctx.sliced_tokens(e, "signatures")
        if saving >= min_tokens and e.tokens > 0 and saving >= min_frac * e.tokens:
            out.append(_finding(
                "L002", None, e.path, e.tokens, saving,
                f"{e.path} is slicable code held at full mode; signatures "
                f"would save {saving:,} of {e.tokens:,} estimated tokens "
                f"({saving / e.tokens:.0%})",
                "drop the full-mode override so it exports as signatures"))
    return out


def _rule_l003(ctx, opts):
    out = []
    for rec in ctx.recs:
        # Duplicate-derived recommendations are L004's, not dead weight.
        if rec["reason"].startswith(("exact duplicate", "near-duplicate")):
            continue
        path = rec["path"]
        if ctx.modes.get(path) in (None, "exclude"):
            continue
        out.append(_finding(
            "L003", None, path, rec["tokens"], rec["potential_savings"],
            f"{path} is a prune candidate ({rec['reason']}) still "
            f"included at {ctx.modes[path]} mode "
            f"({rec['tokens']:,} estimated tokens)",
            "review and exclude it if it is really unused"))
    return out


def _rule_l004(ctx, opts):
    out = []
    for group in ctx.dups.get("exact", []):
        included = [p for p in group["files"] if ctx.modes.get(p) != "exclude"]
        if len(included) < 2:
            continue
        keep = included[0]  # the copy actually carrying the content in context
        for path in included[1:]:
            e = ctx.by_path[path]
            out.append(_finding(
                "L004", None, path, e.tokens, e.tokens,
                f"{path} is an exact duplicate of {keep} and both copies "
                f"are included ({e.tokens:,} estimated tokens)",
                "exclude the duplicate copy; one copy carries the signal"))
    for pair in ctx.dups.get("near", []):
        a, b = pair["files"]
        if ctx.modes.get(a) == "exclude" or ctx.modes.get(b) == "exclude":
            continue  # the included copy is the only one in context
        e = ctx.by_path[b]
        out.append(_finding(
            "L004", None, b, e.tokens, pair["potential_savings"],
            f"{b} is a near-duplicate of {a} (similarity "
            f"{pair['similarity']}) and both copies are included "
            f"({e.tokens:,} estimated tokens)",
            "review the pair and exclude the redundant copy"))
    return out


def _rule_l005(ctx, opts):
    by_file: dict[str, list[dict]] = {}
    for f in ctx.secrets:
        by_file.setdefault(f["path"], []).append(f)
    out = []
    for path, finds in sorted(by_file.items()):
        if ctx.modes.get(path) in (None, "exclude"):
            continue
        e = ctx.by_path.get(path)
        if e is None:
            continue
        types = ", ".join(sorted({f["type"] for f in finds}))
        lines = ", ".join(str(f["line"]) for f in finds[:5])
        if len(finds) > 5:
            lines += f", +{len(finds) - 5} more"
        out.append(_finding(
            "L005", None, path, e.tokens, e.tokens,
            f"{path} has {len(finds)} likely secret(s) (types: {types}; "
            f"lines: {lines}) and is slated for inclusion at "
            f"{ctx.modes[path]} mode ({e.tokens:,} estimated tokens)",
            "remove the secret(s), or exclude the file "
            "(export --exclude-secrets force-excludes flagged files)"))
    return out


def _rule_l006(ctx, opts):
    thr = opts["line_chars"]
    out = []
    for e in ctx.result.files:
        if ctx.modes[e.path] == "exclude":
            continue
        text = ctx.text(e)
        if not text:
            continue
        stats = line_stats(text)
        if not stats["lines"]:
            continue
        avg = stats["avg"]
        p95 = stats["p95"]
        if p95 > thr or avg > thr:
            out.append(_finding(
                "L006", None, e.path, e.tokens, 0,
                f"{e.path} has giant lines (avg {avg:.0f} chars, p95 "
                f"{p95:,} chars; threshold {thr:,}) — the giant-line "
                f"shape (minified code, compact data, or long-line "
                f"prose); {e.tokens:,} estimated tokens, detection "
                f"only in this version",
                "review it: exclude it if it is minified or generated, "
                "or keep it knowing each line costs like a paragraph"))
    return out


def _rule_l007(ctx, opts):
    out = []
    for e in ctx.result.files:
        if ctx.modes[e.path] != "full":
            continue
        # detect.py owns the marker list + header window now; its
        # evidence IS the canonical marker. Markdown/notebook files
        # are out of its scope, so they no longer fire here (prose
        # mentioning a marker is documentation, not generated code).
        hit, marker = detect_generated(e.path, e.language, head_of(ctx.text(e)))
        if not hit:
            continue
        out.append(_finding(
            "L007", None, e.path, e.tokens, ctx.slice_saving(e),
            f"{e.path} carries a generated-code header marker "
            f"({marker!r}) in its first {GENERATED_HEADER_LINES} lines "
            f"and is included at full mode "
            f"({e.tokens:,} estimated tokens)",
            "exclude generated files, or slice them; regenerated "
            "output rarely needs full context"))
    return out


def _rule_l008(ctx, opts):
    out = []
    for e in ctx.result.files:
        if not e.is_test or ctx.modes[e.path] != "full":
            continue
        saving = e.tokens - ctx.sliced_tokens(e, "strip-tests")
        out.append(_finding(
            "L008", None, e.path, e.tokens, saving,
            f"{e.path} is a test file included at full mode "
            f"({e.tokens:,} estimated tokens)",
            "drop the full-mode override so tests export as strip-tests, "
            "or exclude them"))
    return out


def _rule_l009(ctx, opts):
    out = []
    for e in ctx.result.files:
        if not e.is_lockfile or ctx.modes[e.path] == "exclude":
            continue
        out.append(_finding(
            "L009", None, e.path, e.tokens, e.tokens,
            f"{e.path} is a lockfile included at {ctx.modes[e.path]} "
            f"mode ({e.tokens:,} estimated tokens)",
            "exclude lockfiles; they carry no signal for an agent"))
    return out


def _rule_l010(ctx, opts):
    tiny_tokens = opts["tiny_tokens"]
    tiny_count = opts["tiny_count"]
    tinies = [e for e in ctx.result.files if e.tokens < tiny_tokens]
    if len(tinies) < tiny_count:
        return []
    total = sum(e.tokens for e in tinies)
    return [_finding(
        "L010", None, None, total, 0,
        f"{len(tinies)} files hold under {tiny_tokens} estimated tokens "
        f"each ({total:,} total) — manifest noise for near-zero signal",
        "consolidate tiny files, or ignore them in the profile if "
        "they carry no signal")]


_RULE_FUNCS = {
    "L001": _rule_l001, "L002": _rule_l002, "L003": _rule_l003,
    "L004": _rule_l004, "L005": _rule_l005, "L006": _rule_l006,
    "L007": _rule_l007, "L008": _rule_l008, "L009": _rule_l009,
    "L010": _rule_l010,
}


def effective_config(profile) -> dict:
    """Resolve the profile's lint section against the rule registry:
    {rule_id: {"severity": effective, <option>: effective value}}.
    Raises ValueError on an out-of-range fraction option."""
    configured = getattr(profile, "lint", None) or {}
    out: dict = {}
    for rule_id, spec in RULES.items():
        cfg = dict(spec["options"])
        severity = spec["severity"]
        override = configured.get(rule_id) or {}
        for key, val in override.items():
            if key == "severity":
                severity = val
            else:
                cfg[key] = val
        if rule_id == "L002":
            frac = cfg["min_savings_fraction"]
            if not (0 < frac <= 1):
                raise ValueError(
                    f"lint rule L002: min_savings_fraction must be in "
                    f"(0, 1], got {frac!r}")
        out[rule_id] = {"severity": severity, **cfg}
    return out


def lint_project(root, profile=None, scan_result=None, graph=None,
                 recs=None, dups=None, secrets=None) -> dict:
    """Run every enabled rule over a project and return the payload
    shared by the CLI (--json), the dashboard (/api/lint) and the MCP
    lint_project tool. Precomputed scan/graph/recs/dups/secrets may
    be passed in (the dashboard does) to avoid recomputation."""
    if profile is None:
        profile = load_profile(root)
    config = effective_config(profile)
    if scan_result is None:
        matcher = profile.is_ignored if profile.path else None
        scan_result = scan(root, ignore_matcher=matcher)
    modes = resolve_modes(scan_result, profile=profile)
    if graph is None:
        graph = build_graph(scan_result)
    if recs is None:
        recs = recommendations(scan_result, graph, profile)
    if dups is None:
        dups = find_duplicates(scan_result)
    if secrets is None:
        secrets = scan_scan_result(scan_result)
    ctx = _Ctx(scan_result, modes, profile, graph, recs, dups, secrets)

    findings: list[dict] = []
    for rule_id in sorted(_RULE_FUNCS):
        eff = config[rule_id]
        if eff["severity"] == "off":
            continue
        opts = {k: v for k, v in eff.items() if k != "severity"}
        for f in _RULE_FUNCS[rule_id](ctx, opts):
            f["severity"] = eff["severity"]
            findings.append(f)
    findings.sort(key=lambda f: (_SEV_RANK[f["severity"]], -f["tokens"],
                                 f["rule"], f["path"] or ""))

    counts = {"error": 0, "warn": 0, "info": 0}
    flagged_paths: set[str] = set()
    best_saving: dict[str, int] = {}
    project_tokens = 0
    project_savings = 0
    for f in findings:
        counts[f["severity"]] += 1
        if f["path"] is None:
            project_tokens += f["tokens"]
            project_savings += f["savings"]
        else:
            flagged_paths.add(f["path"])
            best_saving[f["path"]] = max(best_saving.get(f["path"], 0), f["savings"])
    flagged_tokens = sum(ctx.by_path[p].tokens for p in flagged_paths) + project_tokens
    potential_savings = sum(best_saving.values()) + project_savings

    return {
        "root": scan_result.root,
        "token_method": METHOD,
        "modes": modes,
        "config": config,
        "findings": findings,
        "counts": counts,
        "flagged_tokens": flagged_tokens,
        "potential_savings": potential_savings,
    }


def lint_exit_code(payload: dict, strict: bool = False) -> int:
    """1 on any error finding; with strict, also on any warning."""
    counts = payload["counts"]
    if counts["error"] > 0:
        return 1
    if strict and counts["warn"] > 0:
        return 1
    return 0
