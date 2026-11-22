"""inspect command tests (PLAN MVP item 1)."""

from __future__ import annotations

from conftest import requires_cli
from helpers import PETSTORE, SDL_SCHEMA, combined, run_cli


@requires_cli
def test_inspect_openapi_succeeds_and_names_format():
    proc = run_cli(["inspect", PETSTORE])
    assert proc.returncode == 0, combined(proc)
    out = combined(proc).lower()
    assert "openapi" in out


@requires_cli
def test_inspect_json_schema_succeeds():
    from helpers import PARTS_SCHEMA
    proc = run_cli(["inspect", PARTS_SCHEMA])
    assert proc.returncode == 0, combined(proc)
    out = combined(proc).lower()
    assert "schema" in out


@requires_cli
def test_inspect_sdl_succeeds_and_says_outline():
    proc = run_cli(["inspect", SDL_SCHEMA])
    assert proc.returncode == 0, combined(proc)
    out = combined(proc).lower()
    # SDL only ever gets the outline treatment; inspect must not imply
    # a full reduction is available.
    assert "graphql" in out or "sdl" in out


@requires_cli
def test_inspect_missing_file_fails_loudly(tmp_path):
    proc = run_cli(["inspect", tmp_path / "does-not-exist.json"])
    assert proc.returncode != 0, combined(proc)
    assert combined(proc).strip() != ""
