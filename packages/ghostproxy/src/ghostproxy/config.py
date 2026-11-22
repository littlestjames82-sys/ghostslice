"""GhostProxy configuration.

Sources, in increasing priority: built-in defaults, the ``proxy`` section
of a project's ``.ghostslice.json`` (same profile file as GhostSlice),
then explicit CLI arguments. Unknown keys in the proxy section fail
loudly (house rule shared with GhostSlice lint/profile behaviour).

Hard rules enforced here, not preferences:
- host must be a loopback literal (127.0.0.1, ::1, or "localhost");
- request bodies are never logged by default: log_bodies is False
  unless the operator passes the explicit serve flag. A profile file
  CANNOT turn body logging on (README trust rule); a ``log_bodies``
  key in the profile proxy section is accepted but ignored. The
  v0.1 ledger schema contains no body field in any case.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787
DEFAULT_UPSTREAM = "https://api.anthropic.com"
DEFAULT_BUDGET_TOKENS = 60_000
DEFAULT_UPSTREAM_TIMEOUT = 120.0
DEFAULT_MAX_BODY_BYTES = 4 * 1024 * 1024  # larger requests pass through untouched
LOOPBACK_HOSTS = ("127.0.0.1", "::1", "localhost")

_PROFILE_KEYS = {
    "host", "port", "upstream", "budget_tokens", "enabled",
    "upstream_timeout", "max_body_bytes", "ledger", "log_bodies",
}
_CLI_KEYS = {"host", "port", "upstream", "budget_tokens", "project",
             "ledger_path", "ghostslice_project", "enabled",
             "upstream_timeout", "max_body_bytes", "log_bodies"}


class ConfigError(ValueError):
    pass


@dataclass
class ProxyConfig:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    upstream: str = DEFAULT_UPSTREAM
    budget_tokens: int = DEFAULT_BUDGET_TOKENS
    project: str = ""                 # project label recorded in the ledger
    ghostslice_project: str = ""      # project dir whose .ghostslice.json is read
    ledger_path: str = ""             # default: <cwd>/.ghostproxy-ledger.jsonl
    enabled: bool = True              # per-project on/off from the profile
    upstream_timeout: float = DEFAULT_UPSTREAM_TIMEOUT
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES
    log_bodies: bool = False          # explicit opt-in only; see module docstring

    def __post_init__(self):
        if self.host not in LOOPBACK_HOSTS:
            raise ConfigError(
                f"refusing to bind non-loopback host {self.host!r}: "
                "GhostProxy v0.1 is localhost only (127.0.0.1)")
        # Normalise "localhost" to the literal so binding is unambiguous.
        if self.host == "localhost":
            self.host = "127.0.0.1"
        # bool is an int subclass: True must not silently become port 1.
        for name in ("port", "budget_tokens", "max_body_bytes"):
            if isinstance(getattr(self, name), bool):
                raise ConfigError(f"{name} must be a number, not a boolean")
        if isinstance(self.upstream_timeout, bool):
            raise ConfigError("upstream_timeout must be a number, not a boolean")
        for name in ("enabled", "log_bodies"):
            if not isinstance(getattr(self, name), bool):
                raise ConfigError(
                    f"{name} must be true or false "
                    f"(got {getattr(self, name)!r})")
        try:
            port_int = int(self.port)
            budget_int = int(self.budget_tokens)
            max_body_int = int(self.max_body_bytes)
            timeout_f = float(self.upstream_timeout)
        except (TypeError, ValueError) as exc:
            raise ConfigError(
                f"port, budget_tokens, max_body_bytes and upstream_timeout "
                f"must be numbers (got port={self.port!r}, "
                f"budget_tokens={self.budget_tokens!r}, "
                f"max_body_bytes={self.max_body_bytes!r}, "
                f"upstream_timeout={self.upstream_timeout!r})"
            ) from exc
        # int("8787") / int(87.5) coerce; a non-integral float or a
        # numeric string that int() accepts is fine, but reject values
        # int() would silently truncate or that are not real numbers.
        if isinstance(self.port, float) and not self.port.is_integer():
            raise ConfigError(f"invalid port: {self.port!r}")
        if not (0 <= port_int <= 65535):  # 0 = OS-assigned (tests)
            raise ConfigError(f"invalid port: {self.port!r}")
        if budget_int < 0:
            raise ConfigError("budget_tokens must be >= 0")
        if max_body_int < 0:
            raise ConfigError("max_body_bytes must be >= 0")
        if not (timeout_f > 0) or not math.isfinite(timeout_f):
            raise ConfigError("upstream_timeout must be a positive, finite number")
        if not isinstance(self.upstream, str) or not (
                self.upstream.startswith("http://")
                or self.upstream.startswith("https://")):
            raise ConfigError(f"upstream must be an http(s) URL: {self.upstream!r}")
        parsed = urlparse(self.upstream)
        if not parsed.hostname:
            raise ConfigError(
                f"upstream URL has no host: {self.upstream!r}")
        try:
            _ = parsed.port  # raises ValueError for ":abc" / out of range
        except ValueError as exc:
            raise ConfigError(
                f"upstream URL has an invalid port: {self.upstream!r}"
            ) from exc
        self.port = port_int
        self.budget_tokens = budget_int
        self.max_body_bytes = max_body_int
        self.upstream_timeout = timeout_f

    def ledger_file(self) -> Path:
        if self.ledger_path:
            return Path(self.ledger_path)
        # Per-project ledger next to the project when one is known (this is
        # what `ghostproxy report --project <dir>` reads back).
        for cand in (self.ghostslice_project, self.project):
            if cand and Path(cand).is_dir():
                return Path(cand) / ".ghostproxy-ledger.jsonl"
        return Path.cwd() / ".ghostproxy-ledger.jsonl"


def load_profile_proxy_section(project_dir: str | Path) -> dict:
    """Read the ``proxy`` section of <project>/.ghostslice.json.

    Returns {} when the file or section is absent. Raises ConfigError on
    malformed JSON or unknown proxy keys (fail loudly, per plan).
    """
    profile = Path(project_dir) / ".ghostslice.json"
    if not profile.is_file():
        return {}
    try:
        data = json.loads(profile.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ConfigError(f"cannot parse {profile}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{profile}: top level must be an object")
    section = data.get("proxy", {})
    if section is None:
        return {}
    if not isinstance(section, dict):
        raise ConfigError(f"{profile}: 'proxy' section must be an object")
    unknown = sorted(set(section) - _PROFILE_KEYS)
    if unknown:
        raise ConfigError(
            f"{profile}: unknown proxy keys: {', '.join(unknown)}")
    out = dict(section)
    if "ledger" in out:
        out["ledger_path"] = out.pop("ledger")
    return out


def build_config(project_dir: str | Path | None = None,
                 overrides: dict | None = None) -> ProxyConfig:
    """Defaults <- profile proxy section <- explicit overrides."""
    values: dict = {}
    if project_dir:
        values.update(load_profile_proxy_section(project_dir))
        values.setdefault("ghostslice_project", str(project_dir))
        values.setdefault("project", str(project_dir))
    # HARD RULE (README): a profile file cannot turn body logging on.
    # The key stays a known profile key (no unknown-key error), but its
    # value is dropped here; only the explicit serve flag in
    # `overrides` may enable it. (The v0.1 ledger schema has no body
    # field regardless.)
    values.pop("log_bodies", None)
    for key, val in (overrides or {}).items():
        if val is None:
            continue
        if key not in _CLI_KEYS:
            raise ConfigError(f"unknown config override: {key}")
        values[key] = val
    values.setdefault("log_bodies", False)
    return ProxyConfig(**values)
