"""ghostproxy doctor: one-screen health check, in the spirit of
``ghostslice doctor``. Checks: loopback host rule, port free, profile
valid, GhostSlice importable, ledger writable, and (opt-in only) an
upstream reachability probe that sends NO authentication and NO billable
request -- a bare HEAD against the upstream root.
"""
from __future__ import annotations

import http.client
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

from . import slice_adapter
from .config import ConfigError, ProxyConfig, load_profile_proxy_section
from .ledger import Ledger
from .tokens import ESTIMATOR, ESTIMATOR_VERSION, ghostslice_available


@dataclass
class Check:
    name: str
    level: str   # ok | warn | fail
    detail: str

    def line(self) -> str:
        return f"[{self.level.upper():4}] {self.name}: {self.detail}"


def _port_free(host: str, port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _upstream_probe(upstream: str, timeout: float = 5.0):
    """Return (reachable, detail). HEAD only, no auth, no body, no spend."""
    parsed = urlparse(upstream)
    conn_cls = (http.client.HTTPSConnection if parsed.scheme == "https"
                else http.client.HTTPConnection)
    conn = conn_cls(parsed.hostname, parsed.port, timeout=timeout)
    try:
        conn.request("HEAD", parsed.path or "/")
        resp = conn.getresponse()
        resp.read()
        return True, f"upstream answered HTTP {resp.status} to a HEAD probe (no auth sent)"
    except Exception as exc:
        return False, f"upstream HEAD probe failed: {type(exc).__name__}: {exc}"
    finally:
        conn.close()


def run_doctor(config: ProxyConfig, check_upstream: bool = False) -> list[Check]:
    checks: list[Check] = []

    if config.host == "127.0.0.1":
        checks.append(Check("host", "ok", "bound to 127.0.0.1 (localhost only)"))
    else:
        checks.append(Check("host", "fail", f"host is {config.host!r}, not loopback"))

    free = _port_free(config.host, config.port)
    checks.append(Check(
        "port", "ok" if free else "fail",
        f"port {config.port} is free" if free
        else f"port {config.port} is in use (proxy already running?)"))

    if config.ghostslice_project:
        try:
            load_profile_proxy_section(config.ghostslice_project)
            checks.append(Check("profile", "ok",
                                ".ghostslice.json proxy section is valid"))
        except ConfigError as exc:
            checks.append(Check("profile", "fail", str(exc)))
    else:
        checks.append(Check("profile", "warn",
                            "no project given; defaults in use"))

    if ghostslice_available():
        checks.append(Check("ghostslice", "ok",
                            f"GhostSlice importable; estimator {ESTIMATOR} "
                            f"v{ESTIMATOR_VERSION}"))
    else:
        checks.append(Check("ghostslice", "warn",
                            "GhostSlice not importable: transforms will "
                            "pass through (fail-open), budget downgrade off"))

    ledger = Ledger(config.ledger_file())
    writable = ledger.writable()  # one probe; the old code probed twice
    checks.append(Check(
        "ledger", "ok" if writable else "fail",
        f"ledger writable at {ledger.path}" if writable
        else f"ledger NOT writable at {ledger.path}"))

    checks.append(Check(
        "bodies", "ok" if not config.log_bodies else "warn",
        "request bodies are NOT logged" if not config.log_bodies
        else "log_bodies explicitly opted in by the operator"))

    if check_upstream:
        ok, detail = _upstream_probe(config.upstream)
        checks.append(Check("upstream", "ok" if ok else "warn", detail))
    else:
        checks.append(Check("upstream", "warn",
                            "not probed (pass --check-upstream for a "
                            "headers-only HEAD probe; no paid call is made)"))
    return checks


def doctor_exit_code(checks: list[Check]) -> int:
    return 1 if any(c.level == "fail" for c in checks) else 0
