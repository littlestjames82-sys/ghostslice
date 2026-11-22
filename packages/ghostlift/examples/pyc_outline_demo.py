"""Reference .pyc outline lift used by the GhostLift examples and tests.

Example code under ``examples/`` only, not the GhostLift core. It
shows the Tier-3 outline idea for Python bytecode: read a ``.pyc``
file, walk its code objects, and print a pseudo-source outline of
the functions and classes inside, with argument names.

How it reads bytecode, and why: it parses the marshal byte format
with the small, limited reader below. It never uses the standard
library's marshal loader, never imports the artifact, and never
executes anything in it. That matches the GhostLift core rule (see PLAN.md):
untrusted bytecode is parsed as data, with an unsupported type or a
magic mismatch refused loudly instead of guessed at. The reader
supports the value types a simple module's code objects need
(strings, bytes, numbers, tuples, lists, code objects, references)
and the CPython 3.11+ code-object field order. Other layouts are
refused by the magic check plus a clear parse error.

Only run this demo on ``.pyc`` files you produced yourself or have
the right to inspect, such as the fixture the tests generate from
``examples/pyc_demo/sample_module.py`` at test time.

Stdlib only.
"""

from __future__ import annotations

import importlib.util
import struct

WATERMARK_PY = "# ghostlift: lifted tier=3 source=pyc reconstruction=outline"

_HEADER_SIZE = 16  # magic (4) + bit field (4) + timestamp/hash (8)
_FLAG_REF = 0x80
_MAX_DEPTH = 100  # same order of limit as the core safe parser
_UNSET = object()  # placeholder for a ref slot whose object is unfinished


class SimpleCode:
    """Just the code-object fields an outline needs."""

    def __init__(self, fields):
        # CPython 3.11+ code layout: five raw counters, then code,
        # consts, names, localsplus names/kinds, filename, name,
        # qualname, a raw firstlineno, then linetable/exceptiontable.
        (
            self.co_argcount,
            self.co_posonlyargcount,
            self.co_kwonlyargcount,
            self.co_stacksize,
            self.co_flags,
            self.co_code,
            self.co_consts,
            self.co_names,
            self.co_varnames,
            self.co_localspluskinds,
            self.co_filename,
            self.co_name,
            self.co_qualname,
            self.co_firstlineno,
            self.co_linetable,
            self.co_exceptiontable,
        ) = fields


class _Reader:
    """Minimal marshal cursor: just the value types a simple module needs."""

    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0
        self.refs: list = []

    def _take(self, count: int) -> bytes:
        if count < 0:
            # A negative size used to slice backwards and rewind pos,
            # silently desynchronising the rest of the parse.
            raise ValueError(f"negative marshal size: {count}")
        if self.pos + count > len(self.data):
            raise ValueError("marshal stream ended early")
        chunk = self.data[self.pos : self.pos + count]
        self.pos += count
        return chunk

    def _count(self, what: str) -> int:
        count = self._int32()
        if count < 0:
            raise ValueError(f"negative marshal {what} count: {count}")
        return count

    def _int32(self) -> int:
        return struct.unpack("<i", self._take(4))[0]

    def _int64(self) -> int:
        return struct.unpack("<q", self._take(8))[0]

    def read_object(self, depth: int = 0):
        """Read one marshalled value; unsupported types are refused loudly."""
        if depth > _MAX_DEPTH:
            # Without a depth limit, a deeply nested stream recursed
            # until RecursionError (or worse) instead of a refusal.
            raise ValueError(f"marshal nesting deeper than {_MAX_DEPTH}")
        type_byte = self._take(1)[0]
        flagged = bool(type_byte & _FLAG_REF)
        kind = chr(type_byte & ~_FLAG_REF)
        slot = None
        if flagged:
            slot = len(self.refs)
            self.refs.append(_UNSET)

        if kind == "N":
            value = None
        elif kind == "F":
            value = False
        elif kind == "T":
            value = True
        elif kind == "i":
            value = self._int32()
        elif kind == "I":
            value = self._int64()
        elif kind == "l":
            count = self._int32()
            sign = -1 if count < 0 else 1
            value = 0
            for i in range(abs(count)):
                digit = struct.unpack("<H", self._take(2))[0]
                value += digit * (32768**i)
            value *= sign
        elif kind == "g":
            value = struct.unpack("<d", self._take(8))[0]
        elif kind == "f":
            size = self._take(1)[0]
            value = float(self._take(size).decode("ascii"))
        elif kind == "s":
            value = self._take(self._int32())
        elif kind in ("a", "A", "u", "U", "t"):
            raw = self._take(self._int32())
            value = raw.decode("utf-8", errors="surrogateescape")
        elif kind in ("z", "Z"):
            size = self._take(1)[0]
            value = self._take(size).decode("utf-8", errors="surrogateescape")
        elif kind == "r":
            index = self._int32()
            if index < 0 or index >= len(self.refs):
                # A negative index used to wrap around to the last
                # ref (silently wrong); an out-of-range one leaked
                # IndexError instead of the documented ValueError.
                raise ValueError(f"marshal ref index out of range: {index}")
            value = self.refs[index]
            if value is _UNSET:
                raise ValueError(f"marshal ref to unfinished object: {index}")
        elif kind == "(":
            value = tuple(self.read_object(depth + 1) for _ in range(self._count("tuple")))
        elif kind == ")":
            size = self._take(1)[0]
            value = tuple(self.read_object(depth + 1) for _ in range(size))
        elif kind == "[":
            value = [self.read_object(depth + 1) for _ in range(self._count("list"))]
        elif kind in ("<", ">"):
            items = [self.read_object(depth + 1) for _ in range(self._count("set"))]
            value = items
        elif kind == "c":
            # CPython 3.11+ writes five leading counters and
            # firstlineno as raw int32 values; the rest are objects.
            fields = [self._int32() for _ in range(5)]
            fields += [self.read_object(depth + 1) for _ in range(8)]
            fields.append(self._int32())
            fields += [self.read_object(depth + 1) for _ in range(2)]
            value = SimpleCode(fields)
        else:
            raise ValueError(f"unsupported marshal type {kind!r}: this demo refuses to guess")

        if slot is not None:
            self.refs[slot] = value
        return value


def load_code_object(pyc_bytes: bytes) -> SimpleCode:
    """Return the top-level code object parsed from .pyc bytes.

    Raises:
        ValueError: the bytes are too short to be a ``.pyc``, the
            magic does not match this interpreter (a different
            Python version built the artifact), or the payload is
            not a code object.
    """
    if len(pyc_bytes) <= _HEADER_SIZE:
        raise ValueError("file too short to be a .pyc")
    magic = pyc_bytes[:4]
    if magic != importlib.util.MAGIC_NUMBER:
        raise ValueError(
            "pyc magic does not match this interpreter: the .pyc was "
            "built by a different Python version and this demo will "
            "not guess at its format"
        )
    code = _Reader(pyc_bytes[_HEADER_SIZE:]).read_object()
    if not isinstance(code, SimpleCode):
        raise ValueError("pyc payload did not contain a code object")
    return code


def _arg_names(code: SimpleCode) -> list[str]:
    # co_argcount already includes positional-only arguments.
    total = code.co_argcount + code.co_kwonlyargcount
    return list(code.co_varnames[:total])


def walk_outline(code: SimpleCode) -> list[dict]:
    """Return outline entries {qualname, name, args} in walk order."""
    entries: list[dict] = []

    def visit(current: SimpleCode, prefix: str) -> None:
        for const in current.co_consts:
            if isinstance(const, SimpleCode):
                qualname = f"{prefix}{const.co_name}" if prefix else const.co_name
                entries.append(
                    {"qualname": qualname, "name": const.co_name, "args": _arg_names(const)}
                )
                visit(const, qualname + ".")

    visit(code, "")
    return entries


def outline_pseudo_source(code: SimpleCode, original: str = "sample_module.pyc") -> str:
    """Render the outline as labelled pseudo-source text."""
    lines = [WATERMARK_PY, f"# original: {original}", ""]
    for entry in walk_outline(code):
        args = ", ".join(entry["args"])
        lines.append(f"def {entry['name']}({args}): ...  # lifted outline: {entry['qualname']}")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":  # pragma: no cover - manual demo entry
    import pathlib
    import py_compile
    import sys
    import tempfile

    source = (
        pathlib.Path(sys.argv[1])
        if len(sys.argv) > 1
        else pathlib.Path(__file__).with_name("pyc_demo") / "sample_module.py"
    )
    with tempfile.TemporaryDirectory() as tmp:
        pyc = pathlib.Path(tmp) / "sample_module.pyc"
        py_compile.compile(str(source), cfile=str(pyc), doraise=True)
        print(outline_pseudo_source(load_code_object(pyc.read_bytes()), original=pyc.name), end="")
