"""User slicer plugins (v0.23, G18): teach GhostSlice a new language
(or replace a built-in slicer) without forking.

A plugin is a plain Python file. Loading one EXECUTES it — plugins
are user code and run with your full privileges. GhostSlice
therefore never auto-discovers plugins: there is no plugin
directory scan, no entry-point lookup, no environment variable.
A plugin loads only when it is named explicitly, in exactly two
places:

  - the project profile:  "plugins": ["tools/lua_slicer.py", ...]
    Paths are relative to the project root and must RESOLVE inside
    it (symlinks are followed before the check, so a link pointing
    outside the project is refused) — a profile that travels with a
    cloned repository cannot make GhostSlice execute code that
    lives outside that repository.
  - the CLI:  --plugin PATH (repeatable) on export / slice / task /
    watch. The path is used exactly as given (relative to your
    shell's working directory): you typed it, it is your code.

Every load is announced on stderr by the CLI, with the trust
warning, so a plugin never loads silently.

Contract — two styles, both documented in README "Plugins":

  1. Module attributes:
       LANGUAGE = "lua"
       EXTENSIONS = [".lua"]
       def slice_text(path, text, mode) -> str: ...
       def outline(path, text) -> list[dict]: ...   # optional

  2. A register(api) function:
       def register(api):
           api.register_slicer("lua", [".lua"], slice_text,
                               outline=outline)   # outline optional

The api object exposes `api.estimate_tokens(text, language=None)`,
`api.MODES` (the mode names every slicer receives), and
`api.register_slicer(...)`.

Mode discipline: the core handles "full" and "exclude" itself and
never passes them to a plugin; a plugin receives the resolved mode
for its language's files ("signatures", "interfaces",
"strip-tests", "structure", "headings") and returns the input
unchanged for modes it does not handle. A test file in
"strip-tests" mode is dropped whole by the core, as for every
language.

Outlines: outline(path, text) returns a list of dicts with keys
"name" (required), "kind" (default "function"), "start" / "end"
(0-based line numbers, end inclusive), and optional "qualified",
"parent", "head_end". A language whose plugin provides no outline
honestly reports "no symbol outline", exactly like the built-in
notebook/markdown/config languages.

Failure discipline:
  - A plugin that fails to LOAD (unreadable, syntax error, missing
    or invalid contract, contract violation below) raises
    PluginError before anything is written; the CLI exits 2.
  - A plugin that RAISES while slicing or outlining a file does
    not kill the run: that file falls back to its full text (or to
    "no outline"), and the failure is recorded on the active
    PluginSet and in the bundle manifest's "plugin_errors".
  - A slicer returning bytes is decoded as UTF-8 (a documented
    coercion); any other non-str return is a plugin error and
    falls back the same way.
  - Claiming a BUILT-IN language, or an extension a built-in
    language already owns, is refused unless the caller explicitly
    allows overrides (CLI --allow-plugin-override). Between
    plugins in one set, the last registration for a language wins
    (recorded in the set's notes and printed by the CLI).
  - Nothing here sandboxes anything: a plugin can loop forever or
    read your disk, like any code you run. Only load plugins you
    trust. That is the whole trust model, stated plainly.

Cache interaction (cache.py): when a plugin set is active, the
set's digest — a sha256 over each registration's language, resolved
path, and plugin file bytes — becomes the content cache's
namespace dimension, so editing a plugin (or swapping which plugin
serves a language) invalidates every cached slice/outline/scan
derivation instead of silently reusing the old plugin's output.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from .tokens import estimate_tokens as _estimate_tokens

__all__ = [
    "PluginError", "LoadedPlugin", "PluginSet", "PluginAPI",
    "load_for_project", "activate", "activated", "reset",
    "active_set", "active_digest", "language_for_ext",
    "slicer_for", "outline_for", "has_slicer", "has_outline",
    "try_slice", "try_outline", "record_error", "report_loaded",
    "TRUST_WARNING",
]

TRUST_WARNING = (
    "plugins are user code and run with your full privileges; "
    "only load plugins you trust")

_LANGUAGE_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_EXTENSION_RE = re.compile(r"^\.[a-z0-9][a-z0-9_-]{0,15}$")


class PluginError(ValueError):
    """A plugin could not be loaded or its contract is invalid.

    A ValueError so the CLI's existing invalid-input handling maps
    it to exit 2 and library callers see the same exception family
    as a malformed profile."""


@dataclass
class LoadedPlugin:
    name: str                 # display name (module NAME or file stem)
    language: str
    extensions: tuple         # tuple[str, ...], normalised ".lua" form
    source_label: str         # the path exactly as the user named it
    resolved: str             # absolute resolved path (digest input)
    sha256: str               # sha256 of the plugin file bytes
    slicer: object            # callable(path, text, mode) -> str
    outline: object = None    # callable(path, text) -> list[dict] | None


@dataclass
class PluginSet:
    """One load operation's registrations plus the runtime errors
    recorded while the set was active."""
    plugins: list = field(default_factory=list)        # [LoadedPlugin]
    notes: list = field(default_factory=list)          # load-time notes
    errors: list = field(default_factory=list)         # runtime failures
    _error_keys: set = field(default_factory=set, repr=False)

    @property
    def by_language(self) -> dict:
        return {p.language: p for p in self.plugins}

    @property
    def by_ext(self) -> dict:
        out: dict = {}
        for p in self.plugins:
            for ext in p.extensions:
                out[ext] = p.language
        return out

    @property
    def digest(self) -> str:
        """Cache namespace for this set: a hash of every input that
        can change a plugin's behaviour (which file, which bytes,
        which language). "" for an empty set (the pre-plugin key
        space, apart from the gs-version dimension)."""
        if not self.plugins:
            return ""
        dims = [{"language": p.language, "path": p.resolved,
                 "sha": p.sha256} for p in self.plugins]
        dims.sort(key=lambda d: (d["language"], d["path"]))
        blob = json.dumps(dims, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def record(self, *, kind: str, path: str, language: str,
               mode: str | None, error: str) -> None:
        key = (kind, path, language, mode, error)
        if key in self._error_keys:
            return
        self._error_keys.add(key)
        self.errors.append({
            "kind": kind, "path": path, "language": language,
            "mode": mode, "error": error,
        })

    def manifest_plugins(self) -> list:
        return [{
            "name": p.name, "language": p.language,
            "extensions": list(p.extensions), "source": p.source_label,
            "sha256": p.sha256,
        } for p in self.plugins]


class PluginAPI:
    """The object handed to a plugin's register(api) function."""

    @property
    def MODES(self) -> tuple:
        from .slicer import MODES
        return MODES

    @staticmethod
    def estimate_tokens(text: str, language: str | None = None) -> int:
        return _estimate_tokens(text, language)

    def __init__(self):
        self.registrations: list = []

    def register_slicer(self, language, extensions, slicer, outline=None):
        self.registrations.append((language, extensions, slicer, outline))


# ---------------------------------------------------------------------------
# The active registry (one per process; CLI commands set it once,
# library entry points set it for the duration of a call)
# ---------------------------------------------------------------------------

_ACTIVE: PluginSet | None = None


def active_set() -> PluginSet | None:
    return _ACTIVE


def activate(pset: PluginSet | None) -> None:
    """Install `pset` as the process-wide active set (an empty set
    is a real value: it means "this run has no plugins")."""
    global _ACTIVE
    _ACTIVE = pset


def reset() -> None:
    global _ACTIVE
    _ACTIVE = None


@contextmanager
def activated(pset: PluginSet | None):
    """Install `pset` for the block, restoring whatever was active."""
    global _ACTIVE
    previous = _ACTIVE
    _ACTIVE = pset
    try:
        yield pset
    finally:
        _ACTIVE = previous


def active_digest() -> str:
    return _ACTIVE.digest if _ACTIVE is not None else ""


def language_for_ext(ext: str) -> str | None:
    if _ACTIVE is None:
        return None
    return _ACTIVE.by_ext.get(ext)


def slicer_for(language: str) -> LoadedPlugin | None:
    if _ACTIVE is None:
        return None
    return _ACTIVE.by_language.get(language)


def outline_for(language: str) -> LoadedPlugin | None:
    lp = slicer_for(language)
    if lp is None or lp.outline is None:
        return None
    return lp


def has_slicer(language: str) -> bool:
    return slicer_for(language) is not None


def has_outline(language: str) -> bool:
    return outline_for(language) is not None


def record_error(*, kind: str, path: str, language: str,
                 mode: str | None, error: str) -> None:
    if _ACTIVE is not None:
        _ACTIVE.record(kind=kind, path=path, language=language,
                       mode=mode, error=error)


def _exc_text(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def try_slice(language: str, source: str, mode: str, path: str) -> str | None:
    """Run the active plugin slicer for `language`, or None when no
    plugin serves it. Failure discipline (see module docstring): a
    raise or an unusable return falls back to the full source and is
    recorded; bytes decode as UTF-8."""
    lp = slicer_for(language)
    if lp is None:
        return None
    try:
        out = lp.slicer(path, source, mode)
    except KeyboardInterrupt:
        raise
    except BaseException as exc:
        # BaseException, not just Exception: a plugin calling
        # sys.exit() must not kill the run either (audit F1). A
        # real KeyboardInterrupt still propagates.
        record_error(kind="slice", path=path, language=language,
                     mode=mode, error=_exc_text(exc))
        return source
    if isinstance(out, str):
        return out
    if isinstance(out, (bytes, bytearray)):
        try:
            return bytes(out).decode("utf-8")
        except UnicodeDecodeError as exc:
            record_error(kind="slice", path=path, language=language,
                         mode=mode,
                         error=f"plugin returned non-UTF-8 bytes: {exc}")
            return source
    record_error(kind="slice", path=path, language=language, mode=mode,
                 error=f"plugin returned {type(out).__name__}, expected str")
    return source


def try_outline(language: str, source: str, path: str) -> list | None:
    """Run the active plugin outline fn for `language` and convert
    its rows to symslice.Symbol objects. None when the language has
    no plugin outline, or when the outline fails / is malformed
    (the failure is recorded; "no outline" is the honest result)."""
    lp = outline_for(language)
    if lp is None:
        return None
    try:
        rows = lp.outline(path, source)
    except KeyboardInterrupt:
        raise
    except BaseException as exc:
        record_error(kind="outline", path=path, language=language,
                     mode=None, error=_exc_text(exc))
        return None
    if rows is None:
        return None
    if not isinstance(rows, (list, tuple)):
        record_error(kind="outline", path=path, language=language,
                     mode=None,
                     error=f"outline returned {type(rows).__name__}, "
                           "expected a list of dicts")
        return None
    from .symslice import Symbol
    n_lines = len(source.splitlines())
    out: list = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str) \
                or not row.get("name"):
            record_error(kind="outline", path=path, language=language,
                         mode=None,
                         error="outline row is not a dict with a "
                               "non-empty 'name' string; row skipped")
            continue
        try:
            start = int(row.get("start", 0))
            end = int(row.get("end", start))
        except (TypeError, ValueError):
            record_error(kind="outline", path=path, language=language,
                         mode=None,
                         error=f"outline row for {row['name']!r} has "
                               "non-integer start/end; row skipped")
            continue
        start = max(0, min(start, max(0, n_lines - 1)))
        end = max(start, min(end, max(0, n_lines - 1)))
        head_end = row.get("head_end", start)
        try:
            head_end = int(head_end)
        except (TypeError, ValueError):
            head_end = start
        head_end = max(start, min(head_end, end))
        out.append(Symbol(
            name=row["name"],
            qualified=str(row.get("qualified") or row["name"]),
            kind=str(row.get("kind") or "function"),
            start=start, end=end, head_end=head_end, decl=start,
            parent=(str(row["parent"]) if row.get("parent") else None),
            selectable=bool(row.get("selectable", True)),
        ))
    return out


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def _builtin_tables():
    """(languages, ext->language) the core ships with. Deferred
    import: scanner imports this module, so this module must not
    import scanner at module level."""
    from .scanner import LANGUAGE_BY_EXT
    # "text" and "config" are core pseudo-languages other modules
    # branch on; a plugin must never claim them either.
    return set(LANGUAGE_BY_EXT.values()) | {"text", "config"}, \
        dict(LANGUAGE_BY_EXT)


def _validate_registration(language, extensions, slicer, outline,
                             label: str, allow_override: bool):
    """Normalise + validate one registration. Returns
    (language, extensions tuple). Raises PluginError."""
    if not isinstance(language, str) or not _LANGUAGE_RE.match(language):
        raise PluginError(
            f"plugin {label}: invalid language name {language!r} "
            "(lowercase letter, then letters/digits/-/_ , max 32 chars)")
    if not isinstance(extensions, (list, tuple)) or not extensions:
        raise PluginError(
            f"plugin {label}: extensions for {language!r} must be a "
            "non-empty list like [\".lua\"]")
    norm: list[str] = []
    for ext in extensions:
        if not isinstance(ext, str):
            raise PluginError(
                f"plugin {label}: extension {ext!r} is not a string")
        e = ext.lower()
        if not e.startswith("."):
            e = "." + e
        if not _EXTENSION_RE.match(e):
            raise PluginError(
                f"plugin {label}: invalid extension {ext!r} (a single "
                "suffix like \".lua\")")
        if e not in norm:
            norm.append(e)
    if not callable(slicer):
        raise PluginError(
            f"plugin {label}: slicer for {language!r} is not callable")
    if outline is not None and not callable(outline):
        raise PluginError(
            f"plugin {label}: outline for {language!r} is not callable")
    builtin_langs, builtin_exts = _builtin_tables()
    if language in builtin_langs and not allow_override:
        raise PluginError(
            f"plugin {label}: language {language!r} is built in; "
            "refusing to replace its slicer without an explicit "
            "override (--allow-plugin-override)")
    for e in norm:
        owner = builtin_exts.get(e)
        if owner is not None and owner != language and not allow_override:
            raise PluginError(
                f"plugin {label}: extension {e!r} already belongs to "
                f"built-in language {owner!r}; refusing to reassign "
                "it without an explicit override "
                "(--allow-plugin-override)")
    return language, tuple(norm)


def _load_file(resolved: Path, label: str, allow_override: bool,
               pset: PluginSet) -> None:
    """Execute one plugin file and add its registrations to `pset`.

    Raises PluginError on any load/contract failure; the caller
    aborts the whole load (fail fast, before anything is written).
    """
    try:
        blob = resolved.read_bytes()
    except OSError as exc:
        raise PluginError(f"plugin {label}: cannot read: {exc}") from exc
    sha = hashlib.sha256(blob).hexdigest()
    mod_name = f"ghostslice_plugin_{sha[:12]}"
    try:
        spec = importlib.util.spec_from_file_location(mod_name, resolved)
        if spec is None or spec.loader is None:
            raise PluginError(f"plugin {label}: not a loadable Python file")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except PluginError:
        raise
    except KeyboardInterrupt:
        raise
    except BaseException as exc:
        # BaseException: a plugin calling sys.exit() at import time
        # is a load failure with a message, not a silent exit with
        # the plugin's chosen code (audit F1).
        raise PluginError(
            f"plugin {label}: failed to load: {_exc_text(exc)}") from exc

    raw: list = []
    register = getattr(module, "register", None)
    if callable(register):
        api = PluginAPI()
        try:
            register(api)
        except KeyboardInterrupt:
            raise
        except BaseException as exc:
            raise PluginError(
                f"plugin {label}: register() raised: "
                f"{_exc_text(exc)}") from exc
        raw = list(api.registrations)
        if not raw:
            raise PluginError(
                f"plugin {label}: register() registered no slicer")
    elif hasattr(module, "LANGUAGE") or hasattr(module, "EXTENSIONS") \
            or hasattr(module, "slice_text"):
        missing = [attr for attr in ("LANGUAGE", "EXTENSIONS", "slice_text")
                   if not hasattr(module, attr)]
        if missing:
            raise PluginError(
                f"plugin {label}: incomplete contract: missing "
                f"{', '.join(missing)} (define LANGUAGE, EXTENSIONS and "
                "slice_text, or a register(api) function)")
        raw = [(module.LANGUAGE, module.EXTENSIONS, module.slice_text,
                getattr(module, "outline", None))]
    else:
        raise PluginError(
            f"plugin {label}: no plugin contract found (define LANGUAGE, "
            "EXTENSIONS and slice_text, or a register(api) function)")

    display = getattr(module, "NAME", None)
    if not isinstance(display, str) or not display:
        display = resolved.stem
    for language, extensions, slicer, outline in raw:
        language, exts = _validate_registration(
            language, extensions, slicer, outline, label, allow_override)
        lp = LoadedPlugin(
            name=display, language=language, extensions=exts,
            source_label=label, resolved=str(resolved), sha256=sha,
            slicer=slicer, outline=outline)
        for old in list(pset.plugins):
            if old.language == language:
                pset.plugins.remove(old)
                pset.notes.append(
                    f"plugin {label} replaces {old.source_label} "
                    f"for language {language!r} (last loaded wins)")
        for other in pset.plugins:
            for e in exts:
                if e in other.extensions:
                    pset.notes.append(
                        f"plugin {label} claims extension {e!r} "
                        f"already claimed by {other.source_label} "
                        f"for language {other.language!r}; the later "
                        "plugin wins the extension")
        pset.plugins.append(lp)


def load_for_project(root, profile=None, extra_paths=(),
                     allow_override: bool = False) -> PluginSet:
    """Load every plugin named for a project: the profile's
    "plugins" entries (relative to, and contained in, the project
    root) followed by `extra_paths` (CLI --plugin values, used as
    given). Returns a PluginSet — empty when nothing is named.

    Raises PluginError on the first failure: a half-loaded plugin
    set is never activated.
    """
    pset = PluginSet()
    root_path = Path(root)
    base = root_path if root_path.is_dir() else root_path.parent
    root_resolved = base.resolve()
    if profile is None:
        # The common case: the project's own profile decides.
        # Callers pass a profile only when they already loaded one
        # (the CLI) or a non-default one.
        from .profile import load_profile
        profile = load_profile(root_path)

    entries = list(getattr(profile, "plugins", None) or [])
    for entry in entries:
        if not isinstance(entry, str) or not entry:
            raise PluginError(
                f"profile {getattr(profile, 'path', None)}: 'plugins' "
                "entries must be non-empty strings")
        cand = Path(entry)
        if cand.is_absolute():
            raise PluginError(
                f"profile plugin {entry!r}: profile plugin paths must "
                "be relative to the project root")
        resolved = (root_resolved / cand).resolve()
        if not resolved.is_relative_to(root_resolved):
            raise PluginError(
                f"profile plugin {entry!r}: resolves outside the "
                f"project root ({resolved}); refused")
        if not resolved.is_file():
            raise PluginError(
                f"profile plugin {entry!r}: no such file under the "
                "project root")
        _load_file(resolved, entry, allow_override, pset)

    for given in extra_paths or ():
        cand = Path(str(given)).expanduser()
        resolved = cand.resolve()
        if not resolved.exists():
            raise PluginError(f"plugin {given!r}: no such file")
        if not resolved.is_file():
            raise PluginError(f"plugin {given!r}: not a file")
        _load_file(resolved, str(given), allow_override, pset)
    return pset


def report_loaded(pset: PluginSet | None, stream) -> None:
    """The CLI's load announcement: one line per plugin, the set's
    notes, and the trust warning once. Nothing when no plugins —
    silence is the default experience."""
    if pset is None or not pset.plugins:
        return
    for p in pset.plugins:
        print(f"plugins: loaded {p.name!r} slicer for language "
              f"{p.language} ({', '.join(p.extensions)}) from "
              f"{p.source_label}", file=stream)
    for note in pset.notes:
        print(f"plugins: {note}", file=stream)
    print(f"plugins: warning: {TRUST_WARNING}.", file=stream)


def report_errors(pset: PluginSet | None, stream) -> None:
    """Print the active set's recorded runtime plugin errors."""
    if pset is None or not pset.errors:
        return
    for err in pset.errors:
        where = err["path"] or "(unknown file)"
        mode = f" mode {err['mode']}" if err.get("mode") else ""
        fallback = ("treated as no outline"
                    if err["kind"].startswith("outline")
                    else "full text used instead")
        print(f"plugins: warning: {err['kind']} failed for {where} "
              f"({err['language']}{mode}): {err['error']} — "
              f"{fallback}", file=stream)
