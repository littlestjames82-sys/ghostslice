"""Shared source-text decoding (v0.21, G16).

Every surface that turns file bytes into text — scanner, slicers,
exporter, graph, lint, watch, the dashboard preview — goes through
this one helper, so a file means the same text everywhere. Before
v0.21 each call site did its own `read_text(encoding="utf-8",
errors="replace")`: a UTF-16 file tokenized as NUL-strewn garbage
(or was skipped as "binary"), a UTF-8 BOM cost a phantom token and
broke `ast.parse`, and Latin-1 bytes were mangled into U+FFFD.

Decode rules, in order:

  1. A byte-order mark wins: UTF-32 LE/BE, UTF-16 LE/BE and UTF-8
     BOMs are sniffed (UTF-32 before UTF-16 — its LE BOM starts
     with the UTF-16 LE BOM) and decoded with the matching codec,
     which strips the BOM. A BOM'd file that still fails to decode
     cleanly falls back to replacement characters under the same
     label: a BOM is a statement of intent, honoured best-effort.
  2. Otherwise strict UTF-8. Clean input keeps the label "utf-8"
     (UTF-8 with a BOM reports "utf-8-sig").
  3. Bytes that are not valid UTF-8 decode as Latin-1, which maps
     every byte to a codepoint: lossless for the Western-European
     files this fallback exists for, and labelled "latin-1" so the
     manifest can say so. Nothing is silently dropped either way.

`encoding` labels are the short names recorded on scanner entries
and in bundle manifests (`source_encoding`, present only when the
label is not "utf-8"): they name the SOURCE encoding. Bundle files
always carry the decoded text written as UTF-8 — the bundle is a
normalized view, never a byte copy.

Line endings are NOT normalized here: slicers split with
str.splitlines() semantics, which treats LF, CRLF and CR-only
endings alike (v0.21 verified this per slicer; the scanner's line
count uses splitlines too).
"""
from __future__ import annotations

from pathlib import Path

# The module's public surface, declared so consumers (and the
# call-graph analyzer, which roots __all__ names) can see what is
# API: read_text / read_text_with_encoding are the two read
# conveniences, decode_bytes / sniff_bom the byte-level core.
__all__ = [
    "sniff_bom", "decode_bytes", "read_text", "read_text_with_encoding",
    "UTF16_32_LABELS",
]

# (bom, codec, label) — longest BOMs first: FF FE 00 00 (UTF-32 LE)
# must win over FF FE (UTF-16 LE).
_BOMS: tuple[tuple[bytes, str, str], ...] = (
    (b"\xff\xfe\x00\x00", "utf-32", "utf-32-le"),
    (b"\x00\x00\xfe\xff", "utf-32", "utf-32-be"),
    (b"\xef\xbb\xbf", "utf-8-sig", "utf-8-sig"),
    (b"\xff\xfe", "utf-16", "utf-16-le"),
    (b"\xfe\xff", "utf-16", "utf-16-be"),
)

UTF16_32_LABELS = frozenset(
    label for _bom, _codec, label in _BOMS if label.startswith(("utf-16", "utf-32")))


def sniff_bom(data: bytes) -> tuple[str, str] | None:
    """(codec, label) when `data` starts with a known BOM, else None."""
    for bom, codec, label in _BOMS:
        if data.startswith(bom):
            return codec, label
    return None


def decode_bytes(data: bytes) -> tuple[str, str]:
    """Decode raw file bytes to (text, encoding label). Never raises."""
    sniffed = sniff_bom(data)
    if sniffed is not None:
        codec, label = sniffed
        try:
            return data.decode(codec), label
        except (UnicodeDecodeError, ValueError):
            return data.decode(codec, errors="replace"), label
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return data.decode("latin-1"), "latin-1"


def read_text(path: str | Path) -> str:
    """Decoded text of a file (see decode_bytes). Raises OSError on
    unreadable files, exactly like Path.read_text did."""
    return decode_bytes(Path(path).read_bytes())[0]


def read_text_with_encoding(path: str | Path) -> tuple[str, str]:
    """(decoded text, encoding label) of a file."""
    return decode_bytes(Path(path).read_bytes())
