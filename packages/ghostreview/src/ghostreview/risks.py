"""Risk flags: explicit rules, every flag cites file + reason.

Thresholds live here as named constants and are printed in the report
so a reader can judge them. Secret findings are path + line + type
only: the matched value is never copied into any output.
"""
from __future__ import annotations

import re
from pathlib import Path

LARGE_FILE_DELETION = 100   # deleted lines in one file
LARGE_TOTAL_DELETION = 300  # deleted lines across the diff
MANY_DEPENDENTS = 5         # dependents at which breadth is flagged
_PASS_VERDICTS = {"pass", "passed", "sufficient", "ok", "clean"}

_TEST_RE = re.compile(r"(^|/)(tests?|specs?)(/|_)|(^|/)test_[^/]*|_test\.[^/]*$|"
                      r"\.test\.[^/]*$|\.spec\.[^/]*$|conftest\.py$")
_CONFIG_NAMES = {".editorconfig", ".gitignore", ".gitattributes",
                 "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
                 "Makefile", "tsconfig.json", "vite.config.ts",
                 "vite.config.js", "webpack.config.js", "babel.config.js",
                 ".eslintrc.json", ".prettierrc", "setup.cfg", "tox.ini",
                 "pytest.ini", "mypy.ini", ".flake8"}
_DEPENDENCY_NAMES = {"pyproject.toml", "requirements.txt", "Pipfile",
                     "Pipfile.lock", "poetry.lock", "package.json",
                     "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
                     "Cargo.toml", "Cargo.lock", "go.mod", "go.sum"}
# "secret"/"credentials" must be a whole name token (end of path or
# followed by a separator), not the prefix of a longer ordinary word:
# secretary.py is not secret-shaped and must not draw a high flag.
_SECRET_PATH_RE = re.compile(r"(^|/)(\.env($|\.)|.*credentials?(?=$|[/._-])|"
                             r".*secrets?(?=$|[/._-])|"
                             r"id_rsa|id_ed25519)", re.I)
_SECRET_EXTS = {".pem", ".key", ".p12", ".pfx", ".keystore"}
# Secret line shapes mirror GhostSlice's canonical guard list
# (ghostslice/secrets_scan.py _KNOWN_PATTERNS) as of the Oct 14, 2026
# seam fix; see SEAM_FIX_REPORT.md for the per-shape parity audit,
# including the two deliberate divergences (no placeholder filtering,
# no entropy heuristic). Token shapes keep Slice's word boundaries so
# a longer look-alike string is not half-matched.
_SECRET_LINE_RES = [
    ("labelled-secret-assignment",
     re.compile(r"(?i)(api[_-]?key|secret|token|password|passwd|"
                r"private[_-]?key|access[_-]?key|credentials?)\s*[:=]\s*"
                r"['\"][^'\"]{8,}['\"]")),
    ("token-prefix", re.compile(r"\b(sk-(?:ant-|proj-)?[A-Za-z0-9_\-]{16,}|"
                                r"gh[pousr]_[A-Za-z0-9_]{20,}|"
                                r"(?:AKIA|ASIA)[0-9A-Z]{16}|"
                                r"xox[baprs]-[A-Za-z0-9-]{10,})\b")),
    ("private-key-header", re.compile(r"BEGIN (RSA |EC |OPENSSH |DSA |PGP )?"
                                      r"PRIVATE KEY")),
    ("password-in-url", re.compile(r"://[^/\s:@'\"]+:[^/\s:@'\"]{3,}@")),
]
# Slice's aws-secret-key shape is context-gated: a bare 40-char
# base64-ish token only counts when the line also names an AWS secret.
_AWS_SECRET_CONTEXT = re.compile(r"aws.{0,20}secret|secret.{0,20}aws",
                                 re.IGNORECASE)
_BARE_40 = re.compile(r"\b[A-Za-z0-9/+=]{40}\b")


def is_test_path(path: str) -> bool:
    """True when *path* looks like a test file (drives ``TEST-EDIT``)."""
    return bool(_TEST_RE.search(path or ""))


def is_config_path(path: str) -> bool:
    """True when *path* looks like config or a dependency manifest."""
    name = Path(path or "").name
    if name in _CONFIG_NAMES or name in _DEPENDENCY_NAMES:
        return True
    parts = Path(path or "").parts
    return ".github" in parts or name.endswith((".toml", ".ini", ".cfg")) \
        and name not in _DEPENDENCY_NAMES


def flag_risks(changes, symbols_by_path: dict, dependents: dict,
               verify: dict | None) -> list:
    """changes: list[FileChange]; returns list of flag dicts."""
    flags: list = []

    def add(level, rule, path, detail, line=None):
        flags.append({"level": level, "rule": rule, "file": path,
                      "line": line, "detail": detail})

    total_deleted = sum(c.deleted_count for c in changes)
    for c in changes:
        path = c.path or ""
        name = Path(path).name
        if is_test_path(path):
            if c.status == "deleted":
                add("high", "TEST-EDIT", path,
                    "a test file is deleted in this diff; the change "
                    "removes its own covering test file")
            else:
                add("medium", "TEST-EDIT", path,
                    f"a test file is {c.status} in this diff; check the "
                    "test change was intended and not made to fit the code")
        if name in _DEPENDENCY_NAMES:
            add("medium", "DEPENDENCY", path,
                "a dependency manifest or lockfile changed")
        elif is_config_path(path):
            add("medium", "CONFIG", path, "a configuration file changed")
        if _SECRET_PATH_RE.search(path) \
                or Path(path).suffix.lower() in _SECRET_EXTS:
            add("high", "SECRET-PATH", path,
                "the changed path is secret-shaped (env, credentials, or "
                "key material by name or extension); its contents are not "
                "shown in this review")
        for lineno, text in c.added:
            hit = None
            for type_name, rx in _SECRET_LINE_RES:
                if rx.search(text):
                    hit = type_name
                    break
            if hit is None and _AWS_SECRET_CONTEXT.search(text) \
                    and _BARE_40.search(text):
                hit = "aws-secret-context"
            if hit is not None:
                add("high", "SECRET-SHAPED-LINE", path,
                    f"an added line matches a secret shape ({hit}); "
                    "value not shown", line=lineno)
        if c.status == "deleted":
            add("high", "LARGE-DELETION", path,
                "a whole file is deleted in this diff")
        elif c.deleted_count >= LARGE_FILE_DELETION:
            add("high", "LARGE-DELETION", path,
                f"this file loses {c.deleted_count} lines "
                f"(threshold {LARGE_FILE_DELETION})")
        if c.is_binary:
            add("medium", "BINARY", path,
                "a binary file changed; its contents cannot be reviewed "
                "from the diff")
        for sym in (symbols_by_path.get(path) or {}).get("removed", []):
            add("medium", "SYMBOL-REMOVED", path,
                f"symbol '{sym}' is defined in deleted lines and has no "
                "matching definition in the added lines of this file")
        deps = (dependents.get(path) or {}).get("dependents", [])
        if len(deps) >= MANY_DEPENDENTS:
            add("medium", "MANY-DEPENDENTS", path,
                f"{len(deps)} project files import this file and are not "
                f"in the diff (threshold {MANY_DEPENDENTS})")
    if total_deleted >= LARGE_TOTAL_DELETION and len(changes) > 1:
        add("high", "LARGE-DELETION", "(diff)",
            f"the diff deletes {total_deleted} lines in total "
            f"(threshold {LARGE_TOTAL_DELETION})")
    code_changed = [c for c in changes if not is_test_path(c.path or "")
                    and c.status != "deleted"]
    if code_changed and not any(is_test_path(c.path or "") for c in changes):
        add("info", "NO-TEST-IN-DIFF", "(diff)",
            "code files changed and no test file appears in this diff; "
            "an observation only, tests may live outside this change")
    if verify and verify.get("present"):
        # A non-pass verdict flags even when the report carries no
        # exit code: citing gaps_found in the summary while giving a
        # straightforward verdict (the pre-polish behaviour when
        # exit_code was absent) contradicted the citation.
        verdict_text = str(verify.get("verdict") or "").strip().lower()
        exit_code = verify.get("exit_code")
        non_pass_verdict = bool(verdict_text) and \
            verdict_text not in _PASS_VERDICTS
        if exit_code not in (0, None) or non_pass_verdict:
            add("high", "VERIFY-FAILED", "(verify-report)",
                f"the supplied GhostVerify report verdict is "
                f"'{verify.get('verdict')}' (exit {exit_code})")
    order = {"high": 0, "medium": 1, "info": 2}
    flags.sort(key=lambda f: (order.get(f["level"], 3), f["file"], f["rule"]))
    return flags


def verdict_for(flags: list) -> str:
    """Derive the verdict from *flags* only: any high flag means
    ``needs-attention``, any medium means ``needs-a-look``, otherwise
    ``straightforward``. (Empty input is handled earlier, in core,
    as ``could-not-review``; it never reaches here as a clean verdict.)
    """
    levels = {f["level"] for f in flags}
    if "high" in levels:
        return "needs-attention"
    if "medium" in levels:
        return "needs-a-look"
    return "straightforward"
