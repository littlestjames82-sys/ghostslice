"""Spec loading and classification.

JSON is parsed with the stdlib. YAML is refused with a clear message:
the Python stdlib has no YAML parser and GhostSchema v0.1 does not
fake one. GraphQL SDL is detected by extension or keyword sniff.
Input files are opened read-only and never modified.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

YAML_MESSAGE = (
    "YAML specs are out of scope for GhostSchema v0.1: the Python "
    "standard library has no YAML parser and this tool does not fake "
    "one. Convert the spec to JSON first (for example with a YAML "
    "tool you trust) and re-run against the .json file."
)

SWAGGER_MESSAGE = (
    "Swagger / OpenAPI 2.0 specs are out of scope for GhostSchema "
    "v0.1 (different $ref layout: #/definitions, #/parameters). "
    "Convert the spec to OpenAPI 3.x JSON first and re-run."
)

_SDL_EXTS = {".graphql", ".gql"}
_YAML_EXTS = {".yaml", ".yml"}
_SDL_KEYWORD = re.compile(
    r"(?m)^\s*(extend\s+)?(type|interface|input|enum|union|scalar|schema|directive)\s+\w+"
)
_YAML_HINT = re.compile(r"(?m)^[\w .\"'-]+:\s")


class SchemaError(Exception):
    """User-facing failure. The CLI prints it and exits 2."""


class LoadedSpec:
    """A spec file loaded read-only and classified.

    Attributes: ``path``, ``raw`` bytes, decoded ``text``, ``format``
    (``openapi``, ``jsonschema``, or ``graphql-sdl``), ``doc`` (the
    parsed dict for JSON formats, ``None`` for SDL), ``sha256`` of
    the raw bytes, and ``size_bytes``.
    """

    def __init__(self, path: Path, raw: bytes, text: str, fmt: str, doc):
        self.path = path
        self.raw = raw
        self.text = text
        self.format = fmt  # openapi | jsonschema | graphql-sdl
        self.doc = doc  # parsed dict for JSON formats, None for SDL
        self.sha256 = hashlib.sha256(raw).hexdigest()
        self.size_bytes = len(raw)


def _looks_like_yaml(text: str) -> bool:
    """Heuristic: non-JSON text with ``key:`` lines at line starts."""
    stripped = text.strip()
    if not stripped:
        return False
    if stripped[0] in "{[":
        return False
    return bool(_YAML_HINT.search(text))


def load_spec(path) -> LoadedSpec:
    """Load and classify one spec file. The file is never modified.

    YAML files (by extension, or YAML content under another name)
    and Swagger / OpenAPI 2.0 documents are refused. GraphQL SDL is
    detected by extension (``.graphql`` / ``.gql`` / ``.graphqls``)
    or by SDL keyword sniffing on non-JSON text. Anything else must
    parse as a JSON object: an ``openapi`` key starting with ``3.``
    means OpenAPI, otherwise the document is a standalone JSON
    Schema. Raises SchemaError with the reason on any refusal.
    """
    p = Path(path)
    if not p.is_file():
        raise SchemaError(f"spec file not found: {p}")
    suffix = p.suffix.lower()
    if suffix in _YAML_EXTS:
        raise SchemaError(f"{p}: {YAML_MESSAGE}")
    try:
        raw = p.read_bytes()
    except OSError as exc:
        raise SchemaError(f"{p}: cannot read spec file: {exc}")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise SchemaError(f"{p}: not valid UTF-8 text; cannot parse statically")
    if text.startswith("\ufeff"):
        # A UTF-8 byte-order mark is an encoding artifact, not content:
        # strip it so a BOM-saved spec parses like the same spec without
        # one. The recorded sha256/size still describe the raw bytes.
        text = text[1:]
    if suffix in _SDL_EXTS:
        return LoadedSpec(p, raw, text, "graphql-sdl", None)
    try:
        doc = json.loads(text)
    except RecursionError:
        raise SchemaError(
            f"{p}: JSON is nested too deeply to parse statically"
        )
    except json.JSONDecodeError:
        if suffix in (".graphqls",):
            return LoadedSpec(p, raw, text, "graphql-sdl", None)
        if _SDL_KEYWORD.search(text):
            return LoadedSpec(p, raw, text, "graphql-sdl", None)
        if _looks_like_yaml(text):
            raise SchemaError(f"{p}: content looks like YAML. {YAML_MESSAGE}")
        raise SchemaError(
            f"{p}: not valid JSON and not recognisable GraphQL SDL; "
            "cannot parse statically"
        )
    if not isinstance(doc, dict):
        raise SchemaError(
            f"{p}: top-level JSON is a {type(doc).__name__}, not an object; "
            "not a recognisable API specification"
        )
    if "swagger" in doc:
        raise SchemaError(f"{p}: {SWAGGER_MESSAGE}")
    if "openapi" in doc:
        version = str(doc.get("openapi", ""))
        if not version.startswith("3."):
            raise SchemaError(
                f"{p}: OpenAPI version {version!r} is not 3.x; {SWAGGER_MESSAGE}"
            )
        return LoadedSpec(p, raw, text, "openapi", doc)
    return LoadedSpec(p, raw, text, "jsonschema", doc)
