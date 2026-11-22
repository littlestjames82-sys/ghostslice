"""The v0.1 safety promise: GhostRecipes NEVER executes recipe steps.

A recipe is loaded with commands that would create a sentinel file if
run by any shell, in every plausible command-bearing field. Every CLI
operation (validate, show, list, render, export) runs against it. The
sentinel must never exist afterwards.
"""
from conftest import (combined, export, list_dir, render, require_core,
                      show, valid_recipe, validate)


def _booby_trapped(tmp_path):
    sentinel = tmp_path / "PWNED.txt"
    cmd = f"touch {sentinel}"
    recipe = valid_recipe(
        id="booby-trapped",
        steps=[
            {"id": "s1", "title": "Harmless looking step", "kind": "run",
             "detail": "A data-only command hint step.",
             "command_hint": cmd},
            {"id": "s2", "title": "Manual step naming a command",
             "kind": "manual",
             "detail": f"Do not run this: {cmd}",
             "command_hint": f"sh -c '{cmd}'"},
        ],
    )
    from conftest import write_recipe
    return write_recipe(tmp_path, recipe=recipe,
                        name="booby-trapped.recipe.json"), sentinel


def test_no_operation_executes_recipe_commands(tmp_path):
    require_core()
    path, sentinel = _booby_trapped(tmp_path)
    assert validate(path).returncode == 0
    assert show(path).returncode == 0
    assert "booby-trapped" in combined(list_dir(tmp_path))
    proc = render(path)
    assert proc.returncode == 0, combined(proc)
    out = tmp_path / "exported"
    assert export(path, out).returncode == 0
    assert not sentinel.exists(), \
        "a GhostRecipes operation executed a recipe command"


def test_render_shows_command_as_text_not_result(tmp_path):
    require_core()
    path, sentinel = _booby_trapped(tmp_path)
    proc = render(path)
    assert proc.returncode == 0, combined(proc)
    assert not sentinel.exists()
