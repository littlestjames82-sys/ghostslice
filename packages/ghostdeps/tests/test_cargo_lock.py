"""Cargo.lock summary parsing: Rust pins as recorded.

Before this capability a Rust project contributed no pins at all:
Cargo.toml records version requirements (caret semantics), not pins,
and Cargo.lock was listed as detected-not-parsed. These tests pin the
summary contract: direct pins are the dependencies of the local
(source-less) package(s), every other recorded package is a
transitive pin recorded compactly, the local package itself is never
a pin, and unrecognised or malformed lockfiles degrade to a reported
status instead of a guess or a crash. Evidence only, local only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from conftest import combined, needs_cli, run_ghostdeps, run_pack
from helpers import banned_hits, section_bodies

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ghostdeps.manifests import _parse_cargo_lock  # noqa: E402


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


_CARGO_TOML = """\
[package]
name = "fixture-rust"
version = "0.1.0"
edition = "2021"

[dependencies]
serde = "1.0"
log = "0.4"
"""

_MAIN_RS = """\
use log::info;
use serde::Serialize;

fn main() {
    info!("hello");
    let _ = Serialize::default();
}
"""

# Direct: serde, log (listed by the local package).
# Transitive: serde_derive, proc-macro2, quote, syn, unicode-ident.
# The serde entry exercises the long dependency-string shape
# ("name version (source)") for its own dependency, and the local
# package's entries exercise both the bare-name and the
# "name version (source)" shapes for the direct split.
_CARGO_LOCK = """\
version = 3

[[package]]
name = "fixture-rust"
version = "0.1.0"
dependencies = [
    "log",
    "serde 1.0.197 (registry+https://github.com/rust-lang/crates.io-index)",
]

[[package]]
name = "log"
version = "0.4.21"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "fixture-checksum-log-must-not-be-reproduced"

[[package]]
name = "serde"
version = "1.0.197"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "fixture-checksum-serde-must-not-be-reproduced"
dependencies = [
    "serde_derive",
]

[[package]]
name = "serde_derive"
version = "1.0.197"
source = "registry+https://github.com/rust-lang/crates.io-index"
checksum = "fixture-checksum-derive-must-not-be-reproduced"
dependencies = [
    "proc-macro2",
    "quote",
    "syn",
]

[[package]]
name = "proc-macro2"
version = "1.0.79"
source = "registry+https://github.com/rust-lang/crates.io-index"
dependencies = [
    "unicode-ident",
]

[[package]]
name = "quote"
version = "1.0.35"
source = "registry+https://github.com/rust-lang/crates.io-index"
dependencies = [
    "proc-macro2",
]

[[package]]
name = "syn"
version = "2.0.52"
source = "registry+https://github.com/rust-lang/crates.io-index"
dependencies = [
    "proc-macro2",
    "quote",
    "unicode-ident",
]

[[package]]
name = "unicode-ident"
version = "1.0.12"
source = "registry+https://github.com/rust-lang/crates.io-index"
"""


def _rust_project(root: Path, lock_text: str = _CARGO_LOCK) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    _write(root / "Cargo.toml", _CARGO_TOML)
    _write(root / "src" / "main.rs", _MAIN_RS)
    if lock_text is not None:
        _write(root / "Cargo.lock", lock_text)
    return root


def _manifest(found) -> dict:
    assert found is not None, "pack produced no DEPS.md + deps-manifest.json"
    return json.loads(found[1].read_text())


# ------------------------------------------------------------ unit level

def test_parser_splits_direct_and_transitive(tmp_path):
    lock = tmp_path / "Cargo.lock"
    lock.write_text(_CARGO_LOCK)
    res = _parse_cargo_lock(lock, "Cargo.lock")
    assert res.status == "parsed"
    assert res.kind == "lockfile"
    assert res.ecosystem == "rust"
    by_name = {(p["name"], p["version"]): p["direct"] for p in res.pins}
    assert by_name[("serde", "1.0.197")] is True
    assert by_name[("log", "0.4.21")] is True
    for name, version in (("serde_derive", "1.0.197"),
                          ("proc-macro2", "1.0.79"),
                          ("quote", "1.0.35"),
                          ("syn", "2.0.52"),
                          ("unicode-ident", "1.0.12")):
        assert by_name[(name, version)] is False, name
    # The local package is the project itself, never a pin.
    assert "fixture-rust" not in {p["name"] for p in res.pins}
    assert "summary level" in res.note
    assert "2 direct" in res.note and "5 transitive" in res.note


def test_parser_without_local_package_records_all_as_transitive(tmp_path):
    lock = tmp_path / "Cargo.lock"
    lock.write_text(
        'version = 3\n\n'
        '[[package]]\nname = "serde"\nversion = "1.0.197"\n'
        'source = "registry+https://example.invalid/index"\n\n'
        '[[package]]\nname = "log"\nversion = "0.4.21"\n'
        'source = "registry+https://example.invalid/index"\n')
    res = _parse_cargo_lock(lock, "Cargo.lock")
    assert res.status == "parsed"
    # No local package means no direct pin can be proven from the
    # file; nothing is guessed to be direct, and nothing is dropped.
    assert len(res.pins) == 2
    assert all(p["direct"] is False for p in res.pins)


def test_parser_preserves_duplicate_names_at_different_versions(tmp_path):
    lock = tmp_path / "Cargo.lock"
    lock.write_text(
        'version = 3\n\n'
        '[[package]]\nname = "app"\nversion = "0.1.0"\n'
        'dependencies = ["syn 1.0.109", "syn 2.0.52"]\n\n'
        '[[package]]\nname = "syn"\nversion = "1.0.109"\n'
        'source = "registry+https://example.invalid/index"\n\n'
        '[[package]]\nname = "syn"\nversion = "2.0.52"\n'
        'source = "registry+https://example.invalid/index"\n')
    res = _parse_cargo_lock(lock, "Cargo.lock")
    assert res.status == "parsed"
    assert {(p["name"], p["version"]) for p in res.pins} == {
        ("syn", "1.0.109"), ("syn", "2.0.52")}
    assert all(p["direct"] for p in res.pins)


def test_parser_malformed_toml_is_error_not_crash(tmp_path):
    lock = tmp_path / "Cargo.lock"
    lock.write_text("this is = [not valid toml\n")
    res = _parse_cargo_lock(lock, "Cargo.lock")
    assert res.status == "error"
    assert res.pins == []
    assert "parse failed" in res.note


def test_parser_unrecognised_shape_is_detected_not_parsed(tmp_path):
    lock = tmp_path / "Cargo.lock"
    lock.write_text('version = 3\nmetadata = "no packages here"\n')
    res = _parse_cargo_lock(lock, "Cargo.lock")
    assert res.status == "detected-not-parsed"
    assert res.pins == []


# --------------------------------------------------------- black-box CLI

@needs_cli
def test_cargo_lock_pins_reach_the_pack(tmp_path):
    project = _rust_project(tmp_path / "rustproj")
    proc, found = run_pack(project, tmp_path / "out")
    assert proc.returncode == 0, combined(proc)
    data = _manifest(found)

    sources = {s["file"]: s for s in data["sources"]}
    assert sources["Cargo.lock"]["status"] == "parsed"
    assert sources["Cargo.lock"]["kind"] == "lockfile"
    assert sources["Cargo.lock"]["ecosystem"] == "rust"

    direct = {(p["name"], p["version"]) for p in data["sections"]["pins"]}
    assert ("serde", "1.0.197") in direct
    assert ("log", "0.4.21") in direct
    # No transitive pin and no local-package pin leaks into direct pins.
    assert ("serde_derive", "1.0.197") not in direct
    assert ("fixture-rust", "0.1.0") not in direct

    transitive = data["sections"]["transitive_pins"]
    assert len(transitive) == 1
    assert transitive[0]["source"] == "Cargo.lock"
    assert transitive[0]["count"] == 5
    for entry in ("serde_derive=1.0.197", "proc-macro2=1.0.79",
                  "quote=1.0.35", "syn=2.0.52", "unicode-ident=1.0.12"):
        assert entry in transitive[0]["pins"], entry

    assert data["counts"]["pins_recorded"] == 7
    assert data["counts"]["pins_transitive_recorded"] == 5

    deps_text = found[0].read_text()
    bodies = section_bodies(deps_text)
    assert "1.0.197" in bodies["pins"]
    assert "serde_derive=1.0.197" in bodies["pins"]
    assert "Cargo.lock" in deps_text
    # Summary discipline: checksums are lockfile payload, not pins.
    assert "must-not-be-reproduced" not in deps_text
    assert "must-not-be-reproduced" not in found[1].read_text()
    assert banned_hits(deps_text, found[1].read_text(),
                       combined(proc)) == []


@needs_cli
def test_cargo_lock_is_parsed_not_detected_in_doctor(tmp_path):
    project = _rust_project(tmp_path / "rustproj")
    proc = run_ghostdeps(["doctor", str(project), "--json"])
    assert proc.returncode == 0, combined(proc)
    report = json.loads(proc.stdout)
    sources = {s["file"]: s for s in report["sources"]}
    assert sources["Cargo.lock"]["status"] == "parsed"


@needs_cli
def test_rust_project_without_lockfile_still_packs(tmp_path):
    """Removing the lockfile changes the pins, not packability."""
    project = _rust_project(tmp_path / "rustproj", lock_text=None)
    proc, found = run_pack(project, tmp_path / "out")
    assert proc.returncode == 0, combined(proc)
    data = _manifest(found)
    assert data["counts"]["pins_recorded"] == 0
    assert {s["file"] for s in data["sources"]} == {"Cargo.toml"}
