"""Parsing of CPython .pyc files: header + safe marshal payload.

A .pyc file is a 16-byte header (magic, bit field, then either a source
timestamp + size or a source hash) followed by one marshal stream for
the module code object. GhostLift reads the header as data and hands
the payload to the safe byte parser in marshal_safe. The artifact is
never imported and never executed.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .marshal_safe import CodeData, parse_marshal

MAX_PYC_BYTES = 64 * 1024 * 1024

# Magic numbers (first uint16 of the file) for the CPython versions
# whose code-object marshal layouts GhostLift has a tested parser for.
SUPPORTED_MAGICS = {
    3495: "3.11",
    3531: "3.12",
    3571: "3.13",
}


class PycError(ValueError):
    """Raised when a .pyc artifact cannot be lifted honestly."""


@dataclass
class PycInfo:
    """A parsed ``.pyc``: header facts plus the module code object as data."""

    magic: int
    python_version: str | None
    hash_based: bool
    source_size: int | None
    source_mtime: int | None
    module: CodeData


def parse_pyc(data: bytes) -> PycInfo:
    """Parse ``.pyc`` bytes (16-byte header + marshal payload) as data.

    The payload goes to the safe parser in :mod:`.marshal_safe`; it
    is never unmarshalled into a real code object, imported, or
    executed.

    Raises:
        PycError: the file is oversized, truncated, not a CPython
            ``.pyc``, has an unsupported magic (only the layouts in
            ``SUPPORTED_MAGICS`` are read), or its payload is not a
            module code object.
    """
    if len(data) > MAX_PYC_BYTES:
        raise PycError(f".pyc larger than limit ({MAX_PYC_BYTES} bytes)")
    if len(data) < 16:
        raise PycError(".pyc too short for the 16-byte header")
    magic = struct.unpack("<H", data[0:2])[0]
    if data[2:4] != b"\r\n":
        raise PycError("bad .pyc magic trailer (not a CPython bytecode file)")
    version = SUPPORTED_MAGICS.get(magic)
    if version is None:
        raise PycError(
            f"unsupported .pyc magic {magic}: GhostLift's tested layouts are "
            + ", ".join(f"{m} ({v})" for m, v in sorted(SUPPORTED_MAGICS.items()))
        )
    bit_field = struct.unpack("<I", data[4:8])[0]
    hash_based = bool(bit_field & 0x01)
    mtime = size = None
    if not hash_based:
        mtime, size = struct.unpack("<II", data[8:16])
    payload = data[16:]
    value = parse_marshal(payload)
    if not isinstance(value, CodeData):
        raise PycError(".pyc payload is not a module code object")
    if value.name != "<module>":
        raise PycError(f".pyc payload code object is named {value.name!r}, not <module>")
    return PycInfo(
        magic=magic,
        python_version=version,
        hash_based=hash_based,
        source_size=size,
        source_mtime=mtime,
        module=value,
    )


def child_code_objects(code: CodeData) -> list[CodeData]:
    """Direct child code objects of a code object, in const order."""
    return [c for c in code.consts if isinstance(c, CodeData)]


def top_level_symbols(module: CodeData) -> list[str]:
    """Names of top-level functions and classes, in definition order."""
    names = []
    for child in child_code_objects(module):
        if child.name.startswith("<"):
            continue
        names.append(child.qualname)
    return names


def is_class(code: CodeData) -> bool:
    """A class body code object touches __name__/__module__/__qualname__."""
    needed = {"__name__", "__module__", "__qualname__"}
    return needed.issubset(set(code.names))
