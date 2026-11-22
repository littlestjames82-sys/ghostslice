"""PLAN verification bar 3 - personal-data hold-out.

Fixture corpus (tests/fixtures/personal_corpus):
  customer-note-example.md  planted FAKE personal data (test SSN shape
                            123-45-6789, test card 4111..., .invalid
                            email, 555 phone). Never a real person's data.
  delivery-info.md          clean control document

Required behaviour: the flagged page is held out of a default export,
and wherever it is named (scan / report) it is named with path + type
only - the raw personal values must never be printed by the tool.
"""
from conftest import (bundle_text, copy_corpus, export_corpus, out_text,
                      report_corpus, scan_corpus)

RAW_VALUES = ("123-45-6789", "4111 1111 1111 1111",
              "jane.example@example.invalid", "555-010-1234")
TYPE_TOKENS = ("ssn", "social security", "personal", "card",
               "payment", "email", "phone", "sensitive", "pii")


def test_flagged_page_held_out_of_default_export(tmp_path):
    corpus = copy_corpus(tmp_path, "personal_corpus")
    out = tmp_path / "export"
    proc = export_corpus(corpus, out)
    assert proc.returncode == 0, out_text(proc)
    text, _ = bundle_text(out)
    assert text, "export produced no readable content"
    for raw in RAW_VALUES:
        assert raw not in text, f"personal value leaked into export: {raw}"
    assert "Jane Example" not in text
    # The clean control document still goes out.
    assert "Delivery Information" in text


def test_scan_and_report_name_the_holdout_by_path_and_type_only(tmp_path):
    corpus = copy_corpus(tmp_path, "personal_corpus")
    surfaces = []
    proc = scan_corpus(corpus)
    assert proc.returncode == 0, out_text(proc)
    surfaces.append(out_text(proc))
    _, report_text = report_corpus(corpus, tmp_path / "report.html")
    surfaces.append(report_text)
    combined = "\n".join(surfaces)
    low = combined.lower()
    assert "customer-note-example.md" in low, \
        "held-out page was never named in scan or report output"
    assert any(tok in low for tok in TYPE_TOKENS), \
        "hold-out was named without any finding type"
    for raw in RAW_VALUES:
        assert raw not in combined, \
            f"tool printed a raw personal value in scan/report: {raw}"
