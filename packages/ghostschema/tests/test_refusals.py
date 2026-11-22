"""Refusal tests: YAML (by extension and by content) and Swagger 2.0.

PLAN rules: YAML is refused with a clear message, exit 2, stdlib has
no YAML parser and v0.1 does not fake one. Swagger 2.0 is refused with
a clear message pointing at 3.x. Refusals never modify the input.
"""

from __future__ import annotations

from conftest import assert_hashes_unchanged, requires_cli
from helpers import (SWAGGER2, YAML_IN_JSON, YAML_SPEC, combined, run_cli)


@requires_cli
def test_yaml_extension_refused_exit2(tmp_path):
    out = tmp_path / "bundle"
    proc = run_cli(["slice", YAML_SPEC, "--all", "-o", out])
    assert proc.returncode == 2, combined(proc)
    assert "yaml" in combined(proc).lower(), combined(proc)


@requires_cli
def test_yaml_content_in_json_file_refused_exit2(tmp_path):
    out = tmp_path / "bundle"
    proc = run_cli(["slice", YAML_IN_JSON, "--all", "-o", out])
    assert proc.returncode == 2, combined(proc)
    assert "yaml" in combined(proc).lower(), combined(proc)


@requires_cli
def test_yaml_refused_on_inspect_too():
    proc = run_cli(["inspect", YAML_SPEC])
    assert proc.returncode == 2, combined(proc)
    assert "yaml" in combined(proc).lower(), combined(proc)


@requires_cli
def test_swagger2_refused_exit2(tmp_path):
    out = tmp_path / "bundle"
    proc = run_cli(["slice", SWAGGER2, "--all", "-o", out])
    assert proc.returncode == 2, combined(proc)
    text = combined(proc).lower()
    assert "swagger" in text or "2.0" in text, combined(proc)


@requires_cli
def test_refusals_leave_inputs_byte_identical(tmp_path, fixture_hashes):
    for target in (YAML_SPEC, YAML_IN_JSON, SWAGGER2):
        out = tmp_path / f"out-{target.stem}"
        run_cli(["slice", target, "--all", "-o", out])
    assert_hashes_unchanged(fixture_hashes)
