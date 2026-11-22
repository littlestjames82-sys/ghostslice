"""PLAN verification bar 2 - coverage honesty.

Fixture corpus (tests/fixtures/pdf_corpus):
  store-manual-text.pdf  PDF WITH a real text layer
  scanned-flyer.pdf      image-only PDF, no text layer (stands in for a
                         scanned page; v0.1 has no OCR)
  warranty.md            plain Markdown control document

Required behaviour: the image-only PDF is named on the not-covered list
in scan, in report, and in any export attempt, and it appears in NO
bundle. The text-layer PDF must be read, not listed as not covered.
"""
import json

from conftest import (bundle_text, context_window, copy_corpus,
                      export_corpus, out_text, report_corpus, scan_corpus)

NOT_COVERED_TOKENS = ("not covered", "not-covered", "not_covered",
                      "no text", "no readable text", "unreadable",
                      "unsupported", "image-only", "image only",
                      "skipped", "cannot read", "could not read")


def _named_not_covered(text, filename):
    window = context_window(text, filename, width=700)
    return bool(window) and any(tok in window for tok in NOT_COVERED_TOKENS)


def test_scan_extracts_text_pdf_and_lists_image_pdf_not_covered(tmp_path):
    corpus = copy_corpus(tmp_path, "pdf_corpus")
    proc = scan_corpus(corpus)
    assert proc.returncode == 0, out_text(proc)
    # Structured first: when scan emits JSON, read the not_covered list
    # itself instead of guessing from neighbouring text.
    try:
        data = json.loads(proc.stdout)
    except Exception:
        data = None
    if isinstance(data, dict) and "not_covered" in data:
        not_cov = [n.get("path", "") for n in data["not_covered"]]
        covered = [d.get("path", "") for d in data.get("documents", [])]
        assert "scanned-flyer.pdf" in not_cov, not_cov
        assert "store-manual-text.pdf" in covered, covered
        assert "store-manual-text.pdf" not in not_cov
        return
    text = out_text(proc)
    assert _named_not_covered(text, "scanned-flyer.pdf"), \
        "image-only PDF was not named as not covered in scan output"
    assert not _named_not_covered(text, "store-manual-text.pdf"), \
        "text-layer PDF was wrongly listed as not covered"


def test_image_pdf_is_in_no_export_bundle(tmp_path):
    corpus = copy_corpus(tmp_path, "pdf_corpus")
    out = tmp_path / "export"
    proc = export_corpus(corpus, out)
    assert proc.returncode == 0, out_text(proc)
    text, names = bundle_text(out)
    copied = [n for n in names if "scanned-flyer" in n
              and not n.endswith((".json", ".md"))]
    assert copied == [], f"image-only PDF was copied into the bundle: {copied}"
    # Its not-covered status is still recorded in the export paperwork.
    combined = text + "\n" + out_text(proc)
    assert _named_not_covered(combined, "scanned-flyer.pdf"), \
        "export did not record the image PDF as not covered"
    # And the readable documents did make it in.
    assert "Warranty Notes" in text or "Count the till" in text


def test_report_lists_image_pdf_as_not_covered(tmp_path):
    corpus = copy_corpus(tmp_path, "pdf_corpus")
    _, report_text = report_corpus(corpus, tmp_path / "report.html")
    assert report_text.strip(), "report produced no output"
    assert _named_not_covered(report_text, "scanned-flyer.pdf"), \
        "report did not list the image-only PDF as not covered"
