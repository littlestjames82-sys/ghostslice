"""Pytest glue: CLI availability gate + small shared fixtures."""

from __future__ import annotations

import pytest

from helpers import cli_available, sha256_of

requires_cli = pytest.mark.skipif(
    not cli_available(),
    reason="GhostSchema CLI not discoverable yet (GHOSTSCHEMA_CMD, PATH, "
           "or python -m ghostschema with PYTHONPATH=src); fixture tests "
           "still validate the planted fixtures",
)


@pytest.fixture
def fixture_hashes():
    """Snapshot hashes of files; the returned dict can be re-checked."""
    from helpers import (PARTS_SCHEMA, PETSTORE, SDL_SCHEMA, SWAGGER2,
                         YAML_IN_JSON, YAML_SPEC)
    paths = [PETSTORE, PARTS_SCHEMA, SDL_SCHEMA, YAML_SPEC, YAML_IN_JSON,
             SWAGGER2]
    return {p: sha256_of(p) for p in paths}


def assert_hashes_unchanged(snapshot):
    for path, digest in snapshot.items():
        assert sha256_of(path) == digest, f"input file was modified: {path}"
