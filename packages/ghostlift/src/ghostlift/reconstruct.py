"""Tier 2 structured reconstruction of Python source from CodeData.

What the .pyc metadata honestly supports: module / class / function
structure, names, argument lists (positional-only, regular,
keyword-only, *args, **kwargs), async and generator markers, and
docstrings. It does not support the original statement bodies,
comments, formatting, decorator expressions, class bases, or default
argument values, because GhostLift's safe parser reads structure, not
the values a parent scope built at definition time. Lifted bodies are
therefore placeholders, with an approximate bytecode listing kept as
comments for reading. The output is labelled a reconstruction in its
own header and in the manifest, never original source.
"""

from __future__ import annotations

import opcode as _opcode_module

from .marshal_safe import CodeData
from .pyc import child_code_objects, is_class

CO_VARARGS = 0x04
CO_VARKEYWORDS = 0x08
CO_GENERATOR = 0x20
CO_COROUTINE = 0x80
CO_ASYNC_GENERATOR = 0x200

_CACHE_ENTRIES = getattr(_opcode_module, "_inline_cache_entries", {})
_OPNAME = getattr(_opcode_module, "opname", [])


def _cache_count(op: int) -> int:
    entries = _CACHE_ENTRIES
    if isinstance(entries, dict):
        return int(entries.get(op, 0))
    if isinstance(entries, (list, tuple)) and op < len(entries):
        return int(entries[op])
    return 0


def _short_repr(value, limit: int = 60) -> str:
    try:
        text = repr(value)
    except Exception:
        text = "<unrepresentable>"
    if len(text) > limit:
        text = text[: limit - 3] + "..."
    return text


def _bytecode_comment_lines(code: CodeData) -> list[str]:
    """Best-effort listing of the adaptive bytecode, for comments only.

    CPython 3.11+ bytecode is a sequence of 2-byte code units, some
    followed by inline cache units. Specialised (adaptive) opcodes and
    operand meanings are approximated; the listing is reading aid, not
    evidence, and is labelled as such where it is emitted.
    """
    raw = code.code
    lines: list[str] = []
    index = 0
    extended = 0
    while index + 1 < len(raw):
        op = raw[index]
        arg = raw[index + 1] | extended
        extended = 0
        name = _OPNAME[op] if op < len(_OPNAME) else f"<op {op}>"
        detail = ""
        if name in ("LOAD_CONST", "RETURN_CONST") and arg < len(code.consts):
            const = code.consts[arg]
            if isinstance(const, CodeData):
                detail = f" <code {const.qualname}>"
            else:
                detail = f" {_short_repr(const)}"
        elif name in ("LOAD_NAME", "STORE_NAME", "DELETE_NAME", "LOAD_ATTR",
                      "STORE_ATTR", "IMPORT_NAME", "IMPORT_FROM",
                      "LOAD_GLOBAL", "STORE_GLOBAL", "LOAD_METHOD"):
            name_index = arg >> 1 if name == "LOAD_GLOBAL" else arg
            if name_index < len(code.names):
                detail = f" {code.names[name_index]}"
        elif name in ("LOAD_FAST", "STORE_FAST", "DELETE_FAST", "LOAD_DEREF",
                      "STORE_DEREF", "LOAD_CLASSDEREF"):
            if arg < len(code.localsplusnames):
                detail = f" {code.localsplusnames[arg]}"
        elif name in ("MAKE_FUNCTION",):
            detail = f" flags={arg}"
        if name == "EXTENDED_ARG":
            extended = arg << 8
        else:
            lines.append(f"{name} {arg}{detail}".rstrip())
        index += 2 + 2 * _cache_count(op)
    return lines


def build_signature(code: CodeData) -> str:
    """Rebuild a def line (name + parameters) from code metadata.

    Covers positional-only (``/``), regular, keyword-only, ``*args``
    and ``**kwargs`` parameters, and ``async def`` for coroutines.
    Default values are not recovered: they are not in the metadata
    this parser reads.
    """
    names = list(code.localsplusnames)
    params: list[str] = []
    positional = names[: code.argcount]
    for i, name in enumerate(positional):
        params.append(name)
        if code.posonlyargcount and i == code.posonlyargcount - 1:
            params.append("/")
    index = code.argcount
    kwonly = names[index : index + code.kwonlyargcount]
    index += code.kwonlyargcount
    if code.flags & CO_VARARGS:
        if index < len(names):
            params.append("*" + names[index])
            index += 1
    elif kwonly:
        params.append("*")
    params.extend(kwonly)
    if code.flags & CO_VARKEYWORDS:
        if index < len(names):
            params.append("**" + names[index])
            index += 1
    prefix = "async def" if code.flags & (CO_COROUTINE | CO_ASYNC_GENERATOR) else "def"
    return f"{prefix} {code.name}({', '.join(params)}):"


def _docstring(code: CodeData) -> str | None:
    if is_class(code):
        # A class body's first string const is the class name itself;
        # the docstring is the first later string const that is not
        # the name or qualname.
        for const in code.consts:
            if (
                isinstance(const, str)
                and const
                and const not in (code.name, code.qualname)
            ):
                return const
        return None
    if code.consts and isinstance(code.consts[0], str) and code.consts[0]:
        if code.name == "<module>" or code.consts[0].strip():
            return code.consts[0]
    return None


def _emit_code(code: CodeData, indent: int, out: list[str]) -> None:
    pad = "    " * indent
    docstring = _docstring(code)
    if is_class(code):
        out.append(f"{pad}class {code.name}:  # lifted structure, first line {code.firstlineno}")
        out.append(f"{pad}    # class bases and decorators are not recovered in Tier 2")
        body_pad = pad + "    "
        if docstring:
            out.append(f"{body_pad}{docstring!r}")
        members = [n for n in code.names if not n.startswith("__")]
        if members:
            out.append(f"{body_pad}# class namespace names: {', '.join(members)}")
        for child in child_code_objects(code):
            _emit_child(child, indent + 1, out)
        out.append(f"{body_pad}...")
        out.append("")
        return
    out.append(f"{pad}{build_signature(code)}  # lifted structure, first line {code.firstlineno}")
    body_pad = pad + "    "
    if code.flags & CO_GENERATOR:
        out.append(f"{body_pad}# generator function in the original")
    if docstring:
        out.append(f"{body_pad}{docstring!r}")
    for child in child_code_objects(code):
        _emit_child(child, indent + 1, out)
    out.append(f"{body_pad}...")
    for line in _bytecode_comment_lines(code):
        out.append(f"{body_pad}# | {line}")
    out.append("")


def _emit_child(code: CodeData, indent: int, out: list[str]) -> None:
    pad = "    " * indent
    if code.name.startswith("<"):
        out.append(
            f"{pad}# nested code object {code.name} (line {code.firstlineno}) "
            f"is not emitted as a definition"
        )
        return
    if not code.name.isidentifier():
        out.append(f"{pad}# code object named {code.name!r} is not a valid identifier, skipped")
        return
    _emit_code(code, indent, out)


def reconstruct_source(module: CodeData, artifact_name: str) -> str:
    """Reconstruct a readable source skeleton for a module code object.

    The result starts with the Tier 2 watermark header naming
    ``artifact_name``, then emits classes and functions in definition
    order with placeholder bodies and per-function bytecode comment
    listings. It is a reconstruction, never the original source.
    """
    out: list[str] = []
    out.append("# ghostlift: lifted tier=2 source=pyc reconstruction=structured")
    out.append("# GhostLift Tier 2 structured lift - RECONSTRUCTION, not original source.")
    out.append(f"# Lifted from: {artifact_name}")
    out.append(f"# Original file name recorded in the artifact: {module.filename}")
    out.append("# Structure, signatures and docstrings come from code-object metadata.")
    out.append("# Bodies are placeholders; the trailing comment block per function is an")
    out.append("# approximate adaptive-bytecode listing kept for reading only.")
    out.append("# Default argument values, decorators and class bases are not recovered.")
    out.append("")
    docstring = _docstring(module)
    if docstring:
        out.append(f"{docstring!r}")
        out.append("")
    if module.names:
        out.append(f"# module-level names: {', '.join(module.names)}")
        out.append("")
    for child in child_code_objects(module):
        _emit_child(child, 0, out)
    if not child_code_objects(module):
        for line in _bytecode_comment_lines(module):
            out.append(f"# | {line}")
    return "\n".join(out).rstrip() + "\n"
