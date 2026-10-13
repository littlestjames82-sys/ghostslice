"""Project scanner: walks a tree, respects .gitignore, estimates tokens."""
from __future__ import annotations

import fnmatch
import os
import stat
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .detect import detect_all, head_of
from .textio import UTF16_32_LABELS, decode_bytes
from .tokens import estimate_tokens
from .workspaces import WorkspaceInfo, detect_workspaces, summarize_packages

DEFAULT_IGNORE_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "dist", "build", "out",
    "__pycache__", ".venv", "venv", "env", ".tox", ".mypy_cache",
    ".pytest_cache", ".next", ".nuxt", "coverage", ".cache", "target",
    ".idea", ".vscode", ".ghostslice_bundle", ".claude_context",
    # v0.20: the content cache is derived data — never scanned,
    # exported, or watched (cache.py).
    ".ghostslice-cache",
}

BINARY_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".bmp", ".svgz",
    ".pdf", ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".exe", ".dll", ".so", ".dylib", ".o", ".a", ".class", ".wasm",
    ".mp3", ".mp4", ".mov", ".avi", ".woff", ".woff2", ".ttf", ".eot",
    ".pyc", ".pyo", ".db", ".sqlite", ".sqlite3",
}

TEXT_EXTS = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
    ".md", ".markdown", ".txt", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini",
    ".html", ".css", ".sh", ".rb", ".go", ".rs", ".java", ".c", ".h",
    ".cpp", ".hpp", ".cc", ".cxx", ".hh", ".cs", ".php", ".swift", ".kt", ".kts", ".sql", ".xml",
    ".scala", ".sc",
    ".bash", ".zsh", ".ps1", ".psm1",
    ".ipynb",
}

LOCKFILES = {
    "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "poetry.lock",
    "Pipfile.lock", "Cargo.lock", "composer.lock", "Gemfile.lock",
    "go.sum", "uv.lock",
}

LANGUAGE_BY_EXT = {
    ".py": "python",
    ".ts": "typescript", ".tsx": "typescript",
    ".js": "javascript", ".jsx": "javascript",
    ".mjs": "javascript", ".cjs": "javascript",
    ".md": "markdown", ".markdown": "markdown", ".txt": "text", ".json": "json",
    ".go": "go", ".rs": "rust", ".java": "java", ".cs": "csharp",
    ".php": "php", ".rb": "ruby", ".kt": "kotlin", ".kts": "kotlin",
    ".swift": "swift",
    # v0.8: .h is C by convention here (C++ headers use .hpp/.hh);
    # .sc is treated as a Scala script (no competing mapping exists).
    ".c": "c", ".h": "c",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp",
    ".scala": "scala", ".sc": "scala",
    # v0.9: config/data languages for the `structure` mode. Until now
    # these extensions scanned as generic "text"; the label change is
    # the only scanner-visible difference (file set and token counts
    # are unchanged — unknown text extensions were already included).
    ".yaml": "yaml", ".yml": "yaml",
    ".toml": "toml",
    ".sql": "sql",
    ".sh": "shell", ".bash": "shell", ".zsh": "shell",
    ".ps1": "powershell", ".psm1": "powershell",
    ".ipynb": "notebook",
}


def language_for(path: str) -> str:
    return LANGUAGE_BY_EXT.get(Path(path).suffix.lower(), "text")


def is_test_file(rel: str) -> bool:
    p = Path(rel)
    name = p.name.lower()
    parts = [part.lower() for part in p.parts]
    if any(part in ("tests", "test", "__tests__", "spec", "specs") for part in parts[:-1]):
        return True
    if name.startswith("test_") or name.endswith("_test.py") or name.endswith("_test.go") \
            or name.endswith(".test.ts") \
            or name.endswith(".test.tsx") or name.endswith(".test.js") or name.endswith(".test.jsx") \
            or ".spec." in name or name.startswith("test.") or name.endswith("_spec.rb") \
            or name.endswith("_test.rb") \
            or name.endswith("test.java") or name.endswith("tests.java") \
            or name.endswith("test.cs") or name.endswith("tests.cs") \
            or name.endswith("_test.c") or name.endswith("_test.cpp") \
            or name.endswith("_test.cc") or name.endswith("_test.cxx"):
        return True
    # Case-sensitive conventions the lowercased checks above would
    # over-match (e.g. "latest.php" must not count as a PHP test file):
    orig = p.name
    if orig.endswith(("Test.php", "Tests.php", "Test.kt", "Tests.kt",
                      "Test.swift", "Tests.swift",
                      "Test.scala", "Tests.scala", "Spec.scala",
                      "Specs.scala", "Suite.scala", "Suites.scala")):
        return True
    return False


def is_lockfile(rel: str) -> bool:
    return Path(rel).name in LOCKFILES


class Gitignore:
    """Minimal .gitignore matcher: comments, negations, dir patterns, globs.

    Supports the common subset: blank/# lines, leading / anchoring,
    trailing / (dirs only), patterns without a slash matching any
    basename, patterns with a slash matching the relative path, and
    fnmatch globs (*, ?, ** treated like *).

    Rules carry a base directory (posix path relative to the project
    root, "" for the root). A rule only applies to paths under its base,
    and matching is done on the path relative to that base. Later rules
    win, so a nested .gitignore can override a parent rule for its own
    subtree (a simplification of real git semantics, which are close
    enough for scanning: last matching rule in load order decides).
    """

    def __init__(self, root: Path):
        self.root = root
        # (base, negate, pattern, dir_only)
        self.rules: list[tuple[str, bool, str, bool]] = []
        self._loaded: set[str] = set()
        self.load_dir("")

    def load_dir(self, base: str) -> None:
        """Load <root>/<base>/.gitignore if present (idempotent)."""
        if base in self._loaded:
            return
        self._loaded.add(base)
        gi = self.root / base / ".gitignore" if base else self.root / ".gitignore"
        if not gi.is_file():
            return
        try:
            lines = gi.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            lines = []
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            negate = line.startswith("!")
            if negate:
                line = line[1:]
            dir_only = line.endswith("/")
            line = line.rstrip("/").lstrip("/")
            if line:
                self.rules.append((base, negate, line, dir_only))

    def ignored(self, rel: str, is_dir: bool = False) -> bool:
        result = False
        rel_posix = rel.replace(os.sep, "/")
        for base, negate, pat, dir_only in self.rules:
            if base:
                if not (rel_posix == base or rel_posix.startswith(base + "/")):
                    continue
                sub = rel_posix[len(base) + 1:] if rel_posix != base else ""
                if not sub:
                    continue
            else:
                sub = rel_posix
            basename = Path(sub).name
            if dir_only and not is_dir:
                # A dir pattern also ignores everything under that dir.
                if "/" not in pat:
                    if pat in Path(sub).parts:
                        result = not negate
                        continue
                elif sub == pat or sub.startswith(pat + "/"):
                    result = not negate
                    continue
                else:
                    continue
            if "/" in pat:
                if fnmatch.fnmatch(sub, pat) or fnmatch.fnmatch(sub, pat + "/*") \
                        or sub == pat:
                    result = not negate
            else:
                if fnmatch.fnmatch(basename, pat) or pat in Path(sub).parts:
                    result = not negate
        return result


@dataclass
class FileEntry:
    path: str            # relative, posix style
    abspath: str
    size: int
    lines: int
    tokens: int          # estimated
    language: str
    is_test: bool = False
    is_lockfile: bool = False
    # v0.12: detect.py flags, computed head-only from the text read
    # below. detect_evidence maps kind -> evidence string (metadata
    # only, never file content) and holds hits only.
    is_generated: bool = False
    is_minified: bool = False
    is_vendored: bool = False
    detect_evidence: dict = field(default_factory=dict)
    # v0.13: owning package (workspaces.py): posix rel path of the
    # package root, "" for the root package / unpackaged root files.
    package: str = ""
    # v0.21: source encoding label (textio.decode_bytes): "utf-8"
    # unless a BOM or the Latin-1 fallback said otherwise. Token and
    # line counts are computed on the DECODED text.
    encoding: str = "utf-8"

    def to_dict(self):
        return asdict(self)


@dataclass
class ScanResult:
    root: str
    files: list[FileEntry] = field(default_factory=list)
    # v0.13: workspace detection for the scanned root (None for a
    # single-file scan and for hand-built results).
    workspaces: WorkspaceInfo | None = None

    @property
    def total_tokens(self) -> int:
        return sum(f.tokens for f in self.files)

    @property
    def total_size(self) -> int:
        return sum(f.size for f in self.files)

    def to_dict(self):
        payload = {
            "root": self.root,
            "total_tokens": self.total_tokens,
            "total_size": self.total_size,
            "file_count": len(self.files),
            "files": [f.to_dict() for f in self.files],
            "packages": summarize_packages(self),
        }
        if self.workspaces is not None:
            # v0.13 (audit G08 F1): the detection evidence itself —
            # declared-but-missing members and clamp warnings must
            # be visible somewhere, not just recorded.
            payload["workspace"] = {
                "declared": self.workspaces.declared,
                "is_monorepo": self.workspaces.is_monorepo,
                "missing": list(self.workspaces.missing),
                "warnings": list(self.workspaces.warnings),
            }
        return payload


def _looks_binary(data: bytes) -> bool:
    return b"\x00" in data[:8192]


DEFAULT_IGNORE_FILES = {".ghostslice-history.jsonl"}

# Optional profile hook: scan(root, ignore_matcher=callable) where the
# callable takes a posix rel path and returns True to exclude the file.
# Kept as a plain callable to avoid an import cycle with profile.py.

def scan(root: str | Path, ignore_matcher=None, cache=None) -> ScanResult:
    root = Path(root).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(str(root))
    if root.is_dir() and not os.access(root, os.R_OK | os.X_OK):
        # os.walk would silently yield nothing for an unreadable
        # root; an explicit error beats an empty "0 files" scan.
        raise PermissionError(str(root))
    result = ScanResult(root=str(root))
    if root.is_file():
        candidates = [(root, root.name)]
        for abspath, rel in candidates:
            _add_file(result, abspath, rel, cache=cache)
        return result

    # v0.13: detect the package layout ONCE for the whole walk;
    # every file added below is assigned its package by prefix.
    result.workspaces = detect_workspaces(root)
    package_for = result.workspaces.package_for
    gitignore = Gitignore(root)
    for dirpath, dirnames, filenames in os.walk(root):
        dirpath_p = Path(dirpath)
        rel_dir = dirpath_p.relative_to(root)
        rel_dir_posix = "" if str(rel_dir) == "." else rel_dir.as_posix()
        # Load this directory's own .gitignore before judging its contents.
        gitignore.load_dir(rel_dir_posix)
        # prune dirs in place
        keep = []
        for d in sorted(dirnames):
            rel = str(rel_dir / d) if str(rel_dir) != "." else d
            if d in DEFAULT_IGNORE_DIRS:
                continue
            if gitignore.ignored(rel.replace(os.sep, "/"), is_dir=True):
                continue
            if ignore_matcher and ignore_matcher(rel.replace(os.sep, "/")):
                continue
            keep.append(d)
        dirnames[:] = keep
        for name in sorted(filenames):
            if name in DEFAULT_IGNORE_FILES:
                continue
            abspath = dirpath_p / name
            rel = str(rel_dir / name) if str(rel_dir) != "." else name
            rel_posix = rel.replace(os.sep, "/")
            if gitignore.ignored(rel_posix, is_dir=False):
                continue
            if ignore_matcher and ignore_matcher(rel_posix):
                continue
            _add_file(result, abspath, rel_posix, package=package_for(rel_posix),
                      cache=cache)
    result.files.sort(key=lambda f: f.tokens, reverse=True)
    return result


def _add_file(result: ScanResult, abspath: Path, rel_posix: str,
              package: str = "", cache=None) -> None:
    suffix = abspath.suffix.lower()
    if suffix in BINARY_EXTS:
        return
    try:
        info = abspath.stat()
    except OSError:
        return
    if not stat.S_ISREG(info.st_mode):
        # v0.21: FIFOs, sockets and device files are not source
        # text — and opening a FIFO blocks until a writer appears,
        # so merely scanning a tree containing one hung forever
        # (G16 fuzz find). Regular files only.
        return
    try:
        data = abspath.read_bytes()
    except OSError:
        return
    # v0.21: decode once, centrally (textio). A UTF-16/32 BOM marks
    # the file as text even though its raw bytes are full of NULs —
    # the binary test below only applies to un-BOM'd bytes.
    text, encoding = decode_bytes(data)
    wide = encoding in UTF16_32_LABELS
    if not wide and _looks_binary(data):
        return
    if suffix not in TEXT_EXTS and suffix != "":
        # Unknown extension: skip unless it decodes cleanly as the
        # UTF-8 family or carries a wide BOM. A "latin-1" verdict
        # means the bytes were NOT valid UTF-8, which is exactly
        # what this gate has always rejected.
        if encoding == "latin-1":
            return
    lang = language_for(rel_posix)
    if cache is not None:
        # v0.20: the derivation below (decode, line count, token
        # estimate, detection) is a pure function of (path, bytes);
        # a content-keyed hit reproduces it exactly (cache.py).
        hit = cache.get_scan(rel_posix, data)
        if hit is not None:
            evidence = hit["evidence"]
            result.files.append(FileEntry(
                path=rel_posix,
                abspath=str(abspath),
                size=len(data),
                lines=hit["lines"],
                tokens=hit["tokens"],
                language=lang,
                is_test=is_test_file(rel_posix),
                is_lockfile=is_lockfile(rel_posix),
                is_generated="generated" in evidence,
                is_minified="minified" in evidence,
                is_vendored="vendored" in evidence,
                detect_evidence=evidence,
                package=package,
                encoding=hit["encoding"],
            ))
            return
    # Detection reuses this read: head for markers/banners/path, the
    # full text for the minified verdict (audit G07 F1). No re-read.
    evidence = detect_all(rel_posix, lang, head_of(text), text=text)
    entry = FileEntry(
        path=rel_posix,
        abspath=str(abspath),
        size=len(data),
        # v0.21: splitlines semantics — a CR-only file is not 1 line.
        lines=len(text.splitlines()),
        tokens=estimate_tokens(text, lang),
        language=lang,
        is_test=is_test_file(rel_posix),
        is_lockfile=is_lockfile(rel_posix),
        is_generated="generated" in evidence,
        is_minified="minified" in evidence,
        is_vendored="vendored" in evidence,
        detect_evidence=evidence,
        package=package,
        encoding=encoding,
    )
    result.files.append(entry)
    if cache is not None:
        cache.put_scan(rel_posix, data, tokens=entry.tokens,
                       lines=entry.lines, evidence=evidence,
                       encoding=encoding)
