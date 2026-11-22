"""Hardening regression tests (Oct 18, 2026 improve pass, lane: harden).

Each test pins a defect found by probing malformed files, bad packs,
type-confused fields, and write-path safety. Before the fixes these
produced raw tracebacks, silent data loss, or (worst) a write through
a symlink to a file outside the library. The data-only rule is
untouched: nothing here executes a recipe step.
"""
import hashlib
import json
import sys
from pathlib import Path

import pytest

from conftest import (combined, require_core, run_ghostrecipes,
                      valid_recipe, validate, write_recipe)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def _import_cli(pack, library, *extra):
    return run_ghostrecipes("import", str(pack), "--library",
                            str(library), *extra)


def _make_pack(tmp_path, recipe=None):
    src = write_recipe(tmp_path / "src",
                       recipe=recipe or valid_recipe(id="one"),
                       name="one.recipe.json")
    out = tmp_path / "pack"
    proc = run_ghostrecipes("export", str(src), "-o", str(out))
    assert proc.returncode == 0, combined(proc)
    return out


# ---- malformed recipe files: clean errors, never tracebacks ----------

def test_validate_invalid_utf8_file_is_a_clean_failure(tmp_path):
    require_core()
    bad = tmp_path / "demo-loop.recipe.json"
    bad.write_bytes(b'{"id": "x\xff\xfe"}')
    proc = validate(bad)
    assert proc.returncode != 0, combined(proc)
    assert "Traceback" not in combined(proc)
    proc = run_ghostrecipes("show", str(bad))
    assert proc.returncode == 2, combined(proc)
    assert "Traceback" not in combined(proc)


def test_validate_accepts_utf8_bom_recipe(recipe_factory):
    require_core()
    path = recipe_factory(
        raw="\ufeff" + json.dumps(valid_recipe()) + "\n")
    proc = validate(path)
    assert proc.returncode == 0, combined(proc)


def test_validate_recipe_missing_file_and_directory_return_errors(
        tmp_path):
    from ghostrecipes.recipe import validate_recipe
    errors, _ = validate_recipe(tmp_path / "nope.recipe.json")
    assert errors
    errors, _ = validate_recipe(tmp_path)
    assert errors


def test_deeply_nested_json_is_a_clean_error(recipe_factory):
    require_core()
    path = recipe_factory(raw="[" * 50000 + "]" * 50000)
    proc = validate(path)
    assert proc.returncode != 0, combined(proc)
    assert "Traceback" not in combined(proc)


def test_duplicate_json_keys_are_rejected(recipe_factory):
    require_core()
    raw = ('{"id": "first-id", "id": "demo-loop", "name": "Demo", '
           '"version": "1.0.0", "description": "d", "steps": '
           '[{"id": "s", "title": "S", "kind": "manual"}]}')
    proc = validate(recipe_factory(raw=raw))
    assert proc.returncode != 0, combined(proc)
    assert "duplicate" in combined(proc)


def test_nonstandard_json_constant_is_rejected():
    from ghostrecipes.recipe import GhostRecipesError, extract_recipe_data
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "x.recipe.json"
        p.write_text('{"id": "x", "name": "X", "version": "1.0.0", '
                     '"description": "d", "steps": [{"id": "s", '
                     '"title": "t", "kind": "manual"}], '
                     '"notes": NaN}')
        with pytest.raises(GhostRecipesError) as excinfo:
            extract_recipe_data(p)
        assert "invalid JSON" in str(excinfo.value)


# ---- validator strictness ---------------------------------------------

def test_validate_rejects_non_string_input_description(recipe_factory):
    require_core()
    recipe = valid_recipe(inputs=[{
        "name": "target", "description": 123, "required": True}])
    proc = validate(recipe_factory(recipe))
    assert proc.returncode != 0, combined(proc)
    assert "description must be a string" in combined(proc)


def test_validate_warns_for_md_filename_id_mismatch(tmp_path):
    require_core()
    path = tmp_path / "wrong-name.recipe.md"
    path.write_text("# Notes\n\n```json\n"
                    + json.dumps(valid_recipe()) + "\n```\n")
    proc = validate(path)
    assert proc.returncode == 0, combined(proc)
    assert "does not match" in combined(proc)


# ---- show / list survive type-confused recipes -------------------------

def test_show_and_list_report_errors_instead_of_crashing(tmp_path):
    require_core()
    recipe = valid_recipe(tags=[123], inputs=["oops"])
    path = write_recipe(tmp_path, recipe=recipe)
    proc = run_ghostrecipes("show", str(path))
    assert proc.returncode == 1, combined(proc)
    assert "Traceback" not in combined(proc)
    assert "error:" in combined(proc)
    proc = run_ghostrecipes("list", "--library", str(tmp_path))
    assert proc.returncode == 0, combined(proc)
    assert "Traceback" not in combined(proc)
    assert "demo-loop" in combined(proc)


# ---- pack import: manifest robustness ----------------------------------

def test_import_rejects_non_object_manifest(tmp_path):
    require_core()
    pack = _make_pack(tmp_path)
    (pack / "manifest.json").write_text('["not", "an", "object"]')
    library = tmp_path / "library"
    proc = _import_cli(pack, library)
    assert proc.returncode == 2, combined(proc)
    assert "Traceback" not in combined(proc)
    assert not library.exists() or not list(library.rglob("*"))


def test_import_rejects_invalid_utf8_manifest(tmp_path):
    require_core()
    pack = _make_pack(tmp_path)
    (pack / "manifest.json").write_bytes(b"\xff\xfe{}")
    proc = _import_cli(pack, tmp_path / "library")
    assert proc.returncode == 2, combined(proc)
    assert "Traceback" not in combined(proc)


def test_import_rejects_manifest_with_nonstandard_constant(tmp_path):
    require_core()
    pack = _make_pack(tmp_path)
    manifest = json.loads((pack / "manifest.json").read_text())
    manifest["extra"] = float("nan")  # json.dumps writes a bare NaN
    (pack / "manifest.json").write_text(json.dumps(manifest))
    proc = _import_cli(pack, tmp_path / "library")
    assert proc.returncode == 2, combined(proc)
    assert "Traceback" not in combined(proc)


def test_import_accepts_bom_manifest(tmp_path):
    require_core()
    pack = _make_pack(tmp_path)
    raw = (pack / "manifest.json").read_bytes()
    (pack / "manifest.json").write_bytes(b"\xef\xbb\xbf" + raw)
    proc = _import_cli(pack, tmp_path / "library")
    assert proc.returncode == 0, combined(proc)


def test_import_rejects_non_recipe_entry_name(tmp_path):
    require_core()
    pack = tmp_path / "pack"
    pack.mkdir()
    content = (json.dumps(valid_recipe()) + "\n").encode()
    (pack / "data.json").write_bytes(content)
    manifest = {
        "format": "ghostrecipes-pack", "ghostrecipes": "0.1.0",
        "recipes": ["demo-loop"],
        "files": [{"path": "data.json",
                   "sha256": hashlib.sha256(content).hexdigest(),
                   "recipe_id": "demo-loop", "version": "1.0.0"}]}
    (pack / "manifest.json").write_text(json.dumps(manifest))
    library = tmp_path / "library"
    proc = _import_cli(pack, library)
    assert proc.returncode != 0, combined(proc)
    assert not library.exists() or not list(library.rglob("*"))


# ---- pack writes never follow symlinks ---------------------------------

def test_import_force_never_writes_through_symlink(tmp_path):
    require_core()
    src = write_recipe(tmp_path / "src")
    pack = tmp_path / "pack"
    proc = run_ghostrecipes("export", str(src), "-o", str(pack))
    assert proc.returncode == 0, combined(proc)
    library = tmp_path / "library"
    library.mkdir()
    victim = tmp_path / "victim.txt"
    victim.write_text("IMPORTANT")
    (library / "demo-loop.recipe.json").symlink_to(victim)
    proc = _import_cli(pack, library, "--force")
    assert proc.returncode != 0, combined(proc)
    assert victim.read_text() == "IMPORTANT"


def test_import_refuses_dangling_symlink_destination(tmp_path):
    require_core()
    src = write_recipe(tmp_path / "src")
    pack = tmp_path / "pack"
    proc = run_ghostrecipes("export", str(src), "-o", str(pack))
    assert proc.returncode == 0, combined(proc)
    library = tmp_path / "library"
    library.mkdir()
    target = tmp_path / "created-by-import.txt"
    (library / "demo-loop.recipe.json").symlink_to(target)
    proc = _import_cli(pack, library)
    assert proc.returncode != 0, combined(proc)
    assert not target.exists()


def test_export_refuses_symlinked_destination(tmp_path):
    require_core()
    src = write_recipe(tmp_path / "src")
    out = tmp_path / "out"
    out.mkdir()
    victim = tmp_path / "victim.txt"
    victim.write_text("IMPORTANT")
    (out / "demo-loop.recipe.json").symlink_to(victim)
    proc = run_ghostrecipes("export", str(src), "-o", str(out),
                            "--force")
    assert proc.returncode != 0, combined(proc)
    assert victim.read_text() == "IMPORTANT"


# ---- CLI surface: filesystem errors and create parsing -----------------

def test_render_output_under_a_file_is_a_clean_error(tmp_path):
    require_core()
    path = write_recipe(tmp_path)
    a_file = tmp_path / "afile"
    a_file.write_text("x")
    proc = run_ghostrecipes("render", str(path), "-o",
                            str(a_file / "out.md"))
    assert proc.returncode == 2, combined(proc)
    assert "Traceback" not in combined(proc)


def test_create_ignores_empty_step_segments(tmp_path):
    require_core()
    out = tmp_path / "seg.recipe.json"
    proc = run_ghostrecipes(
        "create", "--id", "seg-test", "--name", "Seg",
        "--steps", "Setup;; Verify ;", "-o", str(out))
    assert proc.returncode == 0, combined(proc)
    data = json.loads(out.read_text())
    assert [s["title"] for s in data["steps"]] == ["Setup", "Verify"]
    assert validate(out).returncode == 0
