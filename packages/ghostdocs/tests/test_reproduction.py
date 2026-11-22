"""PLAN verification bar 4 - reproduction (chunk pack).

Required behaviour: chunk-pack totals equal manifest totals, chunk
hashes verify against the chunk text, and re-running an export on an
unchanged corpus reproduces identical totals.

Assumed chunk-pack switch (documented in REPORT_B.md): the export must
offer a JSONL chunk pack. Tried in order: the default export (the
landed core writes bundle + chunks by default, `--shape both`), then
`--shape chunks`, then `--format chunks`. Each JSONL row is one document
section with at least: source path, heading trail, sha256 of the chunk
text, a token estimate, and the chunk text itself (or a path to it).
"""
import hashlib
import json
from pathlib import Path

from conftest import copy_corpus, export_corpus, load_manifest, out_text

CHUNK_FLAG_VARIANTS = ((), ("--shape", "chunks"), ("--shape", "both"),
                       ("--format", "chunks"))
TOKEN_KEYS = ("tokens", "estimated_tokens", "token_estimate", "est_tokens")
TEXT_KEYS = ("text", "content", "chunk_text")
HASH_KEYS = ("sha256", "hash", "content_sha256")
TOTAL_KEYS = ("total_tokens", "total_estimated_tokens", "tokens_total",
              "estimated_total", "chunk_estimated_tokens",
              "exported_estimated_tokens")


def _chunk_rows(out_dir):
    rows = []
    for p in sorted(Path(out_dir).rglob("*.jsonl")):
        for line in p.read_text(errors="replace").splitlines():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _make_chunk_export(tmp_path, corpus, tag):
    out = tmp_path / tag
    last = None
    for variant in CHUNK_FLAG_VARIANTS:
        proc = export_corpus(corpus, out, variant)
        last = proc
        if proc.returncode == 0 and _chunk_rows(out):
            return out
    raise AssertionError(
        "no chunk-pack export variant produced a .jsonl file; last "
        f"attempt output: {out_text(last)[:400] if last else 'n/a'}")


def _pick(row, keys):
    for k in keys:
        if k in row and row[k] is not None:
            return row[k]
    return None


def _manifest_total(manifest, rows_sum):
    if not isinstance(manifest, dict):
        return None
    for k in TOTAL_KEYS:
        if isinstance(manifest.get(k), (int, float)):
            return manifest[k]
    totals = manifest.get("totals")
    if isinstance(totals, dict):
        for k in TOTAL_KEYS + TOKEN_KEYS:
            if isinstance(totals.get(k), (int, float)):
                return totals[k]
    return None


def test_chunk_pack_totals_match_manifest_and_hashes_verify(tmp_path):
    corpus = copy_corpus(tmp_path, "dedupe_corpus")
    out = _make_chunk_export(tmp_path, corpus, "chunks1")
    rows = _chunk_rows(out)
    assert rows, "chunk pack is empty"
    rows_sum = 0
    for row in rows:
        tok = _pick(row, TOKEN_KEYS)
        assert tok is not None, f"chunk row has no token estimate: {row.keys()}"
        rows_sum += tok
        text = _pick(row, TEXT_KEYS)
        digest = _pick(row, HASH_KEYS)
        if text is not None and digest:
            actual = hashlib.sha256(str(text).encode()).hexdigest()
            assert actual == digest, "chunk sha256 does not match its text"
    manifest = load_manifest(out)
    total = _manifest_total(manifest, rows_sum)
    assert total is not None, "no manifest total found to compare against"
    assert total == rows_sum, \
        f"manifest total {total} != sum of chunk estimates {rows_sum}"


def test_rerun_reproduces_identical_totals(tmp_path):
    corpus = copy_corpus(tmp_path, "dedupe_corpus")
    out1 = _make_chunk_export(tmp_path, corpus, "chunks-a")
    out2 = _make_chunk_export(tmp_path, corpus, "chunks-b")
    rows1, rows2 = _chunk_rows(out1), _chunk_rows(out2)
    sum1 = sum(_pick(r, TOKEN_KEYS) or 0 for r in rows1)
    sum2 = sum(_pick(r, TOKEN_KEYS) or 0 for r in rows2)
    assert sum1 == sum2 and sum1 > 0
    hashes1 = sorted(_pick(r, HASH_KEYS) for r in rows1)
    hashes2 = sorted(_pick(r, HASH_KEYS) for r in rows2)
    assert hashes1 == hashes2
