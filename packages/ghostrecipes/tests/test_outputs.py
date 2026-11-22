"""Declared outputs: a recipe may name what a follower should end up
holding (name, whether it is required, which step produces it).

Outputs are data only, like everything else in the format: declaring
one never creates it, and an output may not carry an execution-style
key. These tests pin the validation, the placeholder scan, the
rendered Outputs table, show output, and the pack round trip.
"""
import json
import sys
from pathlib import Path

from conftest import (combined, export, render, require_core, show,
                      valid_recipe, validate, write_recipe)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ghostrecipes.recipe import validate_data  # noqa: E402
from ghostrecipes.render import render_recipe  # noqa: E402
from ghostrecipes.recipe import Recipe  # noqa: E402


def _with_outputs(**overrides):
    recipe = valid_recipe()
    recipe["outputs"] = [{
        "name": "checked-result",
        "description": "The checked result for {{target}}.",
        "required": True,
        "from_step": "check",
    }]
    recipe.update(overrides)
    return recipe


# ---- validation: happy path ------------------------------------------

def test_validate_accepts_declared_outputs(recipe_factory):
    require_core()
    proc = validate(recipe_factory(_with_outputs()))
    assert proc.returncode == 0, combined(proc)


def test_validate_accepts_recipe_without_outputs(recipe_factory):
    require_core()
    proc = validate(recipe_factory())
    assert proc.returncode == 0, combined(proc)
    assert "outputs" not in combined(proc).lower()


def test_validate_accepts_empty_outputs_list(recipe_factory):
    require_core()
    assert validate(recipe_factory(
        _with_outputs(outputs=[]))).returncode == 0


def test_validate_data_accepts_minimal_output():
    errors, warnings = validate_data(_with_outputs(
        outputs=[{"name": "report"}]))
    assert errors == [], errors


# ---- validation: shape and strictness --------------------------------

def test_validate_rejects_non_list_outputs():
    errors, _ = validate_data(_with_outputs(outputs="report"))
    assert any("outputs must be a list" in e for e in errors), errors


def test_validate_rejects_non_object_output():
    errors, _ = validate_data(_with_outputs(outputs=["report"]))
    assert any("outputs[0] must be an object" in e for e in errors), errors


def test_validate_rejects_duplicate_output_names():
    errors, _ = validate_data(_with_outputs(outputs=[
        {"name": "report"}, {"name": "report"}]))
    assert any("duplicate output name" in e for e in errors), errors


def test_validate_rejects_invalid_output_name():
    for bad in ("Has Spaces", "", "UPPER", "-leading-dash"):
        errors, _ = validate_data(_with_outputs(outputs=[{"name": bad}]))
        assert any("name must be a slug" in e for e in errors), (bad, errors)


def test_validate_rejects_missing_output_name():
    errors, _ = validate_data(_with_outputs(
        outputs=[{"description": "No name here."}]))
    assert any("name must be a slug" in e for e in errors), errors


def test_validate_rejects_unknown_output_key_by_name():
    # Execution-style keys stay out of the format at this level too.
    for hook in ("command", "script", "path", "on_load"):
        errors, _ = validate_data(_with_outputs(outputs=[
            {"name": "report", hook: "touch /tmp/x"}]))
        assert any(f"unknown key {hook!r}" in e for e in errors), (hook, errors)


def test_validate_rejects_non_string_description_and_non_bool_required():
    errors, _ = validate_data(_with_outputs(outputs=[
        {"name": "report", "description": 3, "required": "yes"}]))
    assert any("description must be a string" in e for e in errors), errors
    assert any("required must be true or false" in e for e in errors), errors


def test_validate_rejects_dangling_from_step():
    errors, _ = validate_data(_with_outputs(outputs=[
        {"name": "report", "from_step": "no-such-step"}]))
    assert any("does not match any step id" in e for e in errors), errors


def test_validate_rejects_non_string_from_step():
    errors, _ = validate_data(_with_outputs(outputs=[
        {"name": "report", "from_step": 2}]))
    assert any("from_step must be a string" in e for e in errors), errors


def test_cli_validate_fails_on_dangling_from_step(recipe_factory):
    require_core()
    recipe = _with_outputs(outputs=[
        {"name": "report", "from_step": "ghost-step"}])
    proc = validate(recipe_factory(recipe))
    assert proc.returncode != 0, combined(proc)
    assert "ghost-step" in combined(proc)


# ---- placeholder scan covers output descriptions ---------------------

def test_placeholder_in_output_description_counts_as_input_use():
    # target is used in the description already by valid_recipe, so
    # use a recipe whose only use of an input is in an output.
    recipe = valid_recipe(description="A plain description.")
    recipe["steps"] = [{"id": "look", "title": "Look", "kind": "manual",
                        "detail": "Read it in full."}]
    recipe["notes"] = "Done."
    recipe["outputs"] = [{"name": "report",
                          "description": "Report on {{target}}."}]
    errors, warnings = validate_data(recipe)
    assert errors == [], errors
    assert not any("never used" in w for w in warnings), warnings


def test_undeclared_placeholder_in_output_description_warns(recipe_factory):
    require_core()
    recipe = _with_outputs(outputs=[
        {"name": "report", "description": "Report on {{mystery}}."}])
    proc = validate(recipe_factory(recipe))
    assert proc.returncode == 0, combined(proc)
    assert "mystery" in combined(proc)


# ---- rendering ---------------------------------------------------------

def test_render_shows_outputs_table_after_steps(recipe_factory):
    require_core()
    proc = render(recipe_factory(_with_outputs()))
    assert proc.returncode == 0, combined(proc)
    out = proc.stdout
    assert "## Outputs" in out
    assert out.index("## Outputs") > out.index("## Steps")
    row = [l for l in out.splitlines() if l.startswith("| checked-result")]
    assert row and "| yes |" in row[0] and "check" in row[0], out
    # The description placeholder is filled from the input default path:
    # target has no default and no --var here, so it stays visible and
    # is listed as unresolved instead of being guessed.
    assert "## Unresolved placeholders" in out
    assert "{{target}}" in out


def test_render_substitutes_output_description(tmp_path):
    recipe = Recipe(_with_outputs())
    text = render_recipe(recipe, {"target": "the parser"})
    assert "The checked result for the parser." in text
    assert "## Unresolved placeholders" not in text


def test_render_escapes_pipes_in_output_description():
    recipe = _with_outputs(outputs=[{
        "name": "report", "description": "Pick a|b for {{target}}.",
        "required": False}])
    text = render_recipe(Recipe(recipe), {"target": "x"})
    row = [l for l in text.splitlines() if l.startswith("| report")]
    assert row and "a\\|b" in row[0], text


def test_render_without_outputs_has_no_outputs_section(recipe_factory):
    require_core()
    proc = render(recipe_factory())
    assert proc.returncode == 0, combined(proc)
    assert "## Outputs" not in proc.stdout


def test_render_optional_output_without_from_step_shows_dash():
    text = render_recipe(Recipe(_with_outputs(
        outputs=[{"name": "notes-copy", "description": "A copy."}])))
    row = [l for l in text.splitlines() if l.startswith("| notes-copy")]
    assert row and "| no |" in row[0] and "| - |" in row[0], text


# ---- show and pack round trip -----------------------------------------

def test_show_prints_outputs(recipe_factory):
    require_core()
    proc = show(recipe_factory(_with_outputs()))
    assert proc.returncode == 0, combined(proc)
    out = combined(proc)
    assert "outputs:" in out
    assert "checked-result" in out
    assert "from step: check" in out


def test_export_import_round_trip_preserves_outputs(tmp_path):
    require_core()
    src = write_recipe(tmp_path, recipe=_with_outputs())
    out = tmp_path / "pack"
    assert export(src, out).returncode == 0
    from conftest import run_ghostrecipes
    proc = run_ghostrecipes("import", str(out),
                            "--library", str(tmp_path / "lib"))
    assert proc.returncode == 0, combined(proc)
    imported = tmp_path / "lib" / "demo-loop.recipe.json"
    data = json.loads(imported.read_text())
    assert data["outputs"][0]["name"] == "checked-result"
    assert data["outputs"][0]["from_step"] == "check"
    assert validate(imported).returncode == 0
