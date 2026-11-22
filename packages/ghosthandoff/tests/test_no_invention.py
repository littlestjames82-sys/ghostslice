"""No-invention bar (PLAN verification): open loops and next steps
come only from repo facts. A clean repo produces a pack that says so,
with empty loop and next-step lists; a non-git folder still produces
a pack with the git section marked unavailable and exit 0.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pytest  # noqa: E402

import helpers  # noqa: E402

pytestmark = pytest.mark.skipif(
    not helpers.cli_available(),
    reason="ghosthandoff CLI not discoverable (see REPORT_B.md)")


def build_pack(project: Path, tmp_path: Path, name: str = "pack-out"):
    outdir = tmp_path / name
    proc = helpers.run_cli(
        ["pack", str(project), "-o", str(outdir)], cwd=tmp_path)
    assert proc.returncode == 0, (
        f"pack exited {proc.returncode}\n{proc.stdout}\n{proc.stderr}")
    return outdir


def flattened_lists(data, *needles):
    out = []
    for value in helpers.values_for_key(data, *needles):
        if isinstance(value, list):
            out.extend(value)
        elif isinstance(value, dict):
            # A section dict (e.g. markers: {total, items, ...}):
            # its entries live under "items", when it has any.
            items = value.get("items")
            if isinstance(items, list):
                out.extend(items)
        elif value not in (None, "", 0):
            out.append(value)
    return out


def test_clean_repo_pack_has_no_loops_and_no_steps(clean_repo, tmp_path):
    outdir = build_pack(clean_repo, tmp_path)
    data = helpers.load_pack_json(outdir)
    loops = flattened_lists(data, "open_loop", "loop")
    steps = flattened_lists(data, "next_step", "step")
    assert loops == [], f"clean repo produced open loops: {loops}"
    assert steps == [], f"clean repo produced next steps: {steps}"
    markers = flattened_lists(data, "marker", "todo")
    assert markers == [], f"clean repo produced markers: {markers}"


def test_clean_repo_pack_says_so_in_words(clean_repo, tmp_path):
    outdir = build_pack(clean_repo, tmp_path)
    text = helpers.pack_text(outdir).lower()
    assert ("no open loops" in text or "no loops" in text
            or "nothing" in text), (
        "clean pack should state plainly that there is nothing to "
        "hand off; see REPORT_B.md if the wording differs")


def test_fixture_loops_name_real_sources(fixture_repo, tmp_path):
    """No-invention, checked by category: the fixture repo plants
    exactly five loop-worthy facts (uncommitted work, untracked
    files, a stash entry, open markers, a failing verdict). The pack
    must produce loops for those categories, no loop outside them,
    and each loop must name its source (the PLAN requires every loop
    to name where it came from)."""
    outdir = build_pack(fixture_repo, tmp_path)
    data = helpers.load_pack_json(outdir)
    loop_entries = []
    for value in helpers.values_for_key(data, "open_loop", "loop"):
        if isinstance(value, list):
            loop_entries.extend(value)
    assert loop_entries, "fixture repo should produce open loops"

    def blob(entry) -> str:
        if isinstance(entry, str):
            return entry.lower()
        return " ".join(helpers.all_strings(entry)).lower()

    def kind_of(entry) -> str:
        if isinstance(entry, dict):
            return str(entry.get("kind", "")).lower()
        return blob(entry)

    categories = set()
    for entry in loop_entries:
        text = blob(entry)
        kind = kind_of(entry)
        if "uncommitted" in kind or "not committed" in text:
            categories.add("uncommitted")
        elif "untracked" in kind or "untracked" in text:
            categories.add("untracked")
        elif "stash" in kind or "stash" in text:
            categories.add("stash")
        elif "marker" in kind or "marker" in text:
            categories.add("markers")
        elif "verif" in kind or "verdict" in text or "fail" in text:
            categories.add("verification")
        else:
            raise AssertionError(
                f"open loop matches no planted fact category: {entry!r}")
        if isinstance(entry, dict):
            assert entry.get("source"), (
                f"open loop names no source: {entry!r}")
    assert categories == {"uncommitted", "untracked", "stash",
                          "markers", "verification"}
    assert len(loop_entries) == 5, (
        f"expected exactly the 5 planted loop categories, got "
        f"{len(loop_entries)} loops: {loop_entries!r}")


def test_next_steps_are_labelled_as_proposals(fixture_repo, tmp_path):
    outdir = build_pack(fixture_repo, tmp_path)
    text = helpers.pack_text(outdir).lower()
    # Propose-only is a stated property of the pack, not a behaviour
    # the reader has to infer.
    assert "propos" in text, (
        "pack should label its next steps as proposals/drafts")


def test_non_git_folder_still_packs(plain_folder, tmp_path):
    outdir = build_pack(plain_folder, tmp_path)
    text = helpers.pack_text(outdir).lower()
    assert "not a git" in text or "unavailable" in text or \
        "no git" in text, (
            "non-git pack must mark the git section unavailable")
    # The marker section still works without git: file, kind, and the
    # marker text (the core renders it as "[TODO]: <text>").
    text = helpers.pack_text(outdir)
    assert "notes.txt" in text
    assert "TODO" in text
    assert "water the plants on Friday" in text


def test_non_git_folder_tree_untouched(plain_folder, tmp_path):
    before = helpers.tree_hashes(plain_folder)
    build_pack(plain_folder, tmp_path)
    assert helpers.tree_hashes(plain_folder) == before
