"""Shared helpers for GhostLift tests.

Core discovery is deliberately tolerant about *names* and strict
about *results*. Agent A owns ``src/ghostlift`` and its API was not
final when these tests were written, so core-contract tests:

* look for plausible public callables (module attributes, or a
  ``ghostlift`` class) whose names mention the job;
* try a small set of plausible call shapes (path in, text in,
  path + output dir);
* verify whatever comes back against the same ground truth the
  fixture tests use;
* skip, with the discovery outcome as the reason, if no usable
  callable is found. A skip here means "core API not available or
  not recognised", never "the behaviour passed".
"""

from __future__ import annotations

import ast
import importlib
import inspect
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"
EXAMPLES = ROOT / "examples"

# The watermark contract from README.md, checked loosely: the tokens
# must be present, exact wording may evolve with Agent A's core.
# In-file form: "ghostlift: lifted tier=2 ...". Manifest form (the
# core's primary watermark): a manifest entry with "lifted": true
# plus "tier": N, in a document that names ghostlift.
WATERMARK_RE = re.compile(r"ghostlift", re.IGNORECASE)
TIER_RE = re.compile(r"tier\"?\s*[:=]\s*\"?([123])\b", re.IGNORECASE)


def has_watermark(text: str) -> bool:
    return bool(WATERMARK_RE.search(text or ""))


def watermark_tier(text: str):
    match = TIER_RE.search(text or "")
    return int(match.group(1)) if match else None


def import_core():
    """Return the ghostlift module, or None if it is not importable."""
    try:
        return importlib.import_module("ghostlift")
    except Exception:
        return None


def _iter_package_modules(module):
    yield module
    path = getattr(module, "__path__", None)
    if path is None:
        return
    import pkgutil

    for info in pkgutil.iter_modules(path):
        try:
            yield importlib.import_module(f"{module.__name__}.{info.name}")
        except Exception:
            continue


def _candidate_callables(module, *name_fragments):
    found = []
    if module is None:
        return found
    objects = []
    for sub in _iter_package_modules(module):
        objects.append(sub)
    for attr in ("GhostLift", "Lifter", "Core"):
        obj = getattr(module, attr, None)
        if obj is not None:
            objects.append(obj)
    for obj in objects:
        for name in dir(obj):
            if name.startswith("_"):
                continue
            lowered = name.lower()
            if any(fragment in lowered for fragment in name_fragments):
                member = getattr(obj, name, None)
                if callable(member):
                    found.append((name, member))
    return found


def call_variants(func, *variant_args):
    """Try plausible call shapes; return (ok, result_or_last_exception).

    Every variant is tried: a callable that rejects one shape (for
    example a function that wants bytes, not a path) may accept the
    next. Only a returned value counts as success.
    """
    last_exc = None
    for args in variant_args:
        try:
            return True, func(*args)
        except Exception as exc:
            last_exc = exc
            continue
    return False, last_exc


def texts_from_result(result, out_dir=None):
    """Collect text outputs from a core call result, best effort."""
    texts: list[str] = []
    if isinstance(result, str):
        texts.append(result)
    elif isinstance(result, (bytes, bytearray)):
        texts.append(bytes(result).decode("utf-8", errors="replace"))
    elif isinstance(result, pathlib.Path) and result.is_file():
        texts.append(result.read_text(errors="replace"))
    elif hasattr(result, "recovered"):  # SourceMapResult-shaped
        texts.extend(texts_from_result(list(result.recovered), out_dir))
    elif hasattr(result, "content"):  # RecoveredSource-shaped
        texts.extend(texts_from_result(result.content, out_dir))
    elif isinstance(result, dict):
        for value in result.values():
            texts.extend(texts_from_result(value, out_dir))
    elif isinstance(result, (list, tuple)):
        for value in result:
            texts.extend(texts_from_result(value, out_dir))
    if out_dir is not None and pathlib.Path(out_dir).is_dir():
        for path in sorted(pathlib.Path(out_dir).rglob("*")):
            if path.is_file():
                try:
                    texts.append(path.read_text(errors="replace"))
                except OSError:
                    pass
    return texts


def python_signatures(source_text: str):
    """{(qualname): [arg names]} for functions/classes in Python source."""
    tree = ast.parse(source_text)
    signatures = {}

    def visit(node, prefix=""):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qual = prefix + child.name
                args = [a.arg for a in child.args.posonlyargs + child.args.args]
                signatures[qual] = args
                visit(child, qual + ".")
            elif isinstance(child, ast.ClassDef):
                qual = prefix + child.name
                signatures[qual] = []
                visit(child, qual + ".")
            else:
                visit(child, prefix)

    visit(tree)
    return signatures


def signature_names_from_text(text: str):
    """Best-effort function/class names from source or outline text."""
    names = set()
    for match in re.finditer(r"\bdef\s+([A-Za-z_]\w*)\s*\(", text or ""):
        names.add(match.group(1))
    for match in re.finditer(r"\bclass\s+([A-Za-z_]\w*)", text or ""):
        names.add(match.group(1))
    for match in re.finditer(r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\(", text or ""):
        names.add(match.group(1))
    return names
