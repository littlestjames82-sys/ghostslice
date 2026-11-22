"""Hardening regression tests (improvement pass, 2026-10-18).

Each test pins a real bug found by probing the original code: silent
garbling, silent skips, crashes on malformed input, and a sensitive
document surviving in a reused export folder. Imports go through the
repo's src/ layout, mirroring conftest's entrypoint discovery.
"""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ghostdocs.cli import cmd_check  # noqa: E402
from ghostdocs.export import export_corpus  # noqa: E402
from ghostdocs.extract import _pdf_streams, extract_file, extract_html, extract_pdf  # noqa: E402
from ghostdocs.profile import Profile, load_profile  # noqa: E402
from ghostdocs.report import write_report  # noqa: E402
from ghostdocs.scan import scan_corpus  # noqa: E402
from ghostdocs.sections import find_date, split_sections  # noqa: E402

from conftest import copy_corpus, out_text, run_ghostdocs  # noqa: E402


def _pdf(content: bytes) -> bytes:
    return (b"%PDF-1.4\n1 0 obj<</Type /Page>>endobj\nstream\n"
            + content + b"\nendstream\n")


def _corpus(tmp_path, files: dict[str, str]) -> Path:
    root = tmp_path / "corpus"
    root.mkdir()
    for name, text in files.items():
        (root / name).write_text(text, encoding="utf-8")
    return root


# ---- text decoding ----

def test_latin1_text_is_not_garbled_as_utf16(tmp_path):
    # even-length latin-1 bytes used to "decode" as UTF-16 into CJK junk
    # with no lossy flag, because utf-16 was tried without requiring a BOM
    p = tmp_path / "prices.txt"
    p.write_bytes("£5 caféx".encode("latin-1"))
    ex = extract_file(p)
    assert ex.text == "£5 caféx"
    assert "lossy-decode" in ex.flags


def test_utf8_bom_does_not_break_first_heading(tmp_path):
    p = tmp_path / "doc.md"
    p.write_bytes("# Real Title\n\nbody text".encode("utf-8-sig"))
    ex = extract_file(p)
    sections = split_sections("doc.md", ex.text)
    assert sections[0].title == "Real Title"


def test_utf16_bom_text_still_decodes(tmp_path):
    p = tmp_path / "doc.txt"
    p.write_bytes("héllo wörld".encode("utf-16"))
    ex = extract_file(p)
    assert ex.text == "héllo wörld"


# ---- HTML headings ----

def test_html_headings_become_markdown_headings():
    ex = extract_html(
        b"<h1>Main Title</h1><p>First para.</p>"
        b"<h2>Sub Head</h2><p>Second para.</p>")
    assert "# Main Title" in ex.text
    assert "## Sub Head" in ex.text
    sections = split_sections("page.html", ex.text)
    assert [s.title for s in sections] == ["Main Title", "Sub Head"]
    assert sections[1].heading_trail == ["Main Title", "Sub Head"]


def test_html_unclosed_heading_still_counts():
    ex = extract_html(b"<p>intro</p><h1>Lonely Title")
    assert "# Lonely Title" in ex.text


# ---- sections: dates and fences ----

def test_find_date_skips_impossible_calendar_dates():
    assert find_date("Updated 2024-02-31, corrected 2024-03-01") == "2024-03-01"
    assert find_date("Dated 2023-02-29 only") is None
    assert find_date("Policy 2026-03-39") is None


def test_find_date_means_first_in_the_document():
    text = "Effective January 5, 2024. Revised 2026-03-01."
    assert find_date(text) == "2024-01-05"


def test_heading_inside_code_fence_is_not_a_section():
    md = ("# Real\n\n```\n# not a heading\ncode\n```\n\nmore text\n\n"
          "## Second\n\nbody2")
    sections = split_sections("d.md", md)
    assert [s.title for s in sections] == ["Real", "Second"]
    assert "# not a heading" in sections[0].text


# ---- PDF extraction ----

def test_pdf_hex_string_text_is_extracted():
    ex = extract_pdf(_pdf(b"BT /F1 12 Tf <48656C6C6F20576F726C64> Tj ET"))
    assert ex.covered
    assert ex.text == "Hello World"


def test_pdf_tj_array_mixing_literal_and_hex():
    ex = extract_pdf(_pdf(b"BT [(Hel) 120 (lo ) <576F726C64>] TJ ET"))
    assert ex.text == "Hel lo World"


def test_pdf_utf16be_literal_string_decodes():
    lit = b"(" + b"\xfe\xff" + "Hello".encode("utf-16-be") + b")"
    ex = extract_pdf(_pdf(b"BT " + lit + b" Tj ET"))
    assert ex.text == "Hello"


def test_pdf_stream_strips_only_one_trailing_eol():
    # the payload itself ends in \n; only the delimiter EOL may be removed
    assert list(_pdf_streams(b"stream\nabc\n\nendstream")) == [b"abc\n"]


# ---- profile validation ----

def test_profile_rejects_string_instead_of_list(tmp_path):
    (tmp_path / ".ghostdocs.json").write_text('{"include": "*.md"}')
    with pytest.raises(ValueError):
        load_profile(tmp_path)


def test_profile_rejects_non_object_modes(tmp_path):
    (tmp_path / ".ghostdocs.json").write_text('{"modes": ["full"]}')
    with pytest.raises(ValueError):
        load_profile(tmp_path)


def test_profile_rejects_non_string_list_items(tmp_path):
    (tmp_path / ".ghostdocs.json").write_text('{"include": [123]}')
    with pytest.raises(ValueError):
        load_profile(tmp_path)


def test_authoritative_prefix_stops_at_path_boundary():
    prof = Profile(authoritative_sources=["off"])
    assert not prof.is_authoritative("office/guide.md")
    assert prof.is_authoritative("off/guide.md")
    assert Profile(authoritative_sources=["official"]).is_authoritative(
        "official/guide.md")


# ---- scan robustness / honesty ----

def test_scan_names_unknown_formats_instead_of_skipping(tmp_path):
    root = _corpus(tmp_path, {"a.md": "# A\n\nhello world"})
    (root / "data.csv").write_text("x,y\n1,2")
    (root / "img.png").write_bytes(b"\x89PNG")
    (root / "noext").write_text("plain")
    corpus = scan_corpus(root)
    not_covered = {n.path for n in corpus.not_covered}
    assert {"data.csv", "img.png", "noext"} <= not_covered


def test_scan_names_unreadable_file_instead_of_crashing(tmp_path):
    root = _corpus(tmp_path, {"a.md": "# A\n\nhello world"})
    os.symlink("/nonexistent-target-xyz", root / "broken.txt")
    corpus = scan_corpus(root)  # used to raise FileNotFoundError
    assert [n.path for n in corpus.not_covered] == ["broken.txt"]
    assert "could not be read" in corpus.not_covered[0].reason
    assert [d.path for d in corpus.docs] == ["a.md"]


def test_scan_works_when_corpus_lives_under_a_skip_named_folder(tmp_path):
    root = tmp_path / "node_modules" / "corpus"
    root.mkdir(parents=True)
    (root / "a.md").write_text("# A\n\nhello world")
    git = root / ".git"
    git.mkdir()
    (git / "ignored.md").write_text("# Hidden\n\ninternal")
    corpus = scan_corpus(root)
    assert [d.path for d in corpus.docs] == ["a.md"]


# ---- check command ----

def test_check_rejects_non_json_manifest(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "manifest.json").write_text("{not json")
    assert cmd_check(argparse.Namespace(bundle=str(bundle))) == 2


def test_check_reports_malformed_chunks_instead_of_crashing(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "manifest.json").write_text(json.dumps(
        {"files": [], "totals": {"chunk_estimated_tokens": 0}}))
    (bundle / "chunks.jsonl").write_text("{bad line\n")
    assert cmd_check(argparse.Namespace(bundle=str(bundle))) == 1


def test_check_flags_file_not_in_manifest(tmp_path):
    bundle = tmp_path / "bundle"
    (bundle / "files").mkdir(parents=True)
    body = "hello"
    (bundle / "files" / "a.md.txt").write_text(body)
    (bundle / "files" / "stale.md.txt").write_text("old export leftover")
    manifest = {"files": [{"path": "a.md",
                           "sha256": hashlib.sha256(body.encode()).hexdigest()}],
                "totals": {"chunk_estimated_tokens": 0}}
    (bundle / "manifest.json").write_text(json.dumps(manifest))
    assert cmd_check(argparse.Namespace(bundle=str(bundle))) == 1


def test_check_still_accepts_a_fresh_export(tmp_path):
    corpus = copy_corpus(tmp_path, "dedupe_corpus")
    out = tmp_path / "export"
    proc = run_ghostdocs(["export", corpus, "-o", out])
    assert proc.returncode == 0, out_text(proc)
    proc = run_ghostdocs(["check", out])
    assert proc.returncode == 0, out_text(proc)


# ---- CLI argument validation ----

def test_scan_rejects_negative_top(tmp_path):
    corpus = copy_corpus(tmp_path, "dedupe_corpus")
    proc = run_ghostdocs(["scan", corpus, "--top", "-1"])
    assert proc.returncode == 2


def test_export_rejects_negative_fit(tmp_path):
    corpus = copy_corpus(tmp_path, "dedupe_corpus")
    proc = run_ghostdocs(["export", corpus, "-o", tmp_path / "o", "--fit", "-5"])
    assert proc.returncode == 2


# ---- report ----

def test_write_report_creates_missing_parent_dirs(tmp_path):
    root = _corpus(tmp_path, {"a.md": "# A\n\nhello world this is text"})
    corpus = scan_corpus(root)
    out = write_report(corpus, tmp_path / "deep" / "deeper" / "report.html")
    assert out.is_file()


# ---- export into a reused folder ----

_SECRET = "# Secret\n\nCard 4111 1111 1111 1111 on file for the customer."
_CLEAN = "# Clean\n\nDelivery information for everyone, no secrets here."


def _secret_corpus(tmp_path):
    return _corpus(tmp_path, {"secret.md": _SECRET, "clean.md": _CLEAN})


def test_reexport_removes_previously_exported_sensitive_file(tmp_path):
    root = _secret_corpus(tmp_path)
    corpus = scan_corpus(root)
    out = tmp_path / "out"
    export_corpus(corpus, out, allow_sensitive=True)
    assert (out / "files" / "secret.md.txt").exists()
    result = export_corpus(corpus, out)  # default: secret held out
    assert result.held_out == ["secret.md"]
    assert not (out / "files" / "secret.md.txt").exists()
    remaining = "\n".join(p.read_text(errors="replace")
                          for p in out.rglob("*") if p.is_file())
    assert "4111 1111 1111 1111" not in remaining


def test_reexport_shape_switch_removes_stale_artifacts(tmp_path):
    root = _secret_corpus(tmp_path)
    corpus = scan_corpus(root)
    out = tmp_path / "out"
    export_corpus(corpus, out, shape="both")
    assert (out / "PROMPT.md").exists() and (out / "files").exists()
    export_corpus(corpus, out, shape="chunks")
    assert not (out / "PROMPT.md").exists()
    assert not (out / "files" / "clean.md.txt").exists()
    assert (out / "chunks.jsonl").exists() and (out / "manifest.json").exists()
