"""A safe, from-scratch parser for the CPython marshal byte format.

Why this exists: ``marshal.loads`` on an untrusted artifact constructs
arbitrary objects chosen by whoever wrote the bytes, and the marshal
format is explicitly not a safe format for untrusted data. GhostLift
therefore parses the byte stream itself into plain data containers plus
:class:`CodeData` records. Parsing never builds a real code object,
never imports anything named by the artifact, and never executes
anything.

Supported scope: the marshal stream of a CPython code object as written
since CPython 3.11 (the layout with localsplus names/kinds, qualname,
linetable and exceptiontable). The caller (pyc layer) pins support by
the artifact's magic number before this parser runs.

Parser limits fail loudly (SafeMarshalError) instead of consuming
unbounded resources on a hostile or corrupt stream.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

MAX_OBJECTS = 1_000_000
MAX_DEPTH = 100
MAX_STRING_BYTES = 64 * 1024 * 1024
MAX_CONTAINER_ITEMS = 1_000_000


class SafeMarshalError(ValueError):
    """Raised when a marshal stream is malformed, hostile, or unsupported."""


class _Null:
    """Sentinel for the marshal NULL value (dict terminator)."""


_NULL = _Null()
_UNSET = object()


@dataclass
class CodeData:
    """A code object reduced to plain data. Never executable."""

    argcount: int
    posonlyargcount: int
    kwonlyargcount: int
    stacksize: int
    flags: int
    code: bytes
    consts: tuple
    names: tuple
    localsplusnames: tuple
    localspluskinds: bytes
    filename: str
    name: str
    qualname: str
    firstlineno: int
    linetable: bytes
    exceptiontable: bytes


class _Reader:
    """Cursor over a marshal byte stream, with limits enforced on read."""

    def __init__(self, data: bytes):
        self._data = data
        self.pos = 0
        self.refs: list = []
        self._objects = 0

    # -- low level ------------------------------------------------------
    def read(self, count: int) -> bytes:
        if count < 0 or self.pos + count > len(self._data):
            raise SafeMarshalError(
                f"truncated marshal stream at offset {self.pos} "
                f"(wanted {count} bytes, {len(self._data) - self.pos} left)"
            )
        chunk = self._data[self.pos : self.pos + count]
        self.pos += count
        return chunk

    def u8(self) -> int:
        return self.read(1)[0]

    def i32(self) -> int:
        return struct.unpack("<i", self.read(4))[0]

    def _count(self, raw: int, what: str) -> int:
        if raw < 0 or raw > MAX_CONTAINER_ITEMS:
            raise SafeMarshalError(f"implausible {what} count: {raw}")
        return raw

    def _sized_bytes(self, count: int) -> bytes:
        if count < 0 or count > MAX_STRING_BYTES:
            raise SafeMarshalError(f"implausible string/bytes size: {count}")
        return self.read(count)

    def _float_text(self, raw: bytes) -> float:
        # Marshal floats are stored as ASCII text. Garbage bytes are a
        # malformed stream: report them as SafeMarshalError, not as a
        # bare ValueError / UnicodeDecodeError leaking to callers.
        try:
            return float(raw.decode("ascii"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise SafeMarshalError(f"invalid marshal float text: {exc}") from exc

    def _decode_text(self, raw: bytes) -> str:
        try:
            return raw.decode("utf-8", "surrogatepass")
        except UnicodeDecodeError as exc:
            raise SafeMarshalError(f"invalid UTF-8 in marshal string: {exc}") from exc

    # -- object parsing ---------------------------------------------------
    def parse(self, depth: int = 0):
        """Parse one marshalled value at the cursor into plain data."""
        if depth > MAX_DEPTH:
            raise SafeMarshalError(f"marshal nesting deeper than {MAX_DEPTH}")
        self._objects += 1
        if self._objects > MAX_OBJECTS:
            raise SafeMarshalError(f"marshal object count over limit {MAX_OBJECTS}")
        start = self.pos
        type_byte = self.u8()
        flag_ref = bool(type_byte & 0x80)
        type_char = chr(type_byte & 0x7F)
        slot = None
        if flag_ref:
            slot = len(self.refs)
            self.refs.append(_UNSET)

        def done(value):
            if slot is not None:
                self.refs[slot] = value
            return value

        t = type_char
        if t == "0":
            return done(_NULL)
        if t == "N":
            return done(None)
        if t == "F":
            return done(False)
        if t == "T":
            return done(True)
        if t == "S":
            return done(StopIteration)
        if t == ".":
            return done(Ellipsis)
        if t == "i":
            return done(self.i32())
        if t == "I":
            return done(struct.unpack("<q", self.read(8))[0])
        if t == "f":
            size = self.u8()
            return done(self._float_text(self._sized_bytes(size)))
        if t == "g":
            return done(struct.unpack("<d", self.read(8))[0])
        if t == "x":
            size = self.u8()
            real = self._float_text(self._sized_bytes(size))
            size = self.u8()
            imag = self._float_text(self._sized_bytes(size))
            return done(complex(real, imag))
        if t == "y":
            real, imag = struct.unpack("<dd", self.read(16))
            return done(complex(real, imag))
        if t == "l":
            count = self.i32()
            negative = count < 0
            count = self._count(abs(count), "long digit")
            value = 0
            for i in range(count):
                digit = struct.unpack("<H", self.read(2))[0]
                value |= digit << (15 * i)
            return done(-value if negative else value)
        if t in ("s", "a", "A", "u", "t"):
            raw = self._sized_bytes(self.i32())
            if t == "s":
                return done(raw)
            return done(self._decode_text(raw))
        if t in ("z", "Z"):
            raw = self._sized_bytes(self.u8())
            return done(self._decode_text(raw))
        if t == "(":
            count = self._count(self.i32(), "tuple")
            return done(tuple(self.parse(depth + 1) for _ in range(count)))
        if t == ")":
            count = self._count(self.u8(), "small tuple")
            return done(tuple(self.parse(depth + 1) for _ in range(count)))
        if t == "[":
            count = self._count(self.i32(), "list")
            return done([self.parse(depth + 1) for _ in range(count)])
        if t == "<":
            count = self._count(self.i32(), "set")
            return done(self._read_set(count, depth))
        if t == ">":
            count = self._count(self.i32(), "frozenset")
            items = [self.parse(depth + 1) for _ in range(count)]
            try:
                return done(frozenset(items))
            except TypeError as exc:
                # Hostile stream: an unhashable item (list, dict, ...)
                # in a frozenset is malformed, not a crash.
                raise SafeMarshalError(
                    f"unhashable item in marshal frozenset: {exc}"
                ) from exc
        if t == "{":
            result = {}
            while True:
                key = self.parse(depth + 1)
                if key is _NULL:
                    break
                value = self.parse(depth + 1)
                try:
                    result[key] = value
                except TypeError:
                    # Unhashable key in a hostile stream: keep the parse
                    # going without storing it.
                    pass
            return done(result)
        if t == "r":
            index = self.i32()
            if index < 0 or index >= len(self.refs):
                raise SafeMarshalError(f"marshal ref index out of range: {index}")
            target = self.refs[index]
            if target is _UNSET:
                raise SafeMarshalError(f"marshal ref to unfinished object: {index}")
            return target
        if t == "c":
            return done(self._parse_code(depth))
        raise SafeMarshalError(f"unsupported marshal type {t!r} at offset {start}")

    def _read_set(self, count: int, depth: int):
        try:
            return set(self.parse(depth + 1) for _ in range(count))
        except TypeError as exc:
            # Hostile stream: an unhashable item in a set is malformed.
            raise SafeMarshalError(f"unhashable item in marshal set: {exc}") from exc

    def _parse_code(self, depth: int) -> CodeData:
        # Code object fields after the type byte, CPython 3.11+ layout:
        # five raw int32 counters, then marshalled objects, a raw int32
        # first line number, then two more marshalled objects.
        values = {}
        values["argcount"] = self.i32()
        values["posonlyargcount"] = self.i32()
        values["kwonlyargcount"] = self.i32()
        values["stacksize"] = self.i32()
        values["flags"] = self.i32()
        for key in (
            "code",
            "consts",
            "names",
            "localsplusnames",
            "localspluskinds",
            "filename",
            "name",
            "qualname",
        ):
            values[key] = self.parse(depth + 1)
        values["firstlineno"] = self.i32()
        values["linetable"] = self.parse(depth + 1)
        values["exceptiontable"] = self.parse(depth + 1)
        for key in ("code", "localspluskinds", "linetable", "exceptiontable"):
            if not isinstance(values[key], (bytes, bytearray)):
                raise SafeMarshalError(f"code field {key} is not bytes")
            values[key] = bytes(values[key])
        for key in ("consts", "names", "localsplusnames"):
            if not isinstance(values[key], tuple):
                raise SafeMarshalError(f"code field {key} is not a tuple")
        for key in ("filename", "name", "qualname"):
            if not isinstance(values[key], str):
                raise SafeMarshalError(f"code field {key} is not a string")
        # The counters are raw int32s in the stream, so a hostile
        # stream can carry negative or inconsistent values that
        # reconstruction would silently mis-slice. Real code objects
        # never have them: refuse instead of reconstructing nonsense.
        for key in ("argcount", "posonlyargcount", "kwonlyargcount",
                    "stacksize", "flags"):
            if values[key] < 0:
                raise SafeMarshalError(f"code field {key} is negative: {values[key]}")
        if values["posonlyargcount"] > values["argcount"]:
            raise SafeMarshalError("code posonlyargcount exceeds argcount")
        # names / localsplusnames are identifier strings in every real
        # code object. Anything else (an int, a list) crashes the
        # reconstructor's joins and membership tests downstream, so it
        # is refused here, at the parser boundary.
        for key in ("names", "localsplusnames"):
            if not all(isinstance(item, str) for item in values[key]):
                raise SafeMarshalError(f"code field {key} contains a non-string name")
        return CodeData(**values)


def parse_marshal(data: bytes) -> object:
    """Parse one complete marshal stream into plain data.

    The stream must be consumed exactly; trailing bytes are an error.
    Returns plain containers plus CodeData records. No real code object
    is ever constructed.
    """
    if not data:
        raise SafeMarshalError("empty marshal stream")
    reader = _Reader(data)
    value = reader.parse()
    if reader.pos != len(data):
        raise SafeMarshalError(
            f"trailing bytes after marshal stream: {len(data) - reader.pos}"
        )
    return value
