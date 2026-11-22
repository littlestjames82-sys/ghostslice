"""HTML section fidelity - DEEPEN improvement (Oct 18, 2026).

Before this fix, _HTMLText emitted the ``#`` markers at the heading's
end tag, on their own line after the title text. That never matched a
Markdown heading line, so split_sections() collapsed every HTML
document - one of the four covered formats - into a single section.
Chunk packs, headings mode, per-section heat and TF-IDF task selection
all silently degraded for HTML corpora while scan still reported the
document as covered.

These tests pin the fixed behaviour: HTML headings become Markdown
heading lines, HTML documents split into heading sections with correct
trails, and exports chunk HTML at those headings like Markdown.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ghostdocs.extract import extract_html  # noqa: E402
from ghostdocs.sections import split_sections  # noqa: E402

from conftest import export_corpus, out_text, run_ghostdocs  # noqa: E402

HTML_DOC = b"""<!DOCTYPE html>
<html><head><title>Help</title><style>.x{color:red}</style>
<script>trackMe()</script></head>
<body>
<h1>Store Help</h1>
<p>Welcome to the help centre.</p>
<h2>Refund window</h2>
<p>You have thirty days to ask for a refund.</p>
<p>Refunds go back to the original payment method.</p>
<h2>Exchanges</h2>
<p>Exchanges are handled at the counter.</p>
</body></html>
"""


def _write_html_corpus(tmp_path):
    corpus = tmp_path / "html_corpus"
    corpus.mkdir()
    (corpus / "help.html").write_bytes(HTML_DOC)
    return corpus


# ---------------- unit level: extraction + sections ----------------

def test_html_headings_become_markdown_heading_lines():
    lines = extract_html(HTML_DOC).text.splitlines()
    assert "# Store Help" in lines
    assert "## Refund window" in lines
    assert "## Exchanges" in lines
    # script/style content still stripped, as before
    assert "trackMe" not in "\n".join(lines)
    assert "color:red" not in "\n".join(lines)


def test_html_document_splits_into_sections_with_trails():
    sections = split_sections("help.html", extract_html(HTML_DOC).text)
    assert [s.title for s in sections] == [
        "Store Help", "Refund window", "Exchanges"]
    assert sections[0].heading_trail == ["Store Help"]
    assert sections[1].heading_trail == ["Store Help", "Refund window"]
    assert "thirty days" in sections[1].text
    assert "thirty days" not in sections[2].text


def test_html_heading_inline_markup_and_entities():
    ex = extract_html(
        b"<h2>Refunds &amp; <em>store</em> credit</h2><p>Body text.</p>")
    assert "## Refunds & store credit" in ex.text.splitlines()
    sections = split_sections("p.html", ex.text)
    assert sections[0].title == "Refunds & store credit"


def test_unclosed_heading_does_not_swallow_body_text():
    ex = extract_html(b"<h1>Only Title<p>body text follows")
    sections = split_sections("p.html", ex.text)
    assert sections[0].title == "Only Title"
    assert "body text follows" in sections[0].text
    assert "body text" not in sections[0].title


def test_html_without_headings_stays_one_section():
    ex = extract_html(b"<p>plain paragraph one</p><p>plain two</p>")
    sections = split_sections("plain.html", ex.text)
    assert len(sections) == 1
    assert "plain paragraph one" in sections[0].text


# ---------------- behaviour level: scan + export ----------------

def test_scan_json_reports_html_sections(tmp_path):
    corpus = _write_html_corpus(tmp_path)
    proc = run_ghostdocs(["scan", corpus, "--json"])
    assert proc.returncode == 0, out_text(proc)
    data = json.loads(proc.stdout)
    (doc,) = data["documents"]
    assert doc["path"] == "help.html"
    assert [s["title"] for s in doc["sections"]] == [
        "Store Help", "Refund window", "Exchanges"]


def test_export_chunks_follow_html_headings(tmp_path):
    corpus = _write_html_corpus(tmp_path)
    out = tmp_path / "export"
    proc = export_corpus(corpus, out)
    assert proc.returncode == 0, out_text(proc)
    rows = [json.loads(line) for line in
            (out / "chunks.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()]
    html_rows = [r for r in rows if r["source"] == "help.html"]
    assert len(html_rows) == 3
    assert html_rows[1]["heading_trail"] == ["Store Help", "Refund window"]
    assert "thirty days" in html_rows[1]["text"]
    assert "Exchanges are handled" in html_rows[2]["text"]
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["totals"]["chunk_estimated_tokens"] == \
        sum(r["estimated_tokens"] for r in rows)


def test_headings_mode_export_for_html_keeps_first_paragraph_only(tmp_path):
    corpus = _write_html_corpus(tmp_path)
    (corpus / ".ghostdocs.json").write_text(
        json.dumps({"modes": {"*.html": "headings"}}), encoding="utf-8")
    out = tmp_path / "export-headings"
    proc = export_corpus(corpus, out)
    assert proc.returncode == 0, out_text(proc)
    body = (out / "files" / "help.html.txt").read_text(encoding="utf-8")
    assert "## Refund window" in body
    assert "You have thirty days to ask for a refund." in body
    # second paragraph of the section is dropped in headings mode
    assert "original payment method" not in body
