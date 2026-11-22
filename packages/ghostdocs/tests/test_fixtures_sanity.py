"""Fixture sanity checks. These need no GhostDocs core: they prove the
fixtures themselves have the properties the behavioural tests rely on,
so a later behavioural failure cannot be blamed on a broken fixture."""
import hashlib
import re
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _lines(p):
    return [ln for ln in Path(p).read_text().splitlines() if ln.strip()]


def _date_in(text):
    m = re.search(r"(20\d\d-\d\d-\d\d)", text)
    return m.group(1) if m else None


def test_exact_duplicate_is_byte_identical():
    d = FIXTURES / "dedupe_corpus"
    assert _sha(d / "returns-policy-v1.md") == _sha(d / "returns-policy-copy.md")


def test_near_duplicate_is_newer_and_mostly_the_same_lines():
    d = FIXTURES / "dedupe_corpus"
    v1 = (d / "returns-policy-v1.md").read_text()
    v2 = (d / "returns-policy-v2.md").read_text()
    assert v1 != v2
    assert _date_in(v2) > _date_in(v1), "v2 must carry the newer date"
    s1, s2 = set(_lines(d / "returns-policy-v1.md")), set(_lines(d / "returns-policy-v2.md"))
    jaccard = len(s1 & s2) / len(s1 | s2)
    # Plan reuses GhostSlice line-shingle Jaccard (>= 0.85 there); the
    # fixture keeps plain line Jaccard comfortably in near-duplicate range.
    assert jaccard >= 0.80, f"line Jaccard only {jaccard:.2f}"
    assert "45 days" in v2 and "30 days" in v1


def test_text_layer_pdf_really_has_text():
    raw = (FIXTURES / "pdf_corpus" / "store-manual-text.pdf").read_bytes()
    assert raw.startswith(b"%PDF")
    assert b" Tj" in raw, "text-showing operator missing"
    assert b"Count the till" in raw, "expected extractable sentence missing"


def test_image_only_pdf_has_no_text_layer():
    raw = (FIXTURES / "pdf_corpus" / "scanned-flyer.pdf").read_bytes()
    assert raw.startswith(b"%PDF")
    assert b"/Image" in raw
    assert b"Tj" not in raw and b"TJ" not in raw, "image PDF must show no text"


def test_personal_fixture_has_planted_fake_personal_data():
    text = (FIXTURES / "personal_corpus" / "customer-note-example.md").read_text()
    assert "123-45-6789" in text  # standard fake SSN shape, not a real one
    assert "4111 1111 1111 1111" in text  # standard test card number
    clean = (FIXTURES / "personal_corpus" / "delivery-info.md").read_text()
    assert "123-45-6789" not in clean and "4111" not in clean


def test_examples_corpus_present():
    ex = FIXTURES.parents[1] / "examples" / "sample-help-centre"
    names = {p.name for p in ex.glob("*.md")}
    assert {"returns-policy.md", "opening-hours.md", "warranty.md"} <= names
