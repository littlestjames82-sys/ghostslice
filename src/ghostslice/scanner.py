"""Project scanner: walks a tree, respects .gitignore, estimates tokens."""
from __future__ import annotations

import fnmatch
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .tokens import estimate_tokens

DEFAULT_IGNORE_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "dist", "build", "out",
    "__pycache__", ".venv", "venv", "env", ".tox", ".mypy_cache",
    ".pytest_cache", ".next", ".nuxt", "coverage", ".cache", "target",
    ".idea", ".vscode", ".ghostslice_bundle", ".claude_context",
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
    ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini",
    ".html", ".css", ".sh", ".rb", ".go", ".rs", ".java", ".c", ".h",
    ".cpp", ".hpp", ".cs", ".php", ".swift", ".kt", ".sql", ".xml",
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
    ".md": "markdown", ".txt": "text", ".json": "json",
    ".go": "go", ".rs": "rust", ".java": "java", ".cs": "csharp",
}


def language_for(path: str) -> str:
    return LANGUAGE_BY_EXT.get(Path(path).suffix.lower(), "text")


def is_test_file(rel: str) -> bool:
    p = Path(rel)
    name = p.name.lower()
    parts = [part.lower() for part in p.parts]
    if any(part in ("tests", "test", "__tests__", "spec", "specs") for part in parts[:-1]):
        return True
    if name.startswith("test_") or name.endswith("_test.py") or name.endswith(".test.ts") \
            or name.endswith(".test.tsx") or name.endswith(".test.js") or name.endswith(".test.jsx") \
            or ".spec." in name or name.startswith("test.") or name.endswith("_spec.rb"):
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

    def to_dict(self):
        return asdict(self)


@dataclass
class ScanResult:
    root: str
    files: list[FileEntry] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return sum(f.tokens for f in self.files)

    @property
    def total_size(self) -> int:
        return sum(f.size for f in self.files)

    def to_dict(self):
        return {
            "root": self.root,
            "total_tokens": self.total_tokens,
            "total_size": self.total_size,
            "file_count": len(self.files),
            "files": [f.to_dict() for f in self.files],
        }


def _looks_binary(data: bytes) -> bool:
    return b"\x00" in data[:8192]


DEFAULT_IGNORE_FILES = {".ghostslice-history.jsonl"}

# Optional profile hook: scan(root, ignore_matcher=callable) where the
# callable takes a posix rel path and returns True to exclude the file.
# Kept as a plain callable to avoid an import cycle with profile.py.

def scan(root: str | Path, ignore_matcher=None) -> ScanResult:
    root = Path(root).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(str(root))
    result = ScanResult(root=str(root))
    if root.is_file():
        candidates = [(root, root.name)]
        for abspath, rel in candidates:
            _add_file(result, abspath, rel)
        return result

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
            _add_file(result, abspath, rel_posix)
    result.files.sort(key=lambda f: f.tokens, reverse=True)
    return result


def _add_file(result: ScanResult, abspath: Path, rel_posix: str) -> None:
    suffix = abspath.suffix.lower()
    if suffix in BINARY_EXTS:
        return
    try:
        data = abspath.read_bytes()
    except OSError:
        return
    if _looks_binary(data):
        return
    if suffix not in TEXT_EXTS and suffix != "":
        # Unknown extension: skip unless it decodes cleanly and is smallish.
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            return
    text = data.decode("utf-8", errors="replace")
    result.files.append(FileEntry(
        path=rel_posix,
        abspath=str(abspath),
        size=len(data),
        lines=text.count("\n") + (1 if text and not text.endswith("\n") else 0),
        tokens=estimate_tokens(text),
        language=language_for(rel_posix),
        is_test=is_test_file(rel_posix),
        is_lockfile=is_lockfile(rel_posix),
    ))
