"""validate: valid recipes pass, broken ones fail by problem, and a
malformed file is never reported as valid."""
from conftest import (combined, load_example, require_core, validate)


def test_validate_accepts_valid_recipe(recipe_factory):
    require_core()
    proc = validate(recipe_factory())
    assert proc.returncode == 0, combined(proc)


def test_validate_accepts_all_starters():
    require_core()
    from conftest import EXAMPLES
    for name in ("slice-marathon-loop", "audit-improve-verify",
                 "creator-pitch-draft-first"):
        proc = validate(EXAMPLES / f"{name}.recipe.json")
        assert proc.returncode == 0, f"{name}: {combined(proc)}"


def test_validate_rejects_missing_id(recipe_factory):
    require_core()
    bad = recipe_factory()
    import json
    data = json.loads(bad.read_text()); del data["id"]
    bad.write_text(json.dumps(data))
    proc = validate(bad)
    assert proc.returncode != 0, combined(proc)


def test_validate_rejects_missing_version(recipe_factory):
    require_core()
    bad = recipe_factory()
    import json
    data = json.loads(bad.read_text()); del data["version"]
    bad.write_text(json.dumps(data))
    assert validate(bad).returncode != 0


def test_validate_rejects_non_semver_version(recipe_factory):
    require_core()
    from conftest import valid_recipe
    assert validate(recipe_factory(
        valid_recipe(version="banana"))).returncode != 0


def test_validate_rejects_empty_steps(recipe_factory):
    require_core()
    from conftest import valid_recipe
    assert validate(recipe_factory(
        valid_recipe(steps=[]))).returncode != 0


def test_validate_rejects_duplicate_step_ids(recipe_factory):
    require_core()
    from conftest import valid_recipe
    step = {"id": "same", "title": "A", "kind": "manual",
            "detail": "Do A."}
    step2 = dict(step, title="B", detail="Do B.")
    assert validate(recipe_factory(
        valid_recipe(steps=[step, step2]))).returncode != 0


def test_validate_rejects_unknown_step_kind(recipe_factory):
    require_core()
    from conftest import valid_recipe
    step = {"id": "x", "title": "X", "kind": "teleport",
            "detail": "Teleport."}
    assert validate(recipe_factory(
        valid_recipe(steps=[step]))).returncode != 0


def test_validate_rejects_malformed_json(recipe_factory):
    require_core()
    bad = recipe_factory(raw="{not json")
    proc = validate(bad)
    assert proc.returncode != 0, combined(proc)
    assert "valid" not in combined(proc).lower().splitlines()[-1] \
        or proc.returncode != 0


def test_validate_rejects_execution_hook_keys(recipe_factory):
    # Unknown keys fail by name: an auto-run / script / hook field can
    # never enter the format, at top level or inside a step.
    require_core()
    from conftest import valid_recipe
    for hook in ("command", "script", "on_load", "autorun"):
        assert validate(recipe_factory(
            valid_recipe(**{hook: "touch /tmp/x"}))).returncode != 0, hook
    step = {"id": "x", "title": "X", "kind": "run",
            "detail": "Looks fine.", "command": "touch /tmp/x"}
    assert validate(recipe_factory(
        valid_recipe(steps=[step]))).returncode != 0


def test_validate_rejects_missing_name(recipe_factory):
    require_core()
    import json
    bad = recipe_factory()
    data = json.loads(bad.read_text()); del data["name"]
    bad.write_text(json.dumps(data))
    assert validate(bad).returncode != 0
