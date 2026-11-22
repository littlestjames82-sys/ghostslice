"""Excerpts: bounded, and made of the real file text (PLAN: search
returns sliced excerpts, never whole files, with token estimates)."""
from __future__ import annotations

import re
from pathlib import Path

MARKER_CHARS = ">*|# \t"


def _clean_lines(excerpt: str) -> list[str]:
    """Excerpt lines with match markers / gutters stripped."""
    out = []
    for raw in excerpt.splitlines():
        line = raw.strip()
        # Drop a leading line-number gutter like "12:" or "12 |".
        line = re.sub(r"^\d{1,6}\s*[:|]\s?", "", line)
        line = line.lstrip(MARKER_CHARS).rstrip()
        if line:
            out.append(line)
    return out


def _source_for(hit, alpha, beta) -> Path | None:
    for root in (alpha, beta):
        cand = root / hit["path"]
        if cand.is_file():
            return cand
    return None


def test_excerpt_text_is_verbatim_file_text(cli, indexed):
    alpha, beta, db = indexed
    proc, hits = cli.search_json(db, "quixotic")
    assert proc.returncode == 0 and hits
    checked = 0
    for hit in hits:
        src = _source_for(hit, alpha, beta)
        assert src is not None, f"hit path does not resolve: {hit['path']}"
        source_text = src.read_text()
        lines = [ln for ln in _clean_lines(hit["excerpt"]) if len(ln) >= 15]
        assert lines, f"hit for {hit['path']} has an empty excerpt"
        assert any(ln in source_text for ln in lines), (
            f"no excerpt line for {hit['path']} appears verbatim in the "
            f"source file. Excerpt was:\n{hit['excerpt']}")
        checked += 1
    assert checked >= 2  # at least the two code files, one per project


def test_excerpt_includes_neighbouring_context_lines(cli, indexed):
    _, _, db = indexed
    proc, hits = cli.search_json(db, "quixotic")
    assert hits
    auth = [h for h in hits if h["path"] == "src/auth.py"]
    assert auth, "no hit for src/auth.py"
    excerpt = auth[0]["excerpt"]
    # The match is the docstring line; +/- context must bring in a
    # neighbouring real line, not just the match itself.
    neighbours = ("def handle_quixotic_login", "missing session token",
                  "session_token.startswith")
    assert any(n in excerpt for n in neighbours), (
        f"excerpt shows no context lines around the match:\n{excerpt}")


def test_excerpt_is_smaller_than_the_file(cli, indexed):
    alpha, _, db = indexed
    proc, hits = cli.search_json(db, "middletermreference")
    assert proc.returncode == 0 and hits
    hit = [h for h in hits if h["path"] == "src/reference.py"]
    assert hit, f"reference.py not in hits: {[h['path'] for h in hits]}"
    hit = hit[0]
    source_text = (alpha / "src" / "reference.py").read_text()
    assert len(hit["excerpt"]) < len(source_text) // 2, (
        "excerpt is not a small slice of the file")
    if hit["excerpt_tokens"] is not None and hit["file_tokens"] is not None:
        assert 0 < hit["excerpt_tokens"] < hit["file_tokens"], (
            f"excerpt tokens {hit['excerpt_tokens']} not below whole-file "
            f"tokens {hit['file_tokens']}")
    else:
        raise AssertionError(
            "hit carries no excerpt/file token estimates, but the PLAN "
            f"promises both on every hit. Raw hit: {hit['raw']}")


def test_excerpt_from_a_very_long_line_is_bounded(cli, indexed):
    alpha, _, db = indexed
    source_line = max(
        (alpha / "src" / "longline.py").read_text().splitlines(), key=len)
    proc, hits = cli.search_json(db, "needlelongline")
    assert proc.returncode == 0 and hits
    hit = hits[0]
    assert "needlelongline" in hit["excerpt"] or "needlelongline" in proc.stdout
    assert len(hit["excerpt"]) <= 4000, (
        f"excerpt from a {len(source_line)}-char line is "
        f"{len(hit['excerpt'])} chars: not bounded")
    assert len(hit["excerpt"]) < len(source_line)
    # The full padding runs of the source line must not pour through.
    assert ("x" * 2000) not in proc.stdout
    assert ("y" * 2000) not in proc.stdout


def test_max_tokens_flag_bounds_total_output(cli, indexed):
    _, _, db = indexed
    proc_full, hits_full = cli.search_json(db, "quixotic")
    assert hits_full
    proc, hits = cli.search_json(db, "quixotic",
                                 extra=["--max-tokens", "5"])
    assert proc.returncode in (0, 1), proc.stdout + proc.stderr
    if hits:
        total = sum(h["excerpt_tokens"] or 0 for h in hits)
        # Allow one minimum excerpt; the cap must still bite hard
        # compared with the uncapped run.
        full_total = sum(h["excerpt_tokens"] or 0 for h in hits_full)
        assert total <= max(5, full_total // 2) or len(hits) < len(hits_full), (
            f"--max-tokens 5 did not bound output: {total} vs {full_total}")
