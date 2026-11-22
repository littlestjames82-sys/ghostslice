"""PLAN verification bar 1 - dedupe.

Fixture corpus (tests/fixtures/dedupe_corpus):
  returns-policy-v1.md    Updated 2024-01-15
  returns-policy-copy.md  exact byte duplicate of v1
  returns-policy-v2.md    near-duplicate edit, Updated 2026-03-01, 45 days
  opening-hours.md        unrelated control document

Required behaviour: v1 + copy + v2 cluster together, v2 is marked the
probable current one (a labelled heuristic), and a deduped export
contains the current version's text once - the old 30-day text must not
appear anywhere in the export - while the control document survives.
"""
from conftest import (bundle_text, copy_corpus, export_corpus, load_manifest,
                      scan_corpus, out_text)


def test_scan_clusters_duplicates_and_marks_probable_current(tmp_path):
    corpus = copy_corpus(tmp_path, "dedupe_corpus")
    proc = scan_corpus(corpus)
    assert proc.returncode == 0, out_text(proc)
    text = out_text(proc).lower()
    for name in ("returns-policy-v1.md", "returns-policy-copy.md",
                 "returns-policy-v2.md"):
        assert name in text, f"{name} not mentioned in scan output"
    assert any(tok in text for tok in (
        "duplicate", "cluster", "near-duplicate", "near duplicate")), \
        "scan output never describes the duplicate cluster"
    window = text
    idx = text.find("returns-policy-v2.md")
    near = text[max(0, idx - 800): idx + 800]
    assert any(tok in near for tok in (
        "probable current", "probable-current", "current", "newest",
        "kept", "canonical")), \
        "v2 is nowhere identified as the probable current version"


def test_deduped_export_contains_current_version_once(tmp_path):
    corpus = copy_corpus(tmp_path, "dedupe_corpus")
    out = tmp_path / "export"
    proc = export_corpus(corpus, out)
    assert proc.returncode == 0, out_text(proc)
    text, names = bundle_text(out)
    assert text, "export produced no readable content"

    # The superseded wording must be gone entirely.
    assert "30 days from the purchase date" not in text, \
        "old policy text leaked into the deduped export"
    # The current wording is present.
    assert "45 days from the purchase date" in text

    # Only the current returns file may be present as an exported file.
    returns_files = [n for n in names if "returns-policy" in n
                     and not n.endswith(("manifest.json", "PROMPT.md"))]
    if returns_files:
        assert returns_files == [n for n in returns_files
                                 if "returns-policy-v2" in n], returns_files

    # The manifest lists the returns policy once, as v2, in its files
    # list. Superseded members may (and should) be RECORDED as skipped,
    # that is bookkeeping, not inclusion.
    manifest = load_manifest(out)
    if manifest is not None:
        exported = [f.get("path", "") for f in manifest.get("files", [])]
        returns_exported = [p for p in exported if "returns-policy" in p]
        assert returns_exported == ["returns-policy-v2.md"], exported
        skipped = manifest.get("superseded_skipped", [])
        if skipped:
            assert "returns-policy-v1.md" in skipped
            assert "returns-policy-copy.md" in skipped

    # Control document is untouched by dedupe.
    assert "Opening Hours" in text or "opening-hours" in " ".join(names)
