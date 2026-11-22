"""Harden-round regression tests: malformed manifests must exit 2
cleanly (never a traceback, never a silent drop), Cursor slug collisions
must not lose a group, and --to all must write nothing when any target
refuses.

These are black-box CLI tests like the rest of the suite.
"""
from __future__ import annotations

import json

from conftest import combined, entry, run_gc, write_hand_bundle


def test_manifest_top_level_not_an_object_exits_2_no_traceback(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "manifest.json").write_text('["not", "an", "object"]',
                                          encoding="utf-8")
    proc = run_gc("convert", str(bundle), "--to", "agents",
                  "-o", str(tmp_path / "out"))
    assert proc.returncode == 2, combined(proc)
    assert "Traceback" not in combined(proc)
    assert "manifest" in combined(proc).lower()
    assert not (tmp_path / "out" / "AGENTS.md").exists()
    proc = run_gc("inspect", str(bundle))
    assert proc.returncode == 2, combined(proc)
    assert "Traceback" not in combined(proc)


def test_manifest_entry_with_non_string_path_exits_2(tmp_path):
    bundle = write_hand_bundle(
        tmp_path / "bundle",
        entries=[{"path": 123, "mode": "full"},
                 entry("ok.py", "full")],
        bodies={"ok.py": "OK = 1\n"})
    proc = run_gc("convert", str(bundle), "--to", "agents",
                  "-o", str(tmp_path / "out"))
    assert proc.returncode == 2, combined(proc)
    assert "Traceback" not in combined(proc)
    assert not (tmp_path / "out" / "AGENTS.md").exists()


def test_manifest_non_object_entry_is_not_silently_dropped(tmp_path):
    bundle = write_hand_bundle(
        tmp_path / "bundle",
        entries=["oops", entry("ok.py", "full")],
        bodies={"ok.py": "OK = 1\n"})
    proc = run_gc("convert", str(bundle), "--to", "agents",
                  "-o", str(tmp_path / "out"))
    # Previously the string entry vanished with no mention anywhere.
    assert proc.returncode == 2, combined(proc)
    assert "Traceback" not in combined(proc)
    assert not (tmp_path / "out" / "AGENTS.md").exists()


def test_manifest_non_string_sha256_exits_2_no_traceback(tmp_path):
    bundle = write_hand_bundle(
        tmp_path / "bundle",
        entries=[entry("gone.py", "full", sha256=123, sliced_tokens=5),
                 entry("ok.py", "full")],
        bodies={"ok.py": "OK = 1\n"})
    proc = run_gc("convert", str(bundle), "--to", "agents",
                  "-o", str(tmp_path / "out"))
    assert proc.returncode == 2, combined(proc)
    assert "Traceback" not in combined(proc)


def test_manifest_non_list_symbols_included_exits_2_no_traceback(tmp_path):
    bundle = write_hand_bundle(
        tmp_path / "bundle",
        entries=[entry("sym.py", "symbols", symbols_included=42)],
        bodies={"sym.py": "def f(): ...\n"})
    proc = run_gc("convert", str(bundle), "--to", "agents",
                  "-o", str(tmp_path / "out"))
    assert proc.returncode == 2, combined(proc)
    assert "Traceback" not in combined(proc)


def test_cursor_slug_collision_keeps_both_groups(tmp_path):
    bundle = write_hand_bundle(
        tmp_path / "bundle",
        entries=[entry("My Docs/a.py", "full"),
                 entry("my-docs/b.py", "full")],
        bodies={"My Docs/a.py": "AAA = 1\n",
                "my-docs/b.py": "BBB = 2\n"})
    out = tmp_path / "out"
    proc = run_gc("convert", str(bundle), "--to", "cursor", "-o", str(out))
    assert proc.returncode == 0, combined(proc)
    rules = sorted((out / ".cursor" / "rules").glob("*.mdc"))
    # Previously both groups slugified to ghostconvert-my-docs.mdc and
    # the second overwrote the first: only one rule file, AAA lost.
    assert len(rules) == 2, [r.name for r in rules]
    texts = [r.read_text(encoding="utf-8") for r in rules]
    assert any("AAA = 1" in t for t in texts)
    assert any("BBB = 2" in t for t in texts)


def test_convert_all_collision_in_later_target_writes_nothing(tmp_path):
    bundle = write_hand_bundle(
        tmp_path / "bundle",
        entries=[entry("ok.py", "full")],
        bodies={"ok.py": "OK = 1\n"})
    out = tmp_path / "out"
    (out / "copilot").mkdir(parents=True)
    (out / "copilot" / "LOSSES.md").write_text("mine\n", encoding="utf-8")
    proc = run_gc("convert", str(bundle), "--to", "all", "-o", str(out))
    assert proc.returncode == 2, combined(proc)
    # Earlier targets must not have been written before the refusal.
    assert not (out / "agents" / "AGENTS.md").exists()
    assert not (out / "generic" / "prompt.md").exists()
    assert not list(out.rglob("*.mdc"))
    assert (out / "copilot" / "LOSSES.md").read_text(
        encoding="utf-8") == "mine\n"


def test_artifact_path_is_a_directory_with_force_exits_2(tmp_path):
    bundle = write_hand_bundle(
        tmp_path / "bundle",
        entries=[entry("ok.py", "full")],
        bodies={"ok.py": "OK = 1\n"})
    out = tmp_path / "out"
    (out / "AGENTS.md").mkdir(parents=True)
    proc = run_gc("convert", str(bundle), "--to", "agents",
                  "-o", str(out), "--force")
    # Previously this raised IsADirectoryError as a traceback (exit 1).
    assert proc.returncode == 2, combined(proc)
    assert "Traceback" not in combined(proc)
    assert (out / "AGENTS.md").is_dir()
