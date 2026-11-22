"""Near-duplicate dropping (PLAN.md / README: "Drop duplicates using
GhostSlice's exact and near duplicate detection").

Before this change the proxy only dropped byte-identical copies.
These tests pin the GhostSlice-canonical behaviour now applied at
request time:

- near: Jaccard similarity over distinct non-empty stripped lines
  >= 0.85, only for blocks with >= 200 normalized characters and
  >= 8 distinct lines (GhostSlice duplicates.py floors/threshold);
- exact also matches after GhostSlice normalization (trailing
  whitespace / trailing blank lines ignored);
- only an earlier KEPT block can be a keeper: a block dropped as
  junk or by the secrets guard never swallows a later clean block;
- the transform map records duplicate_of + similarity (paths and a
  score only, never content).

All unit tests run transform_request directly on markdown blocks
(default mode "full", so no slicer behaviour is involved) and pass
whether or not GhostSlice is importable: the adapter's local
fallback implements the identical algorithm.
"""

import json
import sys

from conftest import (
    SRC,
    ProxyProcess,
    context_block,
    http_post,
    make_project,
    messages_request,
    requires_core,
)

# Same src bootstrap as test_slice_adapter_fallback.py: this module
# imports ghostproxy at module level, so it must not depend on the
# caller's PYTHONPATH or on another test module being collected
# first and fixing sys.path as a side effect.
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ghostproxy import slice_adapter  # noqa: E402
from ghostproxy.transform import transform_request  # noqa: E402

HEADERS = {"x-api-key": "CANARY-API-KEY-ghostproxy-leak-test-0000000001",
           "anthropic-version": "2023-06-01", "content-type": "application/json"}


def _lines(tag, count=20, start=0):
    return "\n".join(
        f"{tag} line {i:02d} describes the caching layer behaviour in detail"
        for i in range(start, start + count)) + "\n"


def _request(sections):
    return messages_request(sections)


def _map_by_path(result):
    return {entry["path"]: entry for entry in result.transform_map}


def _sent_texts(result):
    out = []
    for msg in result.request["messages"]:
        content = msg.get("content")
        if isinstance(content, list):
            out.extend(p.get("text", "") for p in content
                       if isinstance(p, dict) and p.get("type") == "text")
        elif isinstance(content, str):
            out.append(content)
    return out


def test_adapter_fingerprint_thresholds_match_ghostslice():
    assert slice_adapter.NEAR_THRESHOLD == 0.85
    assert slice_adapter.NEAR_MIN_CHARS == 200
    assert slice_adapter.NEAR_MIN_LINES == 8
    assert slice_adapter.near_threshold() == 0.85


def test_adapter_similarity_is_line_shingle_jaccard():
    a = slice_adapter.duplicate_fingerprint(_lines("alpha"))
    b = slice_adapter.duplicate_fingerprint(_lines("alpha"))
    assert slice_adapter.near_similarity(a, b) == 1.0
    c = slice_adapter.duplicate_fingerprint(_lines("omega"))
    assert slice_adapter.near_similarity(a, c) == 0.0
    assert a["near_eligible"] is True
    small = slice_adapter.duplicate_fingerprint("tiny\ntext\n")
    assert small["near_eligible"] is False


def test_near_duplicate_block_is_dropped_and_recorded():
    base = _lines("alpha")
    variant_lines = base.splitlines()
    variant_lines[7] = "alpha line 07 was edited locally for this copy only"
    variant = "\n".join(variant_lines) + "\n"  # 19/21 lines shared: 0.9048
    result = transform_request(_request([
        context_block("notes_a.md", base),
        context_block("notes_b.md", variant),
    ]))
    entry = _map_by_path(result)["notes_b.md"]
    assert entry["action"] == "dropped"
    assert entry["reason"] == "near-duplicate"
    assert entry["duplicate_of"] == "notes_a.md"
    assert entry["similarity"] >= 0.85
    assert entry["tokens_out"] == 0
    assert "notes_b.md" in result.files_dropped
    blob = "\n".join(_sent_texts(result))
    assert "edited locally for this copy only" not in blob, \
        "the near-duplicate copy must not be sent upstream"
    assert "alpha line 00" in blob, "the first (keeper) copy is still sent"


def test_dissimilar_blocks_are_both_kept():
    result = transform_request(_request([
        context_block("alpha.md", _lines("alpha")),
        context_block("omega.md", _lines("omega")),
    ]))
    entries = _map_by_path(result)
    assert entries["alpha.md"]["action"] != "dropped"
    assert entries["omega.md"]["action"] != "dropped"
    assert result.files_dropped == []


def test_below_size_floor_similar_blocks_are_both_kept():
    small_a = "same heading\nshort body one\nshort body two\n"
    small_b = "same heading\nshort body one\nshort body two changed\n"
    result = transform_request(_request([
        context_block("small_a.md", small_a),
        context_block("small_b.md", small_b),
    ]))
    entries = _map_by_path(result)
    assert entries["small_a.md"]["action"] != "dropped"
    assert entries["small_b.md"]["action"] != "dropped", \
        "blocks under GhostSlice's near floors are boilerplate, not duplicates"


def test_exact_duplicate_after_whitespace_normalization():
    base = _lines("alpha", count=10)
    messy = "\n".join(line + "   " for line in base.splitlines()) + "\n\n\n"
    assert messy != base
    result = transform_request(_request([
        context_block("clean.md", base),
        context_block("messy.md", messy),
    ]))
    entry = _map_by_path(result)["messy.md"]
    assert entry["action"] == "dropped"
    assert entry["reason"] == "duplicate"
    assert entry["duplicate_of"] == "clean.md"
    assert entry["similarity"] == 1.0


def test_near_match_against_dropped_block_does_not_drop():
    """A junk-dropped block is not a keeper: a clean block that is a
    near-duplicate of the junk copy must still be sent."""
    body = _lines("alpha")
    result = transform_request(_request([
        context_block("package-lock.json", body),
        context_block("notes.md", body),
    ]))
    entries = _map_by_path(result)
    assert entries["package-lock.json"]["reason"] == "lockfile"
    assert entries["notes.md"]["action"] != "dropped", \
        "only kept blocks can be duplicate keepers"


def test_first_copy_wins_regardless_of_later_copies():
    base = _lines("alpha")
    result = transform_request(_request([
        context_block("one.md", base),
        context_block("two.md", base),
        context_block("three.md", base),
    ]))
    entries = _map_by_path(result)
    assert entries["one.md"]["action"] != "dropped"
    assert entries["two.md"]["duplicate_of"] == "one.md"
    assert entries["three.md"]["duplicate_of"] == "one.md"


@requires_core
def test_near_duplicate_sent_once_through_proxy(fake_upstream, tmp_path):
    project = make_project(tmp_path)
    base = _lines("alpha")
    variant_lines = base.splitlines()
    variant_lines[3] = "alpha line 03 carries the UNIQUE NEAR DUP MARKER"
    request = _request([
        context_block("notes_a.md", base),
        context_block("notes_b.md", "\n".join(variant_lines) + "\n"),
    ])
    with ProxyProcess(project, fake_upstream.url, tmp_path / "work") as proxy:
        status, _ = http_post(proxy.url + "/v1/messages",
                              json.dumps(request).encode(), HEADERS)
    assert status == 200
    sent = json.loads(fake_upstream.recorded[-1]["body"])
    blob = json.dumps(sent)
    assert "UNIQUE NEAR DUP MARKER" not in blob
    assert "alpha line 00" in blob
