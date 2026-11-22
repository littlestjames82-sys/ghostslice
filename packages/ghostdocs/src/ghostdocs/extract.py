"""Text extraction for MD / TXT / HTML / PDF (text layer only).

Stdlib only. Honesty rules from PLAN.md:
- DOCX (and other office formats) are NOT covered, never silently skipped.
- Image-only / no-text PDFs are NOT covered and land on the not-covered list.
- Every PDF carries extraction-quality data (pages, chars, chars/page, flags)
  so a low-yield extraction looks low-yield instead of pretending it worked.
"""
from __future__ import annotations

import re
import zlib
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

COVERED_EXTS = {".md", ".markdown", ".txt", ".text", ".html", ".htm", ".pdf"}
NOT_COVERED_EXTS = {
    ".docx": "DOCX not covered in v0.1 (no stdlib DOCX text extraction adopted)",
    ".doc": "legacy Word .doc not covered in v0.1",
    ".odt": "ODT not covered in v0.1",
    ".xlsx": "spreadsheets not covered in v0.1",
    ".xls": "spreadsheets not covered in v0.1",
    ".pptx": "slides not covered in v0.1",
    ".ppt": "slides not covered in v0.1",
    ".rtf": "RTF not covered in v0.1",
}

LOW_YIELD_CHARS_PER_PAGE = 50


@dataclass
class Extraction:
    """The result of trying to extract text from one file.

    When ``covered`` is False, ``reason`` says why, and the file is
    named on the not-covered list rather than silently skipped. The
    quality fields (``pages``, ``chars``, ``chars_per_page``, and
    ``flags`` such as ``low-yield``) are populated for PDFs so a poor
    extraction is labelled as poor instead of looking successful.
    """

    text: str = ""
    fmt: str = ""
    covered: bool = False
    reason: str = ""              # why not covered, when covered is False
    pages: int | None = None      # PDFs only
    chars: int = 0
    chars_per_page: float | None = None
    flags: list[str] = field(default_factory=list)


class _HTMLText(HTMLParser):
    """Extract text + heading levels, dropping script/style content.

    Heading text is buffered while inside an h1-h6 element and emitted
    as one Markdown heading line (``## Title``) when the element closes,
    so split_sections() sees the same heading structure a Markdown
    document has. Emitting the ``#`` markers at the end tag (the old
    behaviour) put them on their own line after the title, which never
    matched a heading line and collapsed every HTML document into a
    single section.
    """

    _HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0
        self.headings: list[tuple[int, str]] = []
        self._heading_level: int | None = None
        self._heading_parts: list[str] = []

    def _flush_heading(self) -> None:
        if self._heading_level is None:
            return
        text = " ".join("".join(self._heading_parts).split())
        if text:
            self.parts.append(f"\n{'#' * self._heading_level} {text}\n")
            self.headings.append((self._heading_level, text))
        self._heading_level = None
        self._heading_parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "head", "title"):
            # head/title are document metadata, not body text: letting
            # the <title> through puts stray text before the first
            # heading, which split_sections() turns into a fake section
            self._skip += 1
            return
        if tag in self._HEADING_TAGS:
            # an unclosed previous heading (malformed HTML) ends here
            self._flush_heading()
            self._heading_level = int(tag[1])
            self._heading_parts = []
            return
        if self._heading_level is not None:
            if tag not in ("p", "div", "li", "tr", "ul", "ol", "table",
                           "section", "article", "blockquote", "pre", "br"):
                return  # inline markup inside a heading adds no breaks
            # a block element cannot live inside a heading: it implicitly
            # closes an unclosed heading (browser behaviour), so body text
            # after a malformed heading is not swallowed into the title
            self._flush_heading()
        if tag in ("p", "li", "tr", "br", "div"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "head", "title") and self._skip:
            self._skip -= 1
            return
        if tag in self._HEADING_TAGS and self._heading_level is not None:
            self._flush_heading()

    def handle_data(self, data):
        if self._skip:
            return
        if self._heading_level is not None:
            self._heading_parts.append(data)
        else:
            self.parts.append(data)

    def close(self):
        self._flush_heading()  # heading left open at end of document
        super().close()


def _decode_text_bytes(raw: bytes) -> tuple[str, bool]:
    # UTF-16 only when it carries a BOM: without one, arbitrary even-length
    # latin-1 bytes "successfully" decode as UTF-16 and come out garbled
    # with no lossy flag, so the latin-1 fallback was unreachable.
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return raw.decode("utf-16"), False
        except (UnicodeDecodeError, UnicodeError):
            pass
    try:
        # utf-8-sig also strips a UTF-8 BOM, which otherwise breaks the
        # first heading of a Markdown file.
        return raw.decode("utf-8-sig"), False
    except (UnicodeDecodeError, UnicodeError):
        pass
    return raw.decode("latin-1"), True


def extract_html(raw: bytes) -> Extraction:
    """Extract visible text from HTML bytes, dropping script/style content."""
    text, lossy = _decode_text_bytes(raw)
    parser = _HTMLText()
    try:
        parser.feed(text)
        parser.close()
    except Exception:
        pass
    out = "".join(parser.parts)
    out = re.sub(r"[ \t]+", " ", out)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    flags = ["lossy-decode"] if lossy else []
    return Extraction(text=out, fmt="html", covered=bool(out), chars=len(out),
                      reason="" if out else "HTML contained no extractable text",
                      flags=flags)


# ---------------- PDF (text layer only) ----------------

def _pdf_streams(data: bytes):
    """Yield decompressed (or raw) stream payloads."""
    pos = 0
    while True:
        start = data.find(b"stream", pos)
        if start == -1:
            return
        start += len(b"stream")
        if data[start:start + 2] == b"\r\n":
            start += 2
        elif data[start:start + 1] in (b"\n", b"\r"):
            start += 1
        end = data.find(b"endstream", start)
        if end == -1:
            return
        payload = data[start:end]
        # strip only the single EOL that precedes "endstream": rstrip would
        # also eat payload bytes that happen to be \r or \n (for a flate
        # stream those can be real compressed / checksum bytes)
        if payload.endswith(b"\r\n"):
            payload = payload[:-2]
        elif payload.endswith((b"\n", b"\r")):
            payload = payload[:-1]
        header = data[max(0, start - 400):start]
        if b"FlateDecode" in header:
            try:
                payload = zlib.decompress(payload)
            except zlib.error:
                try:
                    payload = zlib.decompressobj().decompress(payload)
                except zlib.error:
                    payload = b""
        yield payload
        pos = end + len(b"endstream")


def _decode_pdf_string(raw: bytes) -> str:
    """PDF strings are PDFDocEncoding/latin-1, or UTF-16BE with a BOM."""
    if raw.startswith(b"\xfe\xff"):
        return raw[2:].decode("utf-16-be", errors="replace")
    return raw.decode("latin-1")


def _pdf_literal_strings(content: bytes) -> list[str]:
    """Pull ( ... ) and < ... > Tj / TJ string operands from a content stream.

    Many real PDFs show text with hex strings, not literal strings; ignoring
    them made text-layer PDFs look like they had no text layer at all.
    """
    out: list[str] = []
    i, n = 0, len(content)
    while i < n:
        if content[i:i + 1] == b"<":
            if content[i + 1:i + 2] == b"<":  # dictionary open, not a string
                i += 2
                continue
            end = content.find(b">", i + 1)
            if end == -1:
                break
            hextext = re.sub(rb"\s+", b"", content[i + 1:end])
            if hextext and all(c in b"0123456789abcdefABCDEF" for c in hextext):
                if len(hextext) % 2:
                    hextext += b"0"
                out.append(_decode_pdf_string(bytes.fromhex(hextext.decode("ascii"))))
            i = end + 1
            continue
        if content[i:i + 1] == b"(":
            depth, j, buf = 1, i + 1, bytearray()
            while j < n and depth:
                c = content[j]
                if c == 0x5C and j + 1 < n:  # backslash escape
                    nxt = content[j + 1]
                    mapping = {ord("n"): "\n", ord("r"): "\r", ord("t"): "\t",
                               ord("("): "(", ord(")"): ")", ord("\\"): "\\"}
                    if nxt in mapping:
                        buf.extend(mapping[nxt].encode("latin-1")); j += 2; continue
                    if 48 <= nxt <= 55:  # octal, up to 3 digits
                        k = j + 1; oct_digits = b""
                        while k < n and len(oct_digits) < 3 and 48 <= content[k] <= 55:
                            oct_digits += bytes([content[k]]); k += 1
                        buf.append(int(oct_digits, 8) & 0xFF); j = k; continue
                    buf.append(nxt); j += 2; continue
                if c == ord("("):
                    depth += 1
                elif c == ord(")"):
                    depth -= 1
                    if depth == 0:
                        j += 1; break
                buf.append(c); j += 1
            out.append(_decode_pdf_string(bytes(buf)))
            i = j
        else:
            i += 1
    return out


def extract_pdf(raw: bytes) -> Extraction:
    """Extract a PDF's text layer from raw bytes (no OCR).

    A PDF with no text layer, or a near-empty one, comes back as not
    covered with an explicit reason and quality flags; see
    :class:`Extraction`.
    """
    pages = len(re.findall(rb"/Type\s*/Page(?![s\w])", raw))
    if pages == 0:
        counts = re.findall(rb"/Count\s+(\d+)", raw)
        if counts:
            pages = int(counts[0])
    lines: list[str] = []
    for payload in _pdf_streams(raw):
        if b"Tj" not in payload and b"TJ" not in payload and b"BT" not in payload:
            continue
        strings = _pdf_literal_strings(payload)
        if strings:
            lines.append(" ".join(s.strip() for s in strings if s.strip()))
    text = "\n".join(lines).strip()
    chars = len(text)
    cpp = (chars / pages) if pages else None
    flags: list[str] = []
    if cpp is not None and cpp < LOW_YIELD_CHARS_PER_PAGE:
        flags.append("low-yield")
    if pages == 0:
        flags.append("page-count-unknown")
    if not text:
        return Extraction(text="", fmt="pdf", covered=False, pages=pages,
                          chars=0, chars_per_page=cpp, flags=flags + ["no-text-layer"],
                          reason="PDF has no extractable text layer (image-only or scanned PDFs are not covered in v0.1, no OCR)")
    if cpp is not None and cpp < 5:
        return Extraction(text=text, fmt="pdf", covered=False, pages=pages,
                          chars=chars, chars_per_page=cpp, flags=flags + ["near-empty-text-layer"],
                          reason="PDF text layer is near-empty; treated as not covered rather than pretending extraction worked")
    return Extraction(text=text, fmt="pdf", covered=True, pages=pages,
                      chars=chars, chars_per_page=cpp, flags=flags)


def extract_file(path: Path) -> Extraction:
    """Extract text from *path*, dispatching on its file extension.

    Extensions listed in ``NOT_COVERED_EXTS`` (and any unrecognised
    extension) return a not-covered result with a reason; they are
    never treated as empty documents.
    """
    ext = path.suffix.lower()
    if ext in NOT_COVERED_EXTS:
        return Extraction(fmt=ext.lstrip("."), covered=False, reason=NOT_COVERED_EXTS[ext])
    raw = path.read_bytes()
    if ext == ".pdf":
        return extract_pdf(raw)
    if ext in (".html", ".htm"):
        return extract_html(raw)
    if ext in (".md", ".markdown", ".txt", ".text"):
        text, lossy = _decode_text_bytes(raw)
        fmt = "markdown" if ext in (".md", ".markdown") else "text"
        flags = ["lossy-decode"] if lossy else []
        text = text.strip()
        return Extraction(text=text, fmt=fmt, covered=True, chars=len(text),
                          flags=flags, reason="")
    return Extraction(fmt=ext.lstrip("."), covered=False,
                      reason=f"format {ext} not covered in v0.1")
