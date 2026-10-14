"""CI pack (v0.24): `ghostslice ci` — one gate command for a repo's
agent-context health.

Runs five named checks over the default export selection and reports
each as pass / warn / fail / skipped with a one-line evidence string:

  budget      sliced context vs the configured budget (skipped when
              no budget is configured anywhere)
  lint        the context-lint rules (errors fail; warnings fail
              only under --strict — lint_exit_code semantics)
  secrets     the secret guard (findings FAIL by default: a CI gate
              exists to keep secrets out of agent context; pass
              --allow-secrets to downgrade findings to a warning.
              The flag speaks for the whole run: the lint check then
              also runs with its L005 secret rule off, so the same
              findings cannot fail the run through the side door)
  fit         whether the auto-fit ladder can reach the budget from
              the default selection (skipped with no budget)
  duplicates  exact-duplicate groups holding at least
              DUP_FLOOR_TOKENS recoverable estimated tokens (warn)

Exit semantics: 0 when no check failed (warnings and skips do not
fail the run), 1 when any check failed, 2 for usage/config errors
(handled by the CLI layer: bad profile, bad --budget, missing
project, an --out report that cannot be written). A check that
raises becomes that check FAILED with the error as its evidence;
the remaining checks still run (the v0.21 no-traceback discipline,
applied per check).

The run is read-only: it scans, slices in memory, and lints, but
writes nothing, appends no ledger record, and never opens the
content cache. The only file it may write is the HTML report named
by --out, which the CLI layer writes after the checks complete.

Token counts are estimates everywhere (see tokens.py).
"""
from __future__ import annotations

import dataclasses

from . import __version__
from .duplicates import find_duplicates
from .exporter import resolve_modes
from .fit import fit_modes
from .lint import lint_exit_code, lint_project
from .profile import load_profile
from .scanner import scan
from .secrets_scan import scan_scan_result
from .slicer import slice_text
from .textio import read_text as _gs_read_text
from .tokens import METHOD as TOKEN_METHOD

# Exact-duplicate groups below this many recoverable estimated
# tokens are noise for a CI gate (small shared fixtures, tiny
# config twins — this repo's own test fixtures live under it);
# at or above it the group warns.
DUP_FLOOR_TOKENS = 500

CHECK_IDS = ("budget", "lint", "secrets", "fit", "duplicates")
STATUSES = ("pass", "warn", "fail", "skipped")


def _selection_totals(result, profile):
    """(original, sliced, resolved modes) for the default/profile
    selection — the same per-mode accounting as
    exporter.estimate_context_tokens (and therefore the same basis
    `check-budget` judges), computed on an existing scan so the CI
    checks share one snapshot. Slices in memory; writes nothing."""
    resolved = resolve_modes(result, profile=profile)
    before = after = 0
    for entry in result.files:
        mode = resolved[entry.path]
        if mode == "full":
            before += entry.tokens
            after += entry.tokens
        elif mode == "exclude":
            before += entry.tokens
        else:
            r = slice_text(entry.path, _gs_read_text(entry.abspath), mode)
            before += r.original_tokens
            after += r.sliced_tokens
    return before, after, resolved


def _check_budget(ctx):
    budget = ctx["budget"]
    if budget is None:
        return "skipped", ("no budget configured (run `ghostslice init` "
                           "to set one, or pass --budget)"), {
            "budget_tokens": None}
    if ctx["totals_error"] is not None:
        raise ctx["totals_error"]
    before, after, _resolved = ctx["totals"]
    details = {"budget_tokens": budget, "original_tokens": before,
               "sliced_tokens": after}
    if after <= budget:
        pct = 100.0 * after / budget if budget else 0.0
        return "pass", (f"sliced context {after:,} of {budget:,} "
                        f"estimated tokens ({pct:.0f}% of budget)"), details
    details["over_by"] = after - budget
    return "fail", (f"sliced context {after:,} exceeds budget {budget:,} "
                    f"by {after - budget:,} estimated tokens"), details


def _check_lint(ctx):
    profile = ctx["profile"]
    l005_off = False
    if ctx["allow_secrets"]:
        # --allow-secrets downgrades the secrets verdict for the
        # whole run (see _check_secrets); lint's L005 is the same
        # findings wearing a rule number, so it is turned off via
        # the profile's own lint config for this check only. The
        # user's profile object is not mutated (dataclasses.replace
        # on a merged lint dict), and the details say it happened.
        merged = dict(profile.lint or {})
        merged["L005"] = {**(merged.get("L005") or {}),
                          "severity": "off"}
        profile = dataclasses.replace(profile, lint=merged)
        l005_off = True
    payload = lint_project(ctx["root"], profile=profile,
                           scan_result=ctx["scan"], dups=ctx["dups"],
                           secrets=ctx["secrets"])
    counts = payload["counts"]
    details = {"counts": counts, "findings": payload["findings"],
               "strict": ctx["strict"],
               "l005_disabled_by_allow_secrets": l005_off}
    evidence = (f"{counts['error']} error(s), {counts['warn']} warning(s), "
                f"{counts['info']} info")
    if payload["findings"]:
        top = payload["findings"][0]
        where = top["path"] or "(project)"
        evidence += f"; top: {top['rule']} {where}: {top['message']}"
    if l005_off and ctx["secrets"]:
        evidence += " (L005 secret rule off under --allow-secrets)"
    if lint_exit_code(payload, strict=ctx["strict"]):
        return "fail", evidence, details
    if counts["warn"]:
        return "warn", evidence, details
    return "pass", evidence, details


def _check_secrets(ctx):
    findings = ctx["secrets"]
    if not findings:
        return "pass", "no likely secrets found", {"count": 0, "files": []}
    files = sorted({f["path"] for f in findings})
    first = findings[0]
    evidence = (f"{len(findings)} likely secret(s) in {len(files)} "
                f"file(s); first: {first['path']}:{first['line']} "
                f"{first['type']} ({first['redacted']})")
    details = {"count": len(findings), "files": files,
               "findings": findings}
    if ctx["allow_secrets"]:
        return "warn", evidence + " (allowed by --allow-secrets)", details
    return "fail", evidence, details


def _check_fit(ctx):
    budget = ctx["budget"]
    if budget is None:
        return "skipped", "no budget configured: nothing to fit to", {
            "budget_tokens": None}
    resolved = resolve_modes(ctx["scan"], profile=ctx["profile"])
    _modes, report = fit_modes(ctx["scan"], resolved, budget,
                                profile=ctx["profile"])
    details = {"budget_tokens": budget,
               "before_tokens": report["before_tokens"],
               "after_tokens": report["after_tokens"],
               "fitted": report["fitted"],
               "downgrades": len(report["downgraded"]),
               "steps": report["steps"]}
    if report["fitted"]:
        return "pass", (f"auto-fit reaches {report['after_tokens']:,} of "
                        f"{budget:,} estimated tokens "
                        f"({len(report['downgraded'])} downgrade(s))"), details
    return "fail", (f"auto-fit cannot reach the budget: best achievable "
                    f"{report['after_tokens']:,} > {budget:,} estimated "
                    f"tokens"), details


def _check_duplicates(ctx):
    if ctx["dups_error"] is not None:
        raise ctx["dups_error"]
    groups = [g for g in ctx["dups"]["exact"]
              if g["potential_savings"] >= DUP_FLOOR_TOKENS]
    below = len(ctx["dups"]["exact"]) - len(groups)
    details = {"floor_tokens": DUP_FLOOR_TOKENS,
               "groups": [{"files": g["files"],
                           "tokens_each": g["tokens_each"],
                           "potential_savings": g["potential_savings"]}
                          for g in groups],
               "groups_below_floor": below}
    if not groups:
        evidence = ("no exact-duplicate group holds "
                    f"{DUP_FLOOR_TOKENS:,}+ recoverable estimated tokens")
        if below:
            evidence += f" ({below} smaller group(s) below the floor)"
        return "pass", evidence, details
    top = groups[0]
    evidence = (f"{len(groups)} exact-duplicate group(s) at or above the "
                f"floor; largest: {' + '.join(top['files'])}: up to "
                f"{top['potential_savings']:,} recoverable estimated tokens")
    return "warn", evidence, details


_CHECKS = (("budget", _check_budget), ("lint", _check_lint),
           ("secrets", _check_secrets), ("fit", _check_fit),
           ("duplicates", _check_duplicates))


def run_ci(root, profile=None, budget=None, strict=False,
           allow_secrets=False) -> dict:
    """Run every CI check over `root` and return the payload the CLI
    renders as text, --json, or --pr-comment.

    `budget` (estimated sliced tokens) overrides the profile's
    budget_tokens; with neither, the budget and fit checks skip.
    Filesystem-shaped failures of the shared scan itself (missing
    project, unreadable tree) propagate: the CLI layer maps them to
    exit 2, a usage error, not a check verdict. Everything a single
    check does is isolated: its exception becomes that check's
    failure, never a crashed run."""
    root = str(root)
    if profile is None:
        profile = load_profile(root)
    result = scan(root,
                  ignore_matcher=profile.is_ignored if profile.path else None)
    secrets = scan_scan_result(result)
    eff_budget = budget if budget is not None else profile.budget_tokens

    # The two shared derivations a single check depends on are
    # precomputed under the same isolation as the checks themselves:
    # a failure is stored and re-raised inside the dependent check,
    # where the isolation wrapper turns it into that check's FAIL.
    totals = None
    totals_error = None
    try:
        totals = _selection_totals(result, profile)
    except Exception as exc:  # surfaced via the budget check + totals
        totals_error = exc
    dups = None
    dups_error = None
    try:
        dups = find_duplicates(result)
    except Exception as exc:  # surfaced via the duplicates check
        dups_error = exc

    ctx = {"root": root, "profile": profile, "budget": eff_budget,
           "strict": strict, "allow_secrets": allow_secrets,
           "scan": result, "secrets": secrets, "dups": dups,
           "dups_error": dups_error,
           "totals": totals, "totals_error": totals_error}

    checks = []
    for check_id, fn in _CHECKS:
        try:
            status, evidence, details = fn(ctx)
        except Exception as exc:
            status = "fail"
            evidence = f"check errored: {type(exc).__name__}: {exc}"
            details = {}
        checks.append({"id": check_id, "status": status,
                       "evidence": evidence, "details": details})

    summary = {s: 0 for s in STATUSES}
    for c in checks:
        summary[c["status"]] += 1
    exit_code = 1 if summary["fail"] else 0

    totals_payload = None
    if totals is not None:
        before, after, _resolved = totals
        totals_payload = {
            "original_tokens": before,
            "sliced_tokens": after,
            "saved_tokens": before - after,
            "saved_pct": (round(100.0 * (before - after) / before, 1)
                          if before else 0.0),
        }

    return {
        "tool": "ghostslice",
        "version": __version__,
        "root": str(result.root),
        "token_method": TOKEN_METHOD,
        "checks": checks,
        "totals": totals_payload,
        "summary": summary,
        "exit_code": exit_code,
        "ok": exit_code == 0,
    }


_STATUS_TAGS = {"pass": "PASS", "warn": "WARN", "fail": "FAIL",
                "skipped": "SKIP"}


def render_text(payload: dict) -> str:
    """The default human output: one line per check plus a verdict.
    Exit semantics: exit 0 unless a check failed (then 1); usage and
    config errors exit 2 before any check runs."""
    lines = [f"GhostSlice CI: {payload['root']} "
             "(token counts are estimates)"]
    for c in payload["checks"]:
        lines.append(f"  [{_STATUS_TAGS[c['status']]:<4}] "
                     f"{c['id']:<10} {c['evidence']}")
    s = payload["summary"]
    verdict = "PASS" if payload["ok"] else "FAIL"
    lines.append(f"Result: {verdict} (exit {payload['exit_code']}): "
                 f"{s['pass']} passed, {s['warn']} warning(s), "
                 f"{s['fail']} failed, {s['skipped']} skipped")
    if payload["totals"] is not None:
        t = payload["totals"]
        lines.append(f"Context: {t['original_tokens']:,} -> "
                     f"{t['sliced_tokens']:,} estimated tokens "
                     f"({t['saved_pct']:.1f}% saved)")
    return "\n".join(lines)


def render_pr_comment(payload: dict) -> str:
    """Compact Markdown summary for pasting as a PR comment: the
    checks table plus the context totals. Plain punctuation only,
    and table-breaking pipes in evidence are escaped."""
    def esc(text: str) -> str:
        return text.replace("|", "\\|")

    lines = ["## GhostSlice CI", "",
             "| Check | Status | Evidence |",
             "| --- | --- | --- |"]
    for c in payload["checks"]:
        lines.append(f"| {c['id']} | {_STATUS_TAGS[c['status']]} | "
                     f"{esc(c['evidence'])} |")
    lines.append("")
    if payload["totals"] is not None:
        t = payload["totals"]
        lines.append(f"**Context:** {t['original_tokens']:,} -> "
                     f"{t['sliced_tokens']:,} estimated tokens "
                     f"({t['saved_pct']:.1f}% saved)")
    s = payload["summary"]
    verdict = "PASS" if payload["ok"] else "FAIL"
    lines.append(f"**Result:** {verdict}: {s['pass']} passed, "
                 f"{s['warn']} warning(s), {s['fail']} failed, "
                 f"{s['skipped']} skipped")
    return "\n".join(lines)
