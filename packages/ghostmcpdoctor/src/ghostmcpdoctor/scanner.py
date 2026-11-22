"""Discovery, parsing and SAFE normalisation of MCP client configs.

Redaction happens here, at parse time: env values, full argument lists and
URL credentials/query strings are never stored on the records this module
returns, so no later code (checks, reports, CLI) can leak them.
"""
from __future__ import annotations

import json
import posixpath
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

# Filenames recognised when a directory (or a default root) is scanned.
KNOWN_FILENAMES = ("mcp.json", ".mcp.json", ".claude.json")
KNOWN_SUFFIX_PATHS = (".cursor/mcp.json", ".vscode/mcp.json")

_SECRETISH = re.compile(r"(token|secret|key|password|passwd|auth|credential)", re.I)
_PATH_EXTS = (".js", ".mjs", ".cjs", ".ts", ".py", ".json", ".sh", ".rb", ".jar")

# Whole segments that mark a value as secret-shaped. Segment (not
# substring) matching, so "monkey", "author" and "keygen" are NOT
# secret-shaped while a "FAKE-SECRET-..." value is.
_SECRET_WORDS = {"token", "secret", "key", "password", "passwd", "auth",
                 "credential", "credentials", "apikey"}


def _secret_shaped(value: str) -> bool:
    """True when a value has a whole secret-word segment.

    Used for display fields (command basename, cwd) whose raw form is
    kept internally for checks: a secret-shaped display value is
    replaced with "[redacted]" in the inventory, mirroring the env
    rule that a secret's presence may be shown, never its value.
    """
    parts = re.split(r"[^A-Za-z0-9]+", str(value).lower())
    return any(p in _SECRET_WORDS for p in parts)


def _is_wildcard_value(value) -> bool:
    """A bare wildcard: "*" / "**", ignoring surrounding whitespace,
    including a wildcard nested one level in a list/tuple value."""
    if isinstance(value, str):
        return value.strip() in ("*", "**")
    if isinstance(value, (list, tuple)):
        return any(_is_wildcard_value(v) for v in value)
    return False


def _parse_disabled(value) -> bool:
    """Parse a disabled flag without Python's bool("false") == True
    trap: JSON booleans pass through, numbers are non-zero tests, and
    strings count only for explicit truthy spellings."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on")
    if isinstance(value, (int, float)):
        return value != 0
    return False


@dataclass
class Server:
    """One normalised server entry: the safe record only (see module docstring)."""

    name: str
    config_path: str
    client: str = "generic"
    scope: str = ""               # e.g. "projects.<dir>" for Claude Code nesting
    transport: str = "unknown"    # stdio | http | sse | unknown
    command_basename: str = ""
    command_raw: str = ""         # internal only for checks; never reported raw
    args_count: int = 0
    referenced_paths: list = field(default_factory=list)  # path-like args / cwd
    broad_path_args: list = field(default_factory=list)   # args equal to / ~ .. /*
    cwd: str = ""
    cwd_raw: str = ""             # internal only for resolution in checks
    env_keys: list = field(default_factory=list)          # NAMES only
    env_wildcard: bool = False    # an env value was a bare "*" (value discarded)
    allow_wildcard: bool = False  # alwaysAllow / autoApprove contains "*"
    url_host: str = ""
    disabled: bool = False
    is_filesystem: bool = False

    def inventory(self) -> dict:
        """The only representation reports may use. No env values, no args."""
        return {
            "name": self.name,
            "config_path": self.config_path,
            "client": self.client,
            "scope": self.scope,
            "transport": self.transport,
            "command": self.command_basename,
            "args_count": self.args_count,
            "referenced_paths": list(self.referenced_paths),
            "cwd": self.cwd,
            "env_keys": list(self.env_keys),
            "env": {k: "present" for k in self.env_keys},
            "url_host": self.url_host,
            "disabled": self.disabled,
        }


@dataclass
class ConfigScan:
    """Result of scanning one config file: status plus its server records."""

    path: str
    client: str
    status: str                   # ok | parse-error | missing
    servers: list = field(default_factory=list)
    parse_issue: str = ""         # issue code only (PARSE-ERROR), never content


def _strip_jsonc_comments(text: str) -> str:
    """Remove ``//`` and ``/* */`` comments that appear OUTSIDE strings.

    JSONC (VS Code / Cursor style) configs carry comments, but strict
    ``json.loads`` rejects them, so a perfectly readable editor config
    used to degrade to PARSE-ERROR. Stripping is string-aware: a ``//``
    inside a quoted value (a URL such as ``https://host/mcp``, an
    escaped quote, a ``/*`` in an argument) is data, not a comment, and
    is copied verbatim. Comment text is discarded here, at parse time,
    so a secret someone pasted into a comment can never reach a record,
    a report, or an error message. Non-newline comment characters are
    replaced with spaces so positions roughly line up.
    """
    out: list[str] = []
    i, n = 0, len(text)
    in_string = False
    escaped = False
    while i < n:
        ch = text[i]
        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            i += 2
            while i < n and text[i] not in "\r\n":
                i += 1
            continue  # the newline itself is copied by the main loop
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            closed = False
            while i < n:
                if text[i] == "*" and i + 1 < n and text[i + 1] == "/":
                    i += 2
                    closed = True
                    break
                out.append(text[i] if text[i] in "\r\n" else " ")
                i += 1
            if not closed:
                # Unterminated block comment: the rest was comment text.
                # The truncated remainder will fail parsing below and
                # surface as a plain PARSE-ERROR, never as echoed content.
                break
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _strip_trailing_commas(text: str) -> str:
    """Drop a comma whose next non-space token is ``}`` or ``]``.

    String-aware for the same reason as comment stripping: a comma
    inside a quoted value (``"a,]"``) is data and is never touched.
    """
    out: list[str] = []
    i, n = 0, len(text)
    in_string = False
    escaped = False
    while i < n:
        ch = text[i]
        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == ",":
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
            if j < n and text[j] in "}]":
                i += 1
                continue  # drop the trailing comma only
        out.append(ch)
        i += 1
    return "".join(out)


def strip_jsonc(text: str) -> str:
    """Return ``text`` with JSONC comments and trailing commas removed.

    The result is still just text for ``json.loads``; it is never
    stored on a record or written anywhere by this module.
    """
    return _strip_trailing_commas(_strip_jsonc_comments(text))


def parse_config_text(text: str):
    """Parse a config as strict JSON first, then as JSONC.

    Strict-first keeps plain-JSON behaviour byte-for-byte identical;
    the JSONC fallback only rescues files strict JSON rejects because
    of comments and/or trailing commas. Anything else (truncated
    files, unclosed braces, garbage) still raises ``ValueError`` so
    the caller reports a content-free PARSE-ERROR.
    """
    try:
        return json.loads(text)
    except ValueError:
        return json.loads(strip_jsonc(text))


def client_for_path(path: Path) -> str:
    """Guess the client kind (claude-code / cursor / vscode / generic) from a path."""
    parts = [p.lower() for p in path.parts]
    name = path.name.lower()
    if ".cursor" in parts or "cursor" in parts:
        return "cursor"
    if ".vscode" in parts:
        return "vscode"
    if name in (".claude.json",) or ".claude" in parts or "claude" in name:
        return "claude-code"
    return "generic"


def default_config_paths(home: Path, project: Path) -> list[Path]:
    """Default local paths (PLAN.md list). Caller filters by existence."""
    return [
        home / ".claude.json",
        home / ".claude" / "settings.json",
        home / ".config" / "claude" / "claude_desktop_config.json",
        home / ".cursor" / "mcp.json",
        home / ".config" / "mcp" / "mcp.json",
        home / ".mcp.json",
        project / ".mcp.json",
        project / ".claude.json",
        project / ".cursor" / "mcp.json",
        project / "mcp.json",
        project / ".vscode" / "mcp.json",
    ]


def expand_inputs(paths, home: Path, project: Path) -> tuple[list[Path], list[str]]:
    """Resolve user paths / defaults to a de-duplicated list of config files.

    Returns (files, missing_explicit) where missing_explicit holds string
    paths the user named explicitly that do not exist.
    """
    files: list[Path] = []
    missing: list[str] = []
    seen: set[str] = set()

    def add(p: Path):
        # De-duplicate by resolved path, not by spelling: the same
        # file named relatively and absolutely (or via a symlink)
        # is ONE config. Scanning it twice invented a spurious
        # DUPLICATE finding for every server in it. The first-seen
        # spelling is kept for reporting.
        try:
            key = str(p.resolve())
        except (OSError, RuntimeError):
            key = str(p.absolute())
        if key not in seen:
            seen.add(key)
            files.append(p)

    if not paths:
        for p in default_config_paths(home, project):
            if p.is_file():
                add(p)
        return files, missing

    for raw in paths:
        p = Path(raw).expanduser()
        if p.is_dir():
            for name in KNOWN_FILENAMES:
                cand = p / name
                if cand.is_file():
                    add(cand)
            for suffix in KNOWN_SUFFIX_PATHS:
                cand = p / suffix
                if cand.is_file():
                    add(cand)
            # A directory that IS e.g. ~/.cursor also matches plain mcp.json.
        elif p.is_file():
            add(p)
        else:
            missing.append(str(p))
    return files, missing


def _looks_like_path(token: str) -> bool:
    """True when an argument token looks like a file or directory path."""
    if not token or "=" in token or token.startswith("-"):
        return False
    if "://" in token:
        # A URL is not a filesystem path. URL args may carry
        # credentials in userinfo / path segments (the url FIELD is
        # stripped to host only for exactly this reason); storing a
        # URL arg verbatim as a "referenced path" bypassed that.
        return False
    if token in ("/", "~", "$HOME", "${HOME}", "..", "."):
        return True
    if token.startswith(("/", "~/", "./", "../", "$HOME/", "${HOME}/")):
        return True
    if token.startswith((".\\", "..\\")):
        return True
    if re.match(r"^[A-Za-z]:[\\/]", token):  # Windows drive path
        return True
    if ("/" in token or "\\" in token) and token.lower().endswith(_PATH_EXTS):
        return True
    if token.endswith("/*"):
        return True
    return False


def _is_broad_path(token: str, home: Path) -> bool:
    """True for broad roots: ``/``, home, ``~``, ``$HOME``, ``..``, drive roots, ``/*``."""
    t = token.strip()
    if not t:
        return False
    # Unify separators so Windows spellings ("..\\", "C:\\") are
    # judged by the same rules as POSIX ones.
    unified = t.replace("\\", "/")
    if unified.endswith("/*"):
        base = unified[:-2] or "/"
        return _is_broad_path(base, home)
    home_str = str(home).replace("\\", "/")
    expanded = unified.replace("${HOME}", home_str).replace("$HOME", home_str)
    if expanded == "~":
        expanded = home_str
    elif expanded.startswith("~/"):
        expanded = home_str + expanded[1:]
    # normpath collapses trailing slashes, "." and ".." components:
    # "~/", "$HOME/", "/home/user/" and "//" mean the same directories
    # as "~", "$HOME", "/home/user" and "/", and were not flagged
    # before because the comparison was a raw string equality.
    norm = posixpath.normpath(expanded)
    if norm in ("/", "//"):
        return True
    if re.match(r"^[A-Za-z]:/?$", norm):  # drive root, "C:" or "C:/"
        return True
    parts = [p for p in norm.split("/") if p not in ("", ".")]
    if parts and all(p == ".." for p in parts):
        # Pure parent traversal: "..", "../", "../..", "../../" ...
        # (a token like "../sibling/server.py" has non-".." parts
        # and is a narrow reference, not a parent-dir grant.)
        return True
    home_norm = posixpath.normpath(home_str)
    if norm == home_norm:
        return True
    # An absolute ancestor of home ("/", "/home" for "/home/user",
    # reached directly or via "~/.." / "$HOME/..") grants at least
    # everything home has, so it is at least as broad as home.
    if (norm.startswith("/") or re.match(r"^[A-Za-z]:/", norm)) \
            and home_norm.startswith(norm.rstrip("/") + "/"):
        return True
    return False


def _command_display_basename(command: str) -> str:
    """The reportable form of a command: basename ONLY.

    A command string may embed its arguments ("bash -c ...",
    "tool --api-key=..."): for such a string Path(...).name is the
    whole string, so reporting it would report a full argument list
    (and anything secret-shaped inside it), violating the
    basename-only rule, and the embedded form also hid shell
    wrappers from the SHELL-WRAPPER check. When the naive basename
    contains whitespace or "=", fall back to the basename of the
    first whitespace-separated token, truncated at any "=" (the
    part after "=" is a value, never reported; the part before it
    is a name, like an env key name). A remaining basename that is
    itself secret-shaped is replaced with "[redacted]".
    """
    raw_name = Path(command.replace("\\", "/")).name or command
    if any(c.isspace() for c in raw_name) or "=" in raw_name:
        stripped = command.strip().strip("\"'")
        first = stripped.split()[0] if stripped.split() else ""
        raw_name = Path(first.replace("\\", "/")).name or first
        raw_name = raw_name.split("=", 1)[0]
    if _secret_shaped(raw_name):
        return "[redacted]"
    return raw_name


def _safe_url_host(url: str) -> str:
    """Host only, per the secret rule: userinfo, port, path, query and
    fragment are all dropped, so nothing credential-shaped can ride
    along in the one URL field a report keeps."""
    try:
        return urlparse(url).hostname or ""
    except ValueError:
        return ""


def _normalise_server(name: str, raw, config_path: Path, client: str,
                      scope: str, home: Path) -> Server | None:
    if not isinstance(raw, dict):
        return Server(name=name, config_path=str(config_path), client=client,
                      scope=scope)  # EMPTY-SERVER territory; checks will flag it
    srv = Server(name=name, config_path=str(config_path), client=client, scope=scope)
    command = raw.get("command")
    url = raw.get("url") or raw.get("serverUrl") or ""
    args = raw.get("args") if isinstance(raw.get("args"), list) else []
    args = [a for a in args if isinstance(a, str)]

    if isinstance(command, str) and command:
        srv.transport = "stdio"
        srv.command_raw = command
        srv.command_basename = _command_display_basename(command)
    elif isinstance(url, str) and url:
        srv.transport = "sse" if str(raw.get("type", "")).lower() == "sse" else "http"
        srv.url_host = _safe_url_host(url)
    srv.args_count = len(args)

    base_dir = config_path.parent
    cwd_raw = raw.get("cwd")
    if isinstance(cwd_raw, str) and cwd_raw:
        srv.cwd_raw = cwd_raw
        if _secret_shaped(cwd_raw):
            # cwd bypassed every guard the arg paths go through: it
            # was stored verbatim AND copied into referenced_paths
            # (and from there into a MISSING-FILE finding's path).
            # Keep the raw value internal for resolution only; the
            # report shows that a cwd exists, never its value.
            srv.cwd = "[redacted]"
        else:
            srv.cwd = cwd_raw
            srv.referenced_paths.append(cwd_raw)

    haystack = " ".join([name, srv.command_basename] + args).lower()
    srv.is_filesystem = "server-filesystem" in haystack or "filesystem" in name.lower()

    for token in args:
        if _is_broad_path(token, home):
            srv.broad_path_args.append(token)
        if _looks_like_path(token) and not _SECRETISH.search(token):
            if token not in srv.referenced_paths:
                srv.referenced_paths.append(token)
        elif token in srv.broad_path_args and token not in srv.referenced_paths:
            srv.referenced_paths.append(token)
    _ = base_dir  # referenced paths resolved against config dir in checks

    env = raw.get("env")
    if isinstance(env, dict):
        srv.env_keys = sorted(str(k) for k in env.keys())
        # Values inspected ONLY for the wildcard test, then discarded.
        # The test used to be an exact "*" equality, so a value of
        # " * " or "**" (the same grant, formatted) slipped past.
        srv.env_wildcard = any(_is_wildcard_value(v) for v in env.values()) \
            or "*" in env
        if "*" in srv.env_keys:
            srv.env_wildcard = True
    for key in ("alwaysAllow", "autoApprove", "always_allow", "auto_approve"):
        lst = raw.get(key)
        if _is_wildcard_value(lst):
            # Covers a bare "*" string as well as a list containing
            # one (possibly whitespace-padded); the list-only, exact
            # "*" test missed both spellings.
            srv.allow_wildcard = True
    srv.disabled = _parse_disabled(raw.get("disabled")) \
        or _parse_disabled(raw.get("disable"))
    return srv


def _collect_servers(data: dict, config_path: Path, client: str,
                     home: Path) -> tuple[list[Server], bool]:
    """Collect normalised servers; also report a malformed container.

    A present-but-non-object server container (``mcpServers: [...]``)
    is a PARSE-ERROR per PLAN.md, not a silent "no servers": the caller
    flags the config while still keeping any servers collected from
    well-formed containers in the same file (recovery, not abort).
    Returns (servers, bad_container).
    """
    servers: list[Server] = []
    bad_container = False

    def take(container, scope: str):
        nonlocal bad_container
        if not isinstance(container, dict):
            bad_container = True
            return
        for name, raw in container.items():
            srv = _normalise_server(str(name), raw, config_path, client, scope, home)
            if srv is not None:
                servers.append(srv)

    for key in ("mcpServers", "servers"):
        if key in data:
            take(data.get(key), "")
    projects = data.get("projects")
    if isinstance(projects, dict):  # Claude Code per-project nesting
        for proj, cfg in projects.items():
            if isinstance(cfg, dict):
                for key in ("mcpServers", "servers"):
                    if key in cfg:
                        take(cfg.get(key), f"projects.{proj}")
    return servers, bad_container


def scan_config(path: Path, home: Path) -> ConfigScan:
    """Parse one config file into redacted server records (read-only).

    Unreadable or non-JSON content, a non-object top level, or a
    non-object server container yields status ``parse-error`` instead
    of raising; the file's content is never copied into the result.
    """
    client = client_for_path(path)
    scan = ConfigScan(path=str(path), client=client, status="ok")
    try:
        # utf-8-sig: tolerate a BOM (common in editor-written configs)
        # while reading plain UTF-8 unchanged.
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        data = parse_config_text(text)
    except (OSError, ValueError):
        scan.status = "parse-error"
        scan.parse_issue = "PARSE-ERROR"
        return scan
    if not isinstance(data, dict):
        scan.status = "parse-error"
        scan.parse_issue = "PARSE-ERROR"
        return scan
    servers, bad_container = _collect_servers(data, path, client, home)
    scan.servers = servers
    if bad_container:
        # PARSE-ERROR finding (raised in checks from this status), but
        # the well-formed containers in the same file were still read.
        scan.status = "parse-error"
        scan.parse_issue = "PARSE-ERROR"
    return scan


def scan_configs(files: list[Path], home: Path) -> list[ConfigScan]:
    """Scan each file in order; one bad config never blocks the others."""
    return [scan_config(p, home) for p in files]
