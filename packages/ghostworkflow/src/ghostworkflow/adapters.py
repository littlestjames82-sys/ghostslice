"""Engine discovery and invocation.

ghostworkflow never imports an engine. Each engine is invoked
through its CLI, located in this order:

1. A console script on PATH (``ghostslice``, ``ghostverify``,
   ``ghostbench``, ``ghostconsole``).
2. A checkout tree: under an explicit engine home (the
   ``--engine-home`` flag or the ``GHOSTWORKFLOW_ENGINE_HOME``
   environment variable) when one is given, otherwise as a sibling
   of the ghostworkflow checkout. A tree is ``<home>/<engine>/``
   containing ``src/<engine>/``; it is invoked as
   ``[sys.executable, "-m", <engine>]`` with
   ``PYTHONPATH=<tree>/src``.

An engine that cannot be found is reported honestly as not found;
the orchestrator records that as a failed step, never as a
fabricated report.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ENGINE_NAMES = ("ghostslice", "ghostverify", "ghostbench", "ghostconsole")

_VERSION_RE = re.compile(r"\d+\.\d+\.\d+")


@dataclass
class EngineHandle:
    """How to invoke one engine, and whether it was found at all."""

    name: str
    found: bool = False
    how: str | None = None            # "path" | "checkout" | None
    home: str | None = None           # checkout tree root, when how == "checkout"
    base_argv: list = field(default_factory=list)
    pythonpath: str | None = None     # src dir to put on PYTHONPATH
    version: str | None = None

    def describe(self) -> dict:
        """The engines-map entry for the workflow report."""
        return {
            "found": self.found,
            "version": self.version,
            "how": self.how,
            "home": self.home,
        }


def checkout_root() -> Path:
    """Root of the ghostworkflow checkout this code is running from."""
    return Path(__file__).resolve().parents[2]


def engine_homes(engine_home: str | None = None) -> list:
    """Candidate checkout homes, most specific first.

    An explicit home (flag or environment) replaces the default
    sibling search: it names THE place engine checkouts live.
    """
    explicit = engine_home or os.environ.get("GHOSTWORKFLOW_ENGINE_HOME")
    if explicit:
        return [Path(explicit).expanduser()]
    return [checkout_root().parent]


def find_engine(name: str, engine_home: str | None = None) -> EngineHandle:
    """Locate one engine CLI, PATH first, then checkout trees."""
    exe = shutil.which(name)
    if exe:
        return EngineHandle(name=name, found=True, how="path",
                            base_argv=[exe])
    for home in engine_homes(engine_home):
        tree = home / name
        package = tree / "src" / name
        if (package / "__init__.py").is_file():
            return EngineHandle(
                name=name, found=True, how="checkout", home=str(tree),
                base_argv=[sys.executable, "-m", name],
                pythonpath=str(tree / "src"))
    return EngineHandle(name=name)


def merged_env(handle: EngineHandle) -> dict:
    """Process environment for invoking an engine via this handle."""
    env = dict(os.environ)
    if handle.pythonpath:
        existing = env.get("PYTHONPATH")
        env["PYTHONPATH"] = handle.pythonpath + (
            os.pathsep + existing if existing else "")
    return env


@dataclass
class EngineResult:
    argv: list
    exit_code: int | None             # None when the run timed out
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False


def run_argv(handle: EngineHandle, args: list, timeout: int = 600) -> EngineResult:
    """Invoke an engine with an argument list; never a shell."""
    argv = list(handle.base_argv) + list(args)
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout,
            env=merged_env(handle))
        return EngineResult(argv=argv, exit_code=proc.returncode,
                            stdout=proc.stdout or "",
                            stderr=proc.stderr or "")
    except subprocess.TimeoutExpired as exc:
        return EngineResult(
            argv=argv, exit_code=None,
            stdout=(exc.stdout or b"").decode("utf-8", "replace")
            if isinstance(exc.stdout, bytes) else (exc.stdout or ""),
            stderr=(exc.stderr or b"").decode("utf-8", "replace")
            if isinstance(exc.stderr, bytes) else (exc.stderr or ""),
            timed_out=True)
    except OSError as exc:
        return EngineResult(argv=argv, exit_code=None,
                            stderr=f"could not execute: {exc}",
                            timed_out=False)


def probe_version(handle: EngineHandle, timeout: int = 60) -> str | None:
    """An engine's version string from its own CLI, or None.

    Every engine answers ``--version`` except GhostBench, whose
    version lives behind its ``version`` subcommand; both forms are
    tried. The first ``X.Y.Z`` in the output wins.
    """
    if not handle.found:
        return None
    for args in (["--version"], ["version"]):
        result = run_argv(handle, args, timeout=timeout)
        if result.exit_code == 0:
            match = _VERSION_RE.search(result.stdout + "\n" + result.stderr)
            if match:
                return match.group(0)
    return None


def discover_engines(engine_home: str | None = None) -> dict:
    """Find every engine and probe the found ones for a version."""
    handles = {}
    for name in ENGINE_NAMES:
        handle = find_engine(name, engine_home=engine_home)
        if handle.found:
            handle.version = probe_version(handle)
        handles[name] = handle
    return handles
