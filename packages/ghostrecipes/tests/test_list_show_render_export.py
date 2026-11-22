"""list / show / render / export / create round trips."""
import json

from conftest import (EXAMPLES, combined, create, export, list_dir,
                      render, require_core, show, valid_recipe, validate,
                      write_recipe)


def test_list_finds_all_starters():
    require_core()
    proc = list_dir(EXAMPLES)
    assert proc.returncode == 0, combined(proc)
    out = combined(proc)
    for rid in ("slice-marathon-loop", "audit-improve-verify",
                "creator-pitch-draft-first"):
        assert rid in out, f"{rid} missing from list output"


def test_show_prints_identity_and_steps():
    require_core()
    proc = show(EXAMPLES / "audit-improve-verify.recipe.json")
    assert proc.returncode == 0, combined(proc)
    out = combined(proc)
    assert "audit-improve-verify" in out
    assert "1.0.0" in out
    assert "Verify with evidence" in out


def test_render_is_a_checklist_in_step_order(tmp_path):
    require_core()
    path = EXAMPLES / "audit-improve-verify.recipe.json"
    out_file = tmp_path / "checklist.md"
    proc = render(path, out=out_file)
    text = out_file.read_text() if out_file.is_file() and \
        out_file.stat().st_size else combined(proc)
    assert proc.returncode == 0, combined(proc)
    assert "- [ ]" in text, f"no checkboxes in render:\n{text}"
    titles = ["Audit the work", "First improvement", "Second improvement",
              "Verify with evidence", "Report plainly"]
    positions = [text.find(t) for t in titles]
    assert all(p >= 0 for p in positions), text
    assert positions == sorted(positions), "checklist out of step order"


def test_export_produces_a_valid_shareable_copy(tmp_path):
    require_core()
    src = EXAMPLES / "slice-marathon-loop.recipe.json"
    out = tmp_path / "exported"
    proc = export(src, out)
    assert proc.returncode == 0, combined(proc)
    candidates = [p for p in out.rglob("*.json")] if out.exists() else []
    assert candidates, f"export produced no json under {out}"
    found = None
    for cand in candidates:
        try:
            data = json.loads(cand.read_text())
        except Exception:
            continue
        if data.get("id") == "slice-marathon-loop":
            found = cand
            break
    assert found is not None, f"no exported recipe json in {candidates}"
    assert validate(found).returncode == 0
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["recipes"] == ["slice-marathon-loop"]
    assert manifest["files"][0]["version"] == "1.0.0"


def test_create_makes_a_valid_skeleton(tmp_path):
    require_core()
    out = tmp_path / "weekly-review.recipe.json"
    proc = create("weekly-review", out)
    assert proc.returncode == 0, combined(proc)
    assert out.exists() or list(tmp_path.rglob("*.json")), \
        "create reported success but produced no file"
    target = out if out.is_file() else next(tmp_path.rglob("*.json"))
    data = json.loads(target.read_text())
    assert data.get("id") == "weekly-review"
    assert data.get("version") == "0.1.0"  # create scaffolds at 0.1.0
    assert validate(target).returncode == 0


def test_list_on_empty_dir_is_ok_not_a_crash(tmp_path):
    require_core()
    empty = tmp_path / "empty"
    empty.mkdir()
    proc = list_dir(empty)
    assert proc.returncode == 0, combined(proc)
    assert "traceback" not in combined(proc).lower()
