"""Polish round regression tests (Oct 14, 2026).

Every test here pins a demonstrated audit finding from POLISH.md.
Run against the real CLI the same way as the rest of the suite.
"""
import json
import sys
from pathlib import Path

from conftest import (EXAMPLES, combined, export, list_dir, load_example,
                      render, require_core, run_ghostrecipes, valid_recipe,
                      validate, write_recipe)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def _import_cli(pack, library):
    return run_ghostrecipes("import", str(pack), "--library", str(library))


def _make_pack(tmp_path, recipe=None):
    src = write_recipe(tmp_path, recipe=recipe or valid_recipe(id="one"),
                       name="one.recipe.json")
    out = tmp_path / "pack"
    assert export(src, out).returncode == 0
    return out


# ---- Pass 1: list --json is real JSON --------------------------------

def test_list_json_stdout_is_parseable_json(tmp_path):
    require_core()
    write_recipe(tmp_path / "lib")
    proc = run_ghostrecipes("list", "--library", str(tmp_path / "lib"),
                            "--json")
    assert proc.returncode == 0, combined(proc)
    rows = json.loads(proc.stdout)  # header must not pollute stdout
    assert any(r.get("id") == "demo-loop" for r in rows)


def test_list_text_mode_still_shows_library_header(tmp_path):
    require_core()
    proc = list_dir(tmp_path)
    assert proc.returncode == 0
    assert "library:" in proc.stdout


# ---- Pass 1: library discovery dedupes by resolved path --------------

def test_same_library_spelled_two_ways_lists_each_recipe_once(tmp_path):
    require_core()
    proj = tmp_path / "proj"
    (proj / "recipes").mkdir(parents=True)
    write_recipe(proj / "recipes")
    proc = run_ghostrecipes("list", "--library", "recipes", cwd=proj)
    assert proc.returncode == 0, combined(proc)
    hits = [l for l in proc.stdout.splitlines() if "demo-loop" in l]
    assert len(hits) == 1, proc.stdout


# ---- Pass 1: import pack safety ---------------------------------------

def test_import_rejects_stray_executable_shebang_txt(tmp_path):
    require_core()
    pack = _make_pack(tmp_path)
    evil = pack / "notes.txt"
    evil.write_text("#!/bin/sh\ntouch SHOULD_NOT_EXIST\n")
    evil.chmod(0o755)
    library = tmp_path / "library"
    proc = _import_cli(pack, library)
    assert proc.returncode != 0, combined(proc)
    assert not list(library.rglob("*.recipe.json")) if library.exists() \
        else True


def test_import_rejects_duplicate_manifest_entries(tmp_path):
    require_core()
    pack = _make_pack(tmp_path)
    manifest = json.loads((pack / "manifest.json").read_text())
    manifest["files"] = manifest["files"] * 2
    (pack / "manifest.json").write_text(json.dumps(manifest))
    proc = _import_cli(pack, tmp_path / "library")
    assert proc.returncode != 0, combined(proc)
    assert "duplicate" in combined(proc).lower()


def test_import_reports_verified_ids_not_manifest_claim(tmp_path):
    require_core()
    from ghostrecipes.packio import import_pack
    pack = _make_pack(tmp_path)
    manifest = json.loads((pack / "manifest.json").read_text())
    manifest["recipes"] = ["totally-different"]
    (pack / "manifest.json").write_text(json.dumps(manifest))
    result = import_pack(pack, tmp_path / "library")
    assert result["recipes"] == ["one"]


def test_export_to_a_file_path_is_a_clean_error(tmp_path):
    require_core()
    src = write_recipe(tmp_path)
    a_file = tmp_path / "afile"
    a_file.write_text("x")
    proc = export(src, a_file)
    assert proc.returncode == 2, combined(proc)
    assert "traceback" not in combined(proc).lower()


# ---- Pass 1: validator strictness -------------------------------------

def test_validate_rejects_impossible_calendar_date(recipe_factory):
    require_core()
    path = recipe_factory(valid_recipe(date="2026-13-99"))
    proc = validate(path)
    assert proc.returncode != 0, combined(proc)
    assert "calendar" in combined(proc)


def test_validate_accepts_a_real_date(recipe_factory):
    require_core()
    path = recipe_factory(valid_recipe(date="2026-10-14"))
    assert validate(path).returncode == 0


def test_validate_rejects_whitespace_only_name(recipe_factory):
    require_core()
    path = recipe_factory(valid_recipe(name="   "))
    assert validate(path).returncode != 0


def test_validate_warns_for_placeholder_in_notes(recipe_factory):
    require_core()
    recipe = valid_recipe()
    recipe["notes"] = "Remember {{undeclared_note}}."
    proc = validate(recipe_factory(recipe))
    assert proc.returncode == 0, combined(proc)
    assert "undeclared_note" in combined(proc)


def test_validate_warns_for_malformed_placeholder(recipe_factory):
    require_core()
    recipe = valid_recipe(
        description="Do {{1bad}} on {{target}}.")
    proc = validate(recipe_factory(recipe))
    assert proc.returncode == 0, combined(proc)
    assert "malformed placeholder" in combined(proc)
    assert "1bad" in combined(proc)


# ---- Pass 2: render clarity -------------------------------------------

def test_render_escapes_pipes_in_inputs_table(recipe_factory):
    require_core()
    recipe = valid_recipe(inputs=[{
        "name": "target", "description": "A | B choice.",
        "required": True, "default": "a|b"}])
    proc = render(recipe_factory(recipe))
    assert proc.returncode == 0, combined(proc)
    row = [l for l in proc.stdout.splitlines() if l.startswith("| target")]
    assert row and "a\\|b" in row[0], proc.stdout


def test_render_marks_required_input_not_provided(recipe_factory):
    require_core()
    proc = render(recipe_factory())
    assert proc.returncode == 0, combined(proc)
    row = [l for l in proc.stdout.splitlines() if l.startswith("| target")]
    assert row and "(not provided)" in row[0], proc.stdout


def test_render_hint_backticks_cannot_close_the_fence(recipe_factory):
    require_core()
    step = {"id": "s", "title": "S", "kind": "run",
            "detail": "Look.", "command_hint": "echo hi\n```\nINSIDE\n```"}
    proc = render(recipe_factory(valid_recipe(steps=[step])))
    assert proc.returncode == 0, combined(proc)
    assert "````text" in proc.stdout, proc.stdout
    assert "\n    INSIDE\n" in proc.stdout


def test_render_indents_multiline_detail(recipe_factory):
    require_core()
    step = {"id": "s", "title": "S", "kind": "manual",
            "detail": "first line\nsecond line"}
    proc = render(recipe_factory(valid_recipe(steps=[step])))
    assert proc.returncode == 0, combined(proc)
    assert "\n    second line" in proc.stdout, proc.stdout


# ---- Pass 2: starter quality ------------------------------------------

def test_marathon_loop_includes_push_and_release_after_verify():
    steps = [s["id"] for s in load_example("slice-marathon-loop")["steps"]]
    assert steps.index("push") > steps.index("verify")
    assert steps.index("release") > steps.index("push")
    release = load_example("slice-marathon-loop")["steps"][-1]
    assert release["kind"] == "approve"
    assert "separate approval" in release["gate"].lower()
