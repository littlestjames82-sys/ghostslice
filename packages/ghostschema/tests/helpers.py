"""Shared helpers for the GhostSchema test suite.

The suite is black-box: it drives the PLAN-specified CLI

    ghostschema inspect <spec>
    ghostschema slice <spec> [--task "..."] [--select <ids>] [--all] -o <bundle>

and never imports GhostSchema internals, so it stays valid whatever
module layout the core build uses. CLI discovery order:

1. ``GHOSTSCHEMA_CMD`` env var (a shell-style command prefix).
2. A ``ghostschema`` executable on PATH (installed console script).
3. ``python -m ghostschema`` with ``PYTHONPATH`` set to ``src/`` and
   then to the repo root (covers a ``src/`` layout and a flat layout).

If none of those responds to ``--help``, CLI tests skip with an
explicit reason instead of failing: the fixture tests still run and
still validate the planted fixtures. Assumptions are recorded in
REPORT_B.md.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"

PETSTORE = FIXTURES / "petstore.json"
PARTS_SCHEMA = FIXTURES / "parts-schema.json"
SDL_SCHEMA = FIXTURES / "schema.graphql"
YAML_SPEC = FIXTURES / "petstore.yaml"
YAML_IN_JSON = FIXTURES / "yaml-in-json.json"
SWAGGER2 = FIXTURES / "swagger2.json"

_CLI_PREFIX: list[str] | None = None
_CLI_ENV: dict | None = None
_CLI_PROBED = False


def _probe(prefix: list[str], env_extra: dict | None = None) -> bool:
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    try:
        proc = subprocess.run(
            prefix + ["--help"],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
    except Exception:
        return False
    return proc.returncode == 0


def find_cli() -> tuple[list[str] | None, dict | None]:
    """Return (command prefix, extra env) for the GhostSchema CLI."""
    global _CLI_PREFIX, _CLI_ENV, _CLI_PROBED
    if _CLI_PROBED:
        return _CLI_PREFIX, _CLI_ENV
    _CLI_PROBED = True

    cmd = os.environ.get("GHOSTSCHEMA_CMD")
    if cmd:
        prefix = shlex.split(cmd)
        if _probe(prefix):
            _CLI_PREFIX, _CLI_ENV = prefix, None
            return _CLI_PREFIX, _CLI_ENV

    script = shutil.which("ghostschema")
    if script and _probe([script]):
        _CLI_PREFIX, _CLI_ENV = [script], None
        return _CLI_PREFIX, _CLI_ENV

    for base in (REPO_ROOT / "src", REPO_ROOT):
        env = {"PYTHONPATH": str(base)}
        if _probe([sys.executable, "-m", "ghostschema"], env):
            _CLI_PREFIX = [sys.executable, "-m", "ghostschema"]
            _CLI_ENV = env
            return _CLI_PREFIX, _CLI_ENV

    return None, None


def cli_available() -> bool:
    prefix, _ = find_cli()
    return prefix is not None


def run_cli(args, timeout=120):
    """Run the GhostSchema CLI with args; returns CompletedProcess."""
    prefix, env_extra = find_cli()
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    env["NO_COLOR"] = "1"
    return subprocess.run(
        prefix + [str(a) for a in args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


def combined(proc) -> str:
    return (proc.stdout or "") + "\n" + (proc.stderr or "")


def sha256_of(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# $ref utilities: the closure check the PLAN's verification bar demands.
# These operate purely on parsed JSON, independent of the core.
# ---------------------------------------------------------------------------

def iter_refs(node, pointer=""):
    """Yield (json_pointer_of_ref_key_parent, ref_value) for every $ref."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str):
                yield pointer, value
            else:
                yield from iter_refs(value, f"{pointer}/{key}")
    elif isinstance(node, list):
        for idx, item in enumerate(node):
            yield from iter_refs(item, f"{pointer}/{idx}")


def resolve_pointer(document, ref: str):
    """Resolve a local JSON pointer ref (#/a/b) inside document.

    Returns the target node, or None when unresolvable. Handles the
    ~0 / ~1 escapes JSON Pointer requires.
    """
    if not ref.startswith("#/"):
        return None
    node = document
    for raw in ref[2:].split("/"):
        part = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            return None
    return node


def local_refs(document):
    return [ref for _, ref in iter_refs(document) if ref.startswith("#/")]


def remote_refs(document):
    return [ref for _, ref in iter_refs(document) if not ref.startswith("#/")]


def unresolved_local_refs(document):
    """Local $refs in document that do not resolve inside document."""
    return [ref for ref in local_refs(document)
            if resolve_pointer(document, ref) is None]


def reachable_schema_names(spec: dict, start_names) -> set:
    """Ground-truth reachability over #/components/schemas/* refs.

    Used by the fixture tests to prove the fixture itself encodes the
    chain the behavioural tests later assert against the real core.
    """
    schemas = spec.get("components", {}).get("schemas", {})
    seen: set = set()
    stack = list(start_names)
    while stack:
        name = stack.pop()
        if name in seen or name not in schemas:
            continue
        seen.add(name)
        for _, ref in iter_refs(schemas[name]):
            if ref.startswith("#/components/schemas/"):
                stack.append(ref.rsplit("/", 1)[-1])
    return seen


def manifest_lists(manifest: dict):
    """Normalise a manifest's kept/dropped/unresolved lists to strings.

    The PLAN fixes the fields' meanings, not their exact shape. The
    real core emits kept/dropped as objects of per-kind lists
    ({"operations": [...], "schemas": [...]}) and unresolved refs
    under ``unresolved_refs`` as {"ref": ..., "from": ...} objects.
    Tests match on substring so reasonable shape variation passes.
    """
    def flatten(value):
        out = []
        if isinstance(value, list):
            for item in value:
                out.extend(flatten(item))
        elif isinstance(value, dict):
            for item in value.values():
                out.extend(flatten(item))
            out.append(json.dumps(value, sort_keys=True))
        elif value is not None:
            out.append(str(value))
        return out

    unresolved = manifest.get("unresolved_refs", manifest.get("unresolved", []))
    return {
        "kept": flatten(manifest.get("kept", [])),
        "dropped": flatten(manifest.get("dropped", [])),
        "unresolved": flatten(unresolved),
    }


def any_entry_mentions(entries, needle: str) -> bool:
    return any(needle in entry for entry in entries)
