"""Polish regression tests for GhostDeps v0.1.

These tests pin three audit findings from the documented limits:
comment markers inside JS strings must not erase real imports, local
ignore rules must filter the import scan without hiding manifests, and
nested manifests must be grouped by holding directory in the pack.
"""
from __future__ import annotations

import json
from pathlib import Path

from conftest import combined, needs_cli, run_pack
from helpers import banned_hits, section_bodies


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _manifest(found) -> dict:
    assert found is not None, "pack produced no DEPS.md + deps-manifest.json"
    return json.loads(found[1].read_text())


def _names(entries) -> set[str]:
    return {entry["name"].lower() for entry in entries}


@needs_cli
def test_js_comment_markers_inside_strings_do_not_erase_imports(
        tmp_path):
    project = tmp_path / "lexical"
    _write(project / "package.json", json.dumps({
        "name": "lexical-fixture",
        "dependencies": {
            "express": "^4.18.2",
            "chalk": "^5.0.0",
            "lodash": "^4.17.21",
            "react": "^18.2.0",
            "vue": "^3.4.0",
            "pinia": "^2.1.0",
        },
    }))
    _write(project / "index.js", """\
const marker = "// not a comment"; const axios = require('axios');
// const phantom = require('phantom');
const banner = `/* still text */ ${require('chalk')}`;
const message = `prefix // still text ${require('react')}`;
const slashes = /https?:\\/\\//g; const vue = require('vue');
const quotient = total / count; const pinia = require('pinia');
import express from 'express';
import lodash from 'lodash';
/* const blocked = require('blocked'); */
""")

    proc, found = run_pack(project, tmp_path / "out")
    assert proc.returncode == 1, combined(proc)
    data = _manifest(found)
    sections = data["sections"]

    assert _names(sections["imported_not_declared"]) == {"axios"}
    assert sections["imported_not_declared"][0]["imported_in"] == [
        "index.js"]
    assert {"express", "chalk", "lodash", "react", "vue", "pinia"} <= \
        _names(sections["declared_and_used"])

    deps_text = found[0].read_text()
    bodies = section_bodies(deps_text)
    assert "phantom" not in bodies["imported_not_declared"].lower()
    assert "blocked" not in bodies["imported_not_declared"].lower()
    assert banned_hits(deps_text, found[1].read_text(), combined(proc)) == []


@needs_cli
def test_import_scan_honors_ignore_rules_without_hiding_manifests(
        tmp_path):
    project = tmp_path / "ignored"
    _write(project / "package.json", json.dumps({
        "name": "ignore-fixture",
        "dependencies": {"express": "^4.18.2"},
    }))
    _write(project / ".gitignore", "generated/**\n!generated/keep.js\n")
    _write(project / ".ghostslice.json",
           json.dumps({"ignore": ["fixtures/**"]}))
    _write(project / "src" / "index.js",
           "const express = require('express');\n")
    _write(project / "generated" / "skip.js",
           "const phantom = require('phantom');\n")
    _write(project / "generated" / "keep.js",
           "const axios = require('axios');\n")
    _write(project / "fixtures" / "hidden.js",
           "const ghostpkg = require('ghostpkg');\n")
    _write(project / "fixtures" / "package.json", json.dumps({
        "name": "fixture-only",
        "dependencies": {"fixture-only": "1.0.0"},
    }))
    _write(project / "packages" / ".gitignore", "demo/**\n")
    _write(project / "packages" / "demo" / "skip.ts",
           "import nestedPhantom from 'nested-phantom';\n")

    proc, found = run_pack(project, tmp_path / "out")
    assert proc.returncode == 1, combined(proc)
    data = _manifest(found)

    assert data["import_scan"]["ignored_files"] == [
        "fixtures/hidden.js",
        "generated/skip.js",
        "packages/demo/skip.ts",
    ]
    assert data["import_scan"]["ignore_sources"] == [
        ".gitignore",
        "packages/.gitignore",
        ".ghostslice.json",
    ]
    assert data["files_scanned"]["javascript"] == 2
    assert _names(data["sections"]["imported_not_declared"]) == {"axios"}
    assert data["sections"]["imported_not_declared"][0]["imported_in"] == [
        "generated/keep.js"]

    # Ignore rules apply to import scanning only. Manifest discovery
    # still records the nested manifest as local evidence.
    assert "fixtures/package.json" in {
        source["file"] for source in data["sources"]}


@needs_cli
def test_gitignore_single_star_does_not_cross_directories(tmp_path):
    project = tmp_path / "segment-glob"
    _write(project / "package.json", json.dumps({
        "name": "segment-glob-fixture",
        "dependencies": {"express": "^4.18.2"},
    }))
    _write(project / ".gitignore", "src/*.js\n")
    _write(project / "index.js", "const express = require('express');\n")
    _write(project / "src" / "app.js",
           "const axios = require('axios');\n")
    _write(project / "src" / "nested" / "app.js",
           "const vue = require('vue');\n")

    proc, found = run_pack(project, tmp_path / "out")
    assert proc.returncode == 1, combined(proc)
    data = _manifest(found)
    assert data["import_scan"]["ignored_files"] == ["src/app.js"]
    assert _names(data["sections"]["imported_not_declared"]) == {"vue"}


@needs_cli
def test_malformed_ghostslice_profile_does_not_change_scan_results(
        tmp_path):
    project = tmp_path / "bad-profile"
    _write(project / "package.json", json.dumps({
        "name": "bad-profile-fixture",
        "dependencies": {"express": "^4.18.2"},
    }))
    _write(project / ".ghostslice.json", "{not json")
    _write(project / "index.js", """\
const express = require('express');
const axios = require('axios');
""")

    proc, found = run_pack(project, tmp_path / "out")
    assert proc.returncode == 1, combined(proc)
    data = _manifest(found)
    assert _names(data["sections"]["imported_not_declared"]) == {"axios"}
    assert data["import_scan"]["warnings"]
    assert ".ghostslice.json" in data["import_scan"]["warnings"][0]


@needs_cli
def test_nested_manifests_are_grouped_by_holding_directory(tmp_path):
    project = tmp_path / "nested"
    _write(project / "package.json", json.dumps({
        "name": "root-fixture",
        "dependencies": {"express": "^4.18.2"},
    }))
    _write(project / "index.js", "const express = require('express');\n")
    _write(project / "packages" / "api" / "package.json", json.dumps({
        "name": "api-fixture",
        "dependencies": {"lodash": "^4.17.21"},
    }))
    _write(project / "packages" / "api" / "index.js",
           "const lodash = require('lodash');\n")
    _write(project / "examples" / "demo" / "package.json", json.dumps({
        "name": "demo-fixture",
        "dependencies": {"chalk": "^5.0.0"},
    }))
    _write(project / "examples" / "demo" / "index.js",
           "const chalk = require('chalk');\n")

    proc, found = run_pack(project, tmp_path / "out")
    assert proc.returncode == 0, combined(proc)
    data = _manifest(found)
    groups = {group["directory"]: group
              for group in data["source_groups"]}

    assert set(groups) == {".", "packages/api", "examples/demo"}
    for directory, filename in (
            (".", "package.json"),
            ("packages/api", "packages/api/package.json"),
            ("examples/demo", "examples/demo/package.json")):
        assert groups[directory]["source_count"] == 1
        assert groups[directory]["files"] == [filename]
        assert groups[directory]["status_counts"] == {"parsed": 1}

    deps_text = found[0].read_text()
    assert "Manifest locations: 3" in deps_text
    assert "`packages/api`" in deps_text
    assert "`examples/demo`" in deps_text
    assert {"express", "lodash", "chalk"} <= _names(
        data["sections"]["declared_and_used"])
