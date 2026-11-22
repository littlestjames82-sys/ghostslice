#!/usr/bin/env python3
"""Regenerate the PDF fixtures for the GhostDocs tests.

Pure standard library. Writes two minimal, valid PDFs next to this file
under ``pdf_corpus/``:

- ``store-manual-text.pdf`` - a PDF WITH a real text layer (Helvetica,
  Tj text-showing operators). A correct scanner must extract its text and
  must NOT put it on the not-covered list.
- ``scanned-flyer.pdf`` - an image-only PDF (a single image XObject, no
  text-showing operators anywhere). It stands in for a scanned page: with
  no OCR in v0.1 there is no readable text, so it MUST land on the
  not-covered list and must appear in no export bundle.

Run:  python3 generate_pdfs.py
The output bytes are deterministic (no timestamps), so re-running leaves
the fixtures unchanged unless this script changes.
"""
from pathlib import Path

OUT = Path(__file__).resolve().parent / "pdf_corpus"


def build_pdf(objects):
    """objects: list of (obj_number, bytes). Returns a complete PDF."""
    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for num, body in objects:
        offsets[num] = len(out)
        out += f"{num} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_pos = len(out)
    max_obj = max(n for n, _ in objects)
    out += f"xref\n0 {max_obj + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for i in range(1, max_obj + 1):
        out += f"{offsets[i]:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {max_obj + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n"
    ).encode()
    return bytes(out)


def text_pdf():
    lines = [
        "Store Manual",
        "Updated 2026-01-05",
        "Keep the front door unlocked during opening hours.",
        "Count the till at close and record the total.",
        "Report any fault with the shutter to the manager.",
    ]
    parts = [b"BT", b"/F1 14 Tf", b"72 720 Td"]
    for i, line in enumerate(lines):
        if i:
            parts.append(b"0 -22 Td")
        safe = line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        parts.append(f"({safe}) Tj".encode())
    parts.append(b"ET")
    stream = b"\n".join(parts)
    objects = [
        (1, b"<< /Type /Catalog /Pages 2 0 R >>"),
        (2, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"),
        (3, b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"),
        (4, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"),
        (5, b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n"
            + stream + b"\nendstream"),
    ]
    return build_pdf(objects)


def image_only_pdf():
    # A tiny 2x2 RGB "photo" image, no text operators anywhere.
    pixels = bytes([200, 60, 60, 60, 200, 60, 60, 60, 200, 20, 20, 20])
    objects = [
        (1, b"<< /Type /Catalog /Pages 2 0 R >>"),
        (2, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"),
        (3, b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /XObject << /Im1 4 0 R >> >> /Contents 5 0 R >>"),
        (4, b"<< /Type /XObject /Subtype /Image /Width 2 /Height 2 "
            b"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Length "
            + str(len(pixels)).encode() + b" >>\nstream\n" + pixels
            + b"\nendstream"),
        (5, b"<< /Length 35 >>\nstream\nq 400 0 0 400 100 200 cm /Im1 Do Q\nendstream"),
    ]
    return build_pdf(objects)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "store-manual-text.pdf").write_bytes(text_pdf())
    (OUT / "scanned-flyer.pdf").write_bytes(image_only_pdf())
    print("wrote", OUT / "store-manual-text.pdf")
    print("wrote", OUT / "scanned-flyer.pdf")


if __name__ == "__main__":
    main()
