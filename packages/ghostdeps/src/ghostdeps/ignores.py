"""Ignore rules used by the import scanner.

Two local rule sources are honoured:

* ``.gitignore`` files, including nested files. The matcher covers the
  common Git subset used by project trees: comments, negations,
  directory-only patterns, anchored patterns, basename patterns, and
  segment-aware globs (a single ``*`` does not cross a directory
  separator, while a whole-segment ``**`` can). Later matching rules
  win.
* The ``ignore`` list in the root ``.ghostslice.json`` profile. These
  patterns are root-relative globs, following the subset GhostSlice
  documents for its profile: full-path fnmatch, basename matching for
  slash-free patterns, ``dir/**``, and leading ``**/``.

The matcher is deliberately used only for import scanning. Manifest and
lockfile discovery still reads every local manifest so dependency
evidence is not hidden by a source-file ignore rule.
"""
from __future__ import annotations

import fnmatch
import json
import re
from pathlib import Path


def _translate_git_glob(pattern: str) -> str:
    """Translate a slash-bearing gitignore glob to a regex.

    Unlike ``fnmatch``, a single ``*`` or ``?`` does not cross a path
    separator. ``**`` is special only when it is a whole path segment:
    a leading ``**/`` or middle ``/**/`` matches zero or more whole
    directories, and a trailing ``/**`` matches everything below the
    preceding directory.
    """
    out: list[str] = []
    i = 0
    n = len(pattern)
    while i < n:
        if pattern.startswith("**/", i) and \
                (i == 0 or pattern[i - 1] == "/"):
            out.append("(?:[^/]+/)*")
            i += 3
            continue
        if pattern.startswith("/**", i) and i + 3 == n:
            out.append("(?:/.*)?")
            i += 3
            continue
        ch = pattern[i]
        if ch == "*":
            out.append("[^/]*")
            i += 1
        elif ch == "?":
            out.append("[^/]")
            i += 1
        elif ch == "[":
            end = i + 1
            if end < n and pattern[end] == "!":
                end += 1
            if end < n and pattern[end] == "]":
                end += 1
            while end < n and pattern[end] != "]":
                end += 1
            if end >= n:
                out.append(re.escape(ch))
                i += 1
            else:
                body = pattern[i + 1:end]
                if body.startswith("!"):
                    body = "^" + body[1:]
                body = body.replace("\\", "\\\\")
                out.append(f"[{body}]")
                i = end + 1
        elif ch == "\\" and i + 1 < n:
            out.append(re.escape(pattern[i + 1]))
            i += 2
        else:
            out.append(re.escape(ch))
            i += 1
    return "".join(out)


def _git_pattern_matches(pattern: str, sub: str, dir_only: bool,
                         is_dir: bool) -> bool:
    """Match one gitignore pattern against a base-relative path."""
    if "/" not in pattern:
        return any(fnmatch.fnmatchcase(part, pattern)
                   for part in Path(sub).parts)

    regex = re.compile(_translate_git_glob(pattern))
    parts = sub.split("/")
    # A pattern that matches a parent directory matches everything
    # below it. For a directory-only pattern, the candidate file's own
    # full path is not a directory match; its parents still are.
    prefix_count = len(parts) if is_dir or not dir_only else len(parts) - 1
    for count in range(1, prefix_count + 1):
        if regex.fullmatch("/".join(parts[:count])):
            return True
    return False


class IgnoreMatcher:
    """Hierarchical .gitignore rules plus root GhostSlice ignore globs."""

    def __init__(self, root: Path):
        self.root = root
        # (base, negate, pattern, dir_only), in load order.
        self.rules: list[tuple[str, bool, str, bool]] = []
        self._loaded_dirs: set[str] = set()
        self.gitignore_files: list[str] = []
        self.profile_patterns: list[str] = []
        self.profile_file: str | None = None
        self.warnings: list[str] = []
        self._load_profile()
        self.load_dir("")

    # ---------------------------------------------------------- loading

    def _load_profile(self) -> None:
        path = self.root / ".ghostslice.json"
        if not path.is_file():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            self.warnings.append(
                ".ghostslice.json could not be read as JSON; "
                "its ignore list was not applied")
            return
        if not isinstance(data, dict):
            # Valid JSON of the wrong shape (a list, a bare string)
            # used to be skipped silently, indistinguishable from a
            # profile that simply has no ignore list.
            self.warnings.append(
                ".ghostslice.json top level is not an object; "
                "its ignore list was not applied")
            return
        if "ignore" not in data:
            return
        patterns = data.get("ignore")
        if not isinstance(patterns, list) or \
                not all(isinstance(p, str) for p in patterns):
            self.warnings.append(
                ".ghostslice.json ignore value is not a list of strings; "
                "it was not applied")
            return
        self.profile_patterns = [p.strip() for p in patterns if p.strip()]
        self.profile_file = ".ghostslice.json"

    def load_dir(self, base: str) -> None:
        """Load ``<base>/.gitignore`` once, if it exists."""
        if base in self._loaded_dirs:
            return
        self._loaded_dirs.add(base)
        path = self.root / base / ".gitignore" if base else \
            self.root / ".gitignore"
        if not path.is_file():
            return
        self.gitignore_files.append(path.relative_to(self.root).as_posix())
        try:
            lines = path.read_text(
                encoding="utf-8-sig", errors="replace").splitlines()
        except OSError:
            self.warnings.append(
                f"{path.relative_to(self.root).as_posix()} could not be "
                "read; its rules were not applied")
            return
        for raw in lines:
            line = raw.strip()
            if not line:
                continue
            if line.startswith("\\#") or line.startswith("\\!"):
                line = line[1:]
            elif line.startswith("#"):
                continue
            negate = line.startswith("!")
            if negate:
                line = line[1:]
            dir_only = line.endswith("/")
            line = line.rstrip("/").lstrip("/")
            if line:
                self.rules.append((base, negate, line, dir_only))

    # --------------------------------------------------------- matching

    def _gitignore_ignored(self, rel: str, is_dir: bool = False) -> bool:
        result = False
        rel_posix = rel.replace("\\", "/")
        for base, negate, pattern, dir_only in self.rules:
            if base:
                if not (rel_posix == base or
                        rel_posix.startswith(base + "/")):
                    continue
                sub = rel_posix[len(base) + 1:] \
                    if rel_posix != base else ""
                if not sub:
                    continue
            else:
                sub = rel_posix

            if _git_pattern_matches(pattern, sub, dir_only, is_dir):
                result = not negate
        return result

    @staticmethod
    def _profile_ignored(pattern: str, rel: str) -> bool:
        pat = pattern.replace("\\", "/").strip().lstrip("/")
        rel_posix = rel.replace("\\", "/")
        if not pat:
            return False
        if pat.endswith("/**"):
            prefix = pat[:-3].rstrip("/")
            return rel_posix == prefix or rel_posix.startswith(prefix + "/")
        if fnmatch.fnmatch(rel_posix, pat):
            return True
        if pat.startswith("**/") and fnmatch.fnmatch(rel_posix, pat[3:]):
            return True
        return "/" not in pat and fnmatch.fnmatch(Path(rel_posix).name, pat)

    def ignored(self, rel: str, is_dir: bool = False) -> bool:
        """True when either local rule source excludes ``rel``."""
        if self._gitignore_ignored(rel, is_dir=is_dir):
            return True
        return any(self._profile_ignored(p, rel)
                   for p in self.profile_patterns)

    # ---------------------------------------------------------- metadata

    def source_files(self) -> list[str]:
        sources = list(self.gitignore_files)
        if self.profile_file:
            sources.append(self.profile_file)
        return sources
