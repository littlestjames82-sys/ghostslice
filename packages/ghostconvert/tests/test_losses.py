"""Losses accounting: nothing the target format cannot carry is dropped
silently. Each target's LOSSES.md names it, and edge-case manifest
content (unknown modes, escaping paths, missing bodies, symbols lists)
is reported rather than swallowed.
"""
from __future__ import annotations

import re

import pytest

from conftest import (body_of, combined, entry, files_with_bodies, run_gc,
                      write_hand_bundle)

TARGET_ARTIFACT = {
    "agents": "AGENTS.md",
    "copilot": ".github/copilot-instructions.md",
    "generic": "prompt.md",
}


@pytest.mark.parametrize("target", ["agents", "cursor", "copilot",
                                    "generic"])
def test_losses_name_excluded_files_hashes_and_tokens(
        golden_bundle, tmp_path, target):
    out = tmp_path / "out"
    proc = run_gc("convert", str(golden_bundle), "--to", target,
                  "-o", str(out))
    assert proc.returncode == 0, combined(proc)
    losses = (out / "LOSSES.md").read_text(encoding="utf-8")
    # The excluded file is named.
    assert "vendor/blob.py" in losses
    # Per-file sha256 values are named as not carried.
    assert re.search(r"sha256|hash", losses, re.IGNORECASE)
    # Per-file token estimates are named as not carried.
    assert re.search(r"token", losses, re.IGNORECASE)


def test_losses_for_all_written_per_target(golden_bundle, tmp_path):
    out = tmp_path / "out"
    proc = run_gc("convert", str(golden_bundle), "--to", "all",
                  "-o", str(out))
    assert proc.returncode == 0, combined(proc)
    for target in ("agents", "cursor", "copilot", "generic"):
        losses = (out / target / "LOSSES.md").read_text(encoding="utf-8")
        assert "vendor/blob.py" in losses, target


def test_cursor_losses_name_the_grouping(golden_bundle, tmp_path):
    out = tmp_path / "out"
    proc = run_gc("convert", str(golden_bundle), "--to", "cursor",
                  "-o", str(out))
    assert proc.returncode == 0, combined(proc)
    losses = (out / "LOSSES.md").read_text(encoding="utf-8")
    assert re.search(r"group", losses, re.IGNORECASE)


def test_zero_loss_conversion_says_so(tmp_path):
    # A single full-mode file whose manifest entry carries nothing the
    # generic format can lose: no hash, no token counts, no excluded
    # files, no redactions. The note must still exist and say so.
    bundle = write_hand_bundle(
        tmp_path / "bundle",
        entries=[entry("only.py", "full")],
        bodies={"only.py": "print('only')\n"})
    out = tmp_path / "out"
    proc = run_gc("convert", str(bundle), "--to", "generic",
                  "-o", str(out))
    assert proc.returncode == 0, combined(proc)
    losses = (out / "LOSSES.md").read_text(encoding="utf-8")
    assert re.search(r"no losses", losses, re.IGNORECASE)


def test_missing_body_file_is_named_not_dropped(tmp_path):
    bundle = write_hand_bundle(
        tmp_path / "bundle",
        entries=[entry("present.py", "full",
                       sha256="a" * 64, original_tokens=10,
                       sliced_tokens=10),
                 entry("ghost.py", "full",
                       sha256="b" * 64, original_tokens=10,
                       sliced_tokens=10)],
        bodies={"present.py": "PRESENT = 1\n"})
    out = tmp_path / "out"
    proc = run_gc("convert", str(bundle), "--to", "agents",
                  "-o", str(out))
    assert proc.returncode == 0, combined(proc)
    text = (out / "AGENTS.md").read_text(encoding="utf-8")
    assert "PRESENT = 1" in text
    assert "File: ghost.py" not in text
    losses = (out / "LOSSES.md").read_text(encoding="utf-8")
    assert "ghost.py" in losses
    # inspect also reports it.
    proc = run_gc("inspect", str(bundle))
    assert proc.returncode == 0, combined(proc)
    assert "ghost.py" in combined(proc)


def test_unknown_mode_is_reported_not_silently_dropped(tmp_path):
    # A mode GhostConvert has never heard of: the file must still be
    # converted with its mode label visible as written, and the mode
    # must show up in inspect's census; never silently dropped or
    # relabelled to a known mode.
    bundle = write_hand_bundle(
        tmp_path / "bundle",
        entries=[entry("weird.py", "banana-split",
                       sha256="c" * 64, original_tokens=5,
                       sliced_tokens=5)],
        bodies={"weird.py": "WEIRD = True\n"})
    out = tmp_path / "out"
    proc = run_gc("convert", str(bundle), "--to", "agents",
                  "-o", str(out))
    assert proc.returncode == 0, combined(proc)
    text = (out / "AGENTS.md").read_text(encoding="utf-8")
    assert "WEIRD = True" in text
    assert "banana-split" in text
    proc = run_gc("inspect", str(bundle))
    assert proc.returncode == 0, combined(proc)
    assert "banana-split" in combined(proc)


def test_escaping_manifest_path_is_skipped_and_named(tmp_path):
    # The manifest names a path outside the bundle. It must not be read
    # (a sentinel file sits where a naive join would land) and must be
    # named as skipped, in LOSSES.md and in inspect.
    outside = tmp_path / "evil.py"
    outside.write_text("SENTINEL_EVIL = True\n", encoding="utf-8")
    bundle = write_hand_bundle(
        tmp_path / "bundle",
        entries=[entry("ok.py", "full", sha256="d" * 64,
                       original_tokens=5, sliced_tokens=5),
                 entry("../evil.py", "full", sha256="e" * 64,
                       original_tokens=5, sliced_tokens=5)],
        bodies={"ok.py": "OK = 1\n"})
    out = tmp_path / "out"
    proc = run_gc("convert", str(bundle), "--to", "agents",
                  "-o", str(out))
    assert proc.returncode == 0, combined(proc)
    text = (out / "AGENTS.md").read_text(encoding="utf-8")
    assert "OK = 1" in text
    assert "SENTINEL_EVIL" not in text
    losses = (out / "LOSSES.md").read_text(encoding="utf-8")
    assert "../evil.py" in losses
    proc = run_gc("inspect", str(bundle))
    assert proc.returncode == 0, combined(proc)
    assert "../evil.py" in combined(proc)


def test_symbols_mode_label_lists_symbols(tmp_path):
    bundle = write_hand_bundle(
        tmp_path / "bundle",
        entries=[entry("sym.py", "symbols", sha256="f" * 64,
                       original_tokens=50, sliced_tokens=9,
                       symbols_included=["greet", "add"])],
        bodies={"sym.py": "def greet(name): ...\ndef add(a, b): ...\n"})
    out = tmp_path / "out"
    proc = run_gc("convert", str(bundle), "--to", "agents",
                  "-o", str(out))
    assert proc.returncode == 0, combined(proc)
    text = (out / "AGENTS.md").read_text(encoding="utf-8")
    assert "File: sym.py (mode: symbols" in text
    assert "greet" in text and "add" in text


def test_prompt_md_fallback_supplies_bodies(tmp_path):
    # No files/ directory at all: bodies must come from PROMPT.md,
    # parsed on its '# File:' headers.
    prompt = (
        "# Optimized agent context bundle (GhostSlice)\n"
        "\n---\n\n"
        "# File: alpha.py (mode: full)\n\n"
        "ALPHA = 1\n"
        "\n---\n\n"
        "# File: beta.py (mode: full)\n\n"
        "BETA = 2\n")
    bundle = write_hand_bundle(
        tmp_path / "bundle",
        entries=[entry("alpha.py", "full", sha256="1" * 64,
                       original_tokens=4, sliced_tokens=4),
                 entry("beta.py", "full", sha256="2" * 64,
                       original_tokens=4, sliced_tokens=4)],
        prompt_text=prompt)
    out = tmp_path / "out"
    proc = run_gc("convert", str(bundle), "--to", "generic",
                  "-o", str(out))
    assert proc.returncode == 0, combined(proc)
    text = (out / "prompt.md").read_text(encoding="utf-8")
    assert "ALPHA = 1" in text
    assert "BETA = 2" in text
    assert text.find("alpha.py") < text.find("beta.py")


def test_bodyless_slice_entry_is_named_in_losses(golden_bundle, tmp_path):
    # The golden bundle's strip-tests entry has sliced_tokens 0 and no
    # body anywhere. Conversion must name it as absent, not drop it
    # silently and not invent a body for it.
    from conftest import manifest_order
    entries = manifest_order(golden_bundle)
    absent = [e["path"] for e in entries
              if e["mode"] != "exclude"
              and body_of(golden_bundle, e["path"]) is None]
    assert absent, "fixture premise: golden bundle has a bodyless entry"
    out = tmp_path / "out"
    proc = run_gc("convert", str(golden_bundle), "--to", "agents",
                  "-o", str(out))
    assert proc.returncode == 0, combined(proc)
    losses = (out / "LOSSES.md").read_text(encoding="utf-8")
    for path in absent:
        assert path in losses, path
