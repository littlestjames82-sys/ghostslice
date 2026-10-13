"""Per-project content cache: `.ghostslice-cache/` (v0.20, G15).

Repeat runs of GhostSlice re-derive the same pure functions of the
same bytes: scan tokenizes and runs detection per file, `slice_text`
estimates tokens twice per file and re-parses ASTs, outlines are
re-extracted per symbol selection. The cProfile evidence in
audits/G15_audit.md puts token estimation first and AST parsing
second in every export, so this module memoizes those derivations
on disk, keyed by content:

  key = sha256(canonical JSON of dimensions)

  slice    {gs version, estimator version, path, mode, source sha}
  symslice {gs version, estimator version, path, sorted keep set,
            source sha}
  outline  {gs version, path, source sha}
  scan     {gs version, estimator version, path, raw-bytes sha}

Every input the underlying functions actually consume is one of
those dimensions (slicer.slice_source takes path/source/mode; the
config backstop inside configslice consumes only the rendered text
and the path; scan's per-file derivation consumes the raw bytes
and the path), so a cache hit is by construction the same result
the function would have produced. A ghostslice upgrade moves the
gs-version dimension, an estimator change moves the estimator
dimension, a profile change moves the resolved mode (modes are
resolved upstream of slicing), and a content change moves the
content hash: stale entries simply miss.

Safety rules:
  - Entries are JSON envelopes {v, kind, key, payload}. A parse
    error, a shape error, or a key/kind/version mismatch counts as
    CORRUPT, reads as a miss, and the file is unlinked so the next
    store self-heals. A corrupt cache can never poison an output:
    the worst case is recompute.
  - Stores are atomic: write a temp file in the same directory,
    then os.replace. Concurrent writers (two exports racing) both
    succeed; readers see complete entries or none.
  - The cache never raises into a caller: every failure degrades
    to a miss or a dropped store, counted on the instance.
  - A byte cap (default 256 MiB) evicts oldest-mtime entries when
    a store pushes past it.
  - `.ghostslice-cache` is in scanner.DEFAULT_IGNORE_DIRS, so the
    cache is never scanned, exported, or watched. (Add it to your
    .gitignore too; it is regenerable derived data.)

Disable with the GHOSTSLICE_NO_CACHE environment variable (any
value but ""/"0") or per-call (build_bundle(use_cache=False),
`--no-cache` on the CLI). CACHE counters (hits/misses/corrupt/
stores/evictions/failures) live on the instance; `ghostslice cache
stats|clear <project>` inspects and removes the on-disk state.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

from . import __version__
from .tokens import METHOD_VERSION

CACHE_DIR_NAME = ".ghostslice-cache"
FORMAT_VERSION = 1
DEFAULT_MAX_BYTES = 256 * 1024 * 1024

_KINDS = ("slice", "symslice", "outline", "scan")


def cache_disabled_by_env() -> bool:
    v = os.environ.get("GHOSTSLICE_NO_CACHE")
    return v is not None and v not in ("", "0")


def _digest(dims: dict) -> str:
    blob = json.dumps(dims, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _source_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _is_int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


class ProjectCache:
    """One project's on-disk cache. Cheap to open: the directory
    is created lazily on the first store, and the byte total is
    walked lazily on the first store that needs it."""

    def __init__(self, root: str | Path, max_bytes: int = DEFAULT_MAX_BYTES):
        self.root = Path(root)
        self.dir = self.root / CACHE_DIR_NAME / f"v{FORMAT_VERSION}"
        self.max_bytes = max_bytes
        self.hits = 0
        self.misses = 0
        self.corrupt = 0
        self.stores = 0
        self.evictions = 0
        self.failures = 0
        self._bytes: int | None = None
        self._counter = 0
        self._stores_since_sweep = 512  # first store sweeps once

    # -- envelope I/O ------------------------------------------------

    def _path_for(self, kind: str, key: str) -> Path:
        return self.dir / kind / f"{key}.json"

    def _read(self, kind: str, key: str) -> dict | None:
        """Payload dict on a validated hit, else None (miss or
        corrupt; corrupt entries are unlinked for self-heal)."""
        path = self._path_for(kind, key)
        try:
            raw = path.read_bytes()
        except OSError:
            self.misses += 1
            return None
        try:
            env = json.loads(raw.decode("utf-8"))
            if not isinstance(env, dict) \
                    or env.get("v") != FORMAT_VERSION \
                    or env.get("kind") != kind \
                    or env.get("key") != key \
                    or not isinstance(env.get("payload"), dict):
                raise ValueError("envelope mismatch")
        except (ValueError, UnicodeDecodeError):
            self.corrupt += 1
            try:
                path.unlink()
            except OSError:
                pass
            return None
        self.hits += 1
        return env["payload"]

    def _write(self, kind: str, key: str, payload: dict) -> None:
        try:
            kind_dir = self.dir / kind
            kind_dir.mkdir(parents=True, exist_ok=True)
            env = {"v": FORMAT_VERSION, "kind": kind, "key": key,
                   "payload": payload}
            blob = json.dumps(env, ensure_ascii=True).encode("utf-8")
            self._counter += 1
            # Temp name deliberately does NOT end in .json: the
            # eviction/stats walks glob *.json and must never see
            # (or delete) an in-flight store (audit G15 F1).
            tmp = kind_dir / (f".tmp-{os.getpid()}-{self._counter}-"
                              f"{time.time_ns()}.part")
            tmp.write_bytes(blob)
            os.replace(tmp, self._path_for(kind, key))
            self.stores += 1
            if self._bytes is not None:
                self._bytes += len(blob)
            self._maybe_evict()
        except OSError:
            self.failures += 1

    def _ensure_bytes(self) -> int:
        if self._bytes is None:
            total = 0
            if self.dir.is_dir():
                for p in self.dir.rglob("*.json"):
                    try:
                        total += p.stat().st_size
                    except OSError:
                        pass
            self._bytes = total
        return self._bytes

    def _maybe_evict(self) -> None:
        # Sweep stale store-temp files occasionally (a killed
        # writer can leave them; they are invisible to the *.json
        # walks and would otherwise leak one small file per crash).
        # Occasionally, not per store: the sweep walks the cache
        # tree, and running it on every store made cold fills
        # quadratic in the entry count (audit G15 F6 — a 2,000-file
        # fill spent ~15s CPU in sweeps alone under load).
        self._stores_since_sweep += 1
        if self._stores_since_sweep >= 512:
            self._stores_since_sweep = 0
            if self.dir.is_dir():
                cutoff = time.time() - 3600
                for p in self.dir.rglob(".tmp-*"):
                    try:
                        if p.stat().st_mtime < cutoff:
                            p.unlink()
                    except OSError:
                        pass
        if self._ensure_bytes() <= self.max_bytes:
            return
        entries: list[tuple[float, int, Path]] = []
        for p in self.dir.rglob("*.json"):
            try:
                st = p.stat()
            except OSError:
                continue
            entries.append((st.st_mtime, st.st_size, p))
        entries.sort()
        total = self._bytes
        for _mtime, size, p in entries:
            if total <= self.max_bytes:
                break
            try:
                p.unlink()
            except OSError:
                continue
            total -= size
            self.evictions += 1
        self._bytes = total

    # -- slice results (slicer.slice_text) ----------------------------

    def _slice_dims(self, path: str, source: str, mode: str) -> dict:
        return {"gs": __version__, "est": METHOD_VERSION, "path": path,
                "mode": mode, "sha": _source_sha(source)}

    def get_slice(self, path: str, source: str, mode: str) -> dict | None:
        """Payload {text, original_tokens, sliced_tokens, language}
        for slice_text(path, source, mode), or None."""
        payload = self._read("slice", _digest(self._slice_dims(path, source, mode)))
        if payload is None:
            return None
        if not isinstance(payload.get("text"), str) \
                or not _is_int(payload.get("original_tokens")) \
                or not _is_int(payload.get("sliced_tokens")) \
                or not isinstance(payload.get("language"), str):
            self.corrupt += 1
            self.hits -= 1  # counted in _read; undo: this was corrupt, not a hit
            return None
        return payload

    def put_slice(self, path: str, source: str, mode: str, *,
                  text: str, original_tokens: int, sliced_tokens: int,
                  language: str) -> None:
        self._write("slice", _digest(self._slice_dims(path, source, mode)), {
            "text": text, "original_tokens": original_tokens,
            "sliced_tokens": sliced_tokens, "language": language})

    # -- symbol slices (symslice.slice_with_symbols) -------------------

    def _symslice_dims(self, path: str, source: str, keep) -> dict:
        return {"gs": __version__, "est": METHOD_VERSION, "path": path,
                "keep": sorted(keep), "sha": _source_sha(source)}

    def get_symslice(self, path: str, source: str, keep) -> str | None:
        payload = self._read(
            "symslice", _digest(self._symslice_dims(path, source, keep)))
        if payload is None:
            return None
        if not isinstance(payload.get("text"), str):
            self.corrupt += 1
            self.hits -= 1
            return None
        return payload["text"]

    def put_symslice(self, path: str, source: str, keep, text: str) -> None:
        self._write("symslice",
                    _digest(self._symslice_dims(path, source, keep)),
                    {"text": text})

    # -- symbol outlines (symslice.outline_source) ---------------------

    def _outline_dims(self, path: str, source: str) -> dict:
        return {"gs": __version__, "path": path, "sha": _source_sha(source)}

    def get_outline(self, path: str, source: str) -> list | None:
        """Payload symbol rows (list of dicts) for the file's
        outline, or None. Callers rebuild their Symbol objects."""
        payload = self._read(
            "outline", _digest(self._outline_dims(path, source)))
        if payload is None:
            return None
        rows = payload.get("symbols")
        if not isinstance(rows, list) \
                or any(not isinstance(r, dict) for r in rows):
            self.corrupt += 1
            self.hits -= 1
            return None
        return rows

    def put_outline(self, path: str, source: str, rows: list) -> None:
        self._write("outline", _digest(self._outline_dims(path, source)),
                    {"symbols": rows})

    # -- scan derivations (scanner._add_file) ----------------------------

    def _scan_dims(self, path: str, data: bytes) -> dict:
        return {"gs": __version__, "est": METHOD_VERSION, "path": path,
                "sha": hashlib.sha256(data).hexdigest()}

    def get_scan(self, path: str, data: bytes) -> dict | None:
        """Payload {tokens, lines, evidence, encoding} for a file's
        raw bytes, or None. (v0.21: entries without an encoding —
        written before the field existed — read as corrupt/miss;
        the gs-version dimension already orphans them, this is the
        belt-and-braces shape check.)"""
        payload = self._read("scan", _digest(self._scan_dims(path, data)))
        if payload is None:
            return None
        ev = payload.get("evidence")
        if not _is_int(payload.get("tokens")) \
                or not _is_int(payload.get("lines")) \
                or not isinstance(payload.get("encoding"), str) \
                or not isinstance(ev, dict) \
                or any(not isinstance(k, str) or not isinstance(v, str)
                       for k, v in ev.items()):
            self.corrupt += 1
            self.hits -= 1
            return None
        return payload

    def put_scan(self, path: str, data: bytes, *, tokens: int, lines: int,
                 evidence: dict, encoding: str = "utf-8") -> None:
        self._write("scan", _digest(self._scan_dims(path, data)), {
            "tokens": tokens, "lines": lines, "evidence": evidence,
            "encoding": encoding})

    # -- introspection ---------------------------------------------------

    def counters(self) -> dict:
        return {"hits": self.hits, "misses": self.misses,
                "corrupt": self.corrupt, "stores": self.stores,
                "evictions": self.evictions, "failures": self.failures}


def open_cache(root: str | Path) -> ProjectCache | None:
    """A ProjectCache for a project DIRECTORY, or None when caching
    is disabled by the environment or the root is not a directory
    (a single-file root has no project dir to hold the cache)."""
    if cache_disabled_by_env():
        return None
    root = Path(root)
    if not root.is_dir():
        return None
    return ProjectCache(root)


def cached_slice_text(cache: ProjectCache | None, path: str, source: str,
                      mode: str):
    """slicer.slice_text through the content cache: on a hit the
    stored SliceResult fields are returned untouched; on a miss the
    real slicer runs and its result is stored. `cache=None` is the
    plain slicer. This is the one seam every slicing surface shares
    (export loop, fit ladder, estimate_context_tokens, slice CLI),
    so they all key identically."""
    from .slicer import SliceResult, slice_text
    if cache is None:
        return slice_text(path, source, mode)
    payload = cache.get_slice(path, source, mode)
    if payload is not None:
        return SliceResult(
            path=path, mode=mode, language=payload["language"],
            original_tokens=payload["original_tokens"],
            sliced_tokens=payload["sliced_tokens"],
            text=payload["text"])
    result = slice_text(path, source, mode)
    cache.put_slice(path, source, mode, text=result.text,
                    original_tokens=result.original_tokens,
                    sliced_tokens=result.sliced_tokens,
                    language=result.language)
    return result


def cache_stats(root: str | Path) -> dict:
    """On-disk state of a project's cache: entry counts and bytes
    per kind, oldest/newest entry mtimes. No mutation."""
    base = Path(root) / CACHE_DIR_NAME / f"v{FORMAT_VERSION}"
    out: dict = {"dir": str(Path(root) / CACHE_DIR_NAME), "entries": 0,
                 "bytes": 0, "by_kind": {}, "oldest": None, "newest": None}
    if not base.is_dir():
        return out
    for kind_dir in sorted(base.iterdir()):
        if not kind_dir.is_dir():
            continue
        count = 0
        nbytes = 0
        for p in kind_dir.glob("*.json"):
            try:
                st = p.stat()
            except OSError:
                continue
            count += 1
            nbytes += st.st_size
            iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(st.st_mtime))
            if out["oldest"] is None or iso < out["oldest"]:
                out["oldest"] = iso
            if out["newest"] is None or iso > out["newest"]:
                out["newest"] = iso
        if count:
            out["by_kind"][kind_dir.name] = {"entries": count, "bytes": nbytes}
            out["entries"] += count
            out["bytes"] += nbytes
    return out


def clear_cache(root: str | Path) -> dict:
    """Remove a project's whole cache dir. Returns what was there."""
    import shutil
    stats = cache_stats(root)
    target = Path(root) / CACHE_DIR_NAME
    existed = target.is_dir()
    if existed:
        shutil.rmtree(target, ignore_errors=True)
    return {"existed": existed, "removed_entries": stats["entries"],
            "removed_bytes": stats["bytes"]}
