"""Upstream guard-finding propagation (ecosystem seam fix, Oct 14, 2026).

The ecosystem pass (~/workspace/ghostslice-companions/ECOSYSTEM.md,
Seams #2) found that GhostSlice's export guard records findings
against bundled files while GhostFixture, building from that
bundle, dropped the flags silently: a flagged file was copied at
full fidelity with no trace of the upstream flag in Fixture's
outputs, because the two scanners disagree by design (Slice's
guard is name-based, Fixture's scan is shape-based) and nothing
carried the warning downstream.

The records a real GhostSlice manifest carries (verified against
Slice v1.0.6 exports): when a bundle is exported with redaction
on, each flagged file's entry gains ``redactions`` (the count of
values the guard flagged and replaced) and ``redaction_kinds``
(the guard's finding types for that file), and the manifest
gains a top-level ``redaction`` block. These tests build bundles
in exactly that shape and pin the propagation contract:

- flagged upstream, NOT confirmed by the shape scan (the real
  disagreement shape: a benign FTS5 ``tokenize = '...'`` line the
  name-based guard flags as a sensitive assignment): the file is
  copied, and the upstream finding plus the disagreement are
  recorded in the fixture manifest and in FIXTURE.md.
- flagged upstream AND shape-positive: the file is excluded
  under the existing flagged-secret rules, and the exclusion
  record names both verdicts.
- no upstream records anywhere: behaviour is exactly as before
  (no disagreement section, no upstream annotations).
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import helpers  # noqa: E402

pytestmark = pytest.mark.usefixtures("requires_cli")

# The disagreement case, shaped exactly like the real one the
# ecosystem pass found (GhostIndex's store.py): the FTS5 schema
# line `tokenize = 'unicode61'` sits inside a string literal.
# Slice's name-based guard flags it ("token" in the name, value
# long enough); the shape scan finds no secret shape in it.
STORE_PY = '''SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS docs USING fts5(
    rel,
    body,
    root UNINDEXED,
    tokenize = 'unicode61'
);
"""
'''

# The confirmed case: a fake, test-only AWS-shaped literal. It is
# not, and has never been, a real credential. Tests scan every
# output byte for this exact string.
CANARY = "AKIA7G4K9P2X8QW3Z6BN"
KEYS_PY = f'AWS_KEY = "{CANARY}"\n'

MAIN_PY = "def main():\n    return 42\n"

FILES = {
    "src/store.py": STORE_PY,
    "src/keys.py": KEYS_PY,
    "src/main.py": MAIN_PY,
}

# The guard records a real Slice --redact export writes for these
# files: path -> (redactions, redaction_kinds).
GUARD_RECORDS = {
    "src/store.py": (1, ["sensitive-assignment"]),
    "src/keys.py": (1, ["aws-access-key"]),
}


def _write_project(tmp_path: Path) -> Path:
    project = tmp_path / "seam_project"
    for rel, text in FILES.items():
        dest = project / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
    return project


def _write_bundle(project: Path, out: Path, guard_records=None) -> Path:
    """Write a GhostSlice-shaped bundle of ``project``.

    With ``guard_records`` ({path: (count, kinds)}), entries carry
    the ``redactions``/``redaction_kinds`` fields and the manifest
    the top-level ``redaction`` block, exactly as a real
    ``ghostslice export --redact`` writes them.
    """
    files_dir = out / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    manifest_files = []
    total = 0
    for rel in FILES:
        text = (project / rel).read_text(encoding="utf-8")
        dest = files_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        tokens = max(1, (len(text) + 3) // 4)
        total += tokens
        entry = {
            "path": rel,
            "mode": "full",
            "language": "python",
            "package": "",
            "original_tokens": tokens,
            "sliced_tokens": tokens,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        }
        if guard_records and rel in guard_records:
            count, kinds = guard_records[rel]
            entry["redactions"] = count
            entry["redaction_kinds"] = kinds
        manifest_files.append(entry)
    manifest = {
        "tool": "ghostslice",
        "version": "1.0.6",
        "generated_at": "2026-10-14T00:00:00+00:00",
        "root": str(project),
        "token_method": "fixture estimate (chars/4), test bundle only",
        "files": manifest_files,
        "total_original_tokens": total,
        "total_sliced_tokens": total,
        "total_saved_tokens": 0,
    }
    if guard_records:
        kinds_summary: dict = {}
        for count, kinds in guard_records.values():
            for kind in kinds:
                kinds_summary[kind] = kinds_summary.get(kind, 0) + count
        manifest["redaction"] = {
            "enabled": True,
            "values_redacted": sum(c for c, _ in guard_records.values()),
            "files_affected": len(guard_records),
            "kinds": kinds_summary,
            "left_in_place": 0,
            "leftover_kinds": [],
        }
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (out / "PROMPT.md").write_text(
        "\n".join(f"# File: {rel} (mode: full)\n{FILES[rel]}"
                  for rel in FILES),
        encoding="utf-8")
    return out


@pytest.fixture()
def seam_project(tmp_path):
    return _write_project(tmp_path)


@pytest.fixture()
def seam_bundle(seam_project, tmp_path):
    return _write_bundle(
        seam_project, tmp_path / "seam_bundle", GUARD_RECORDS)


def test_disagreement_copied_and_recorded_everywhere(
        seam_project, seam_bundle, tmp_path):
    out = tmp_path / "fixture"
    proc = helpers.build_fixture(seam_project, seam_bundle, out)
    assert proc.returncode == 0, helpers.combined(proc)

    # The file IS copied, byte-identical to the project original:
    # the shape scan found no secret shape in it.
    copied = out / "src/store.py"
    assert copied.is_file()
    assert copied.read_bytes() == (seam_project / "src/store.py").read_bytes()

    manifest = helpers.fixture_manifest(out)
    disagreements = manifest["upstream_disagreements"]
    assert len(disagreements) == 1, manifest["upstream_disagreements"]
    record = disagreements[0]
    assert record["path"] == "src/store.py"
    assert record["upstream_kinds"] == ["sensitive-assignment"]
    assert record["upstream_redactions"] == 1
    assert record["fixture_types"] == []
    assert manifest["totals"]["files_upstream_disagreements"] == 1

    # The included entry itself carries the upstream flag.
    included = {e["path"]: e for e in manifest["included"]}
    assert included["src/store.py"]["upstream_kinds"] == ["sensitive-assignment"]
    assert included["src/store.py"]["upstream_redactions"] == 1
    # The clean file carries no upstream annotation at all.
    assert "upstream_kinds" not in included["src/main.py"]

    # FIXTURE.md names the disagreement in its own section.
    summary = (out / "FIXTURE.md").read_text(encoding="utf-8")
    assert "## Upstream guard findings not confirmed by the shape scan" in summary
    assert "src/store.py" in summary
    assert "sensitive-assignment" in summary

    # The CLI surfaces it too, and the fixture still checks clean.
    assert "upstream disagreement" in helpers.combined(proc)
    check = helpers.check_fixture(out)
    assert check.returncode == 0, helpers.combined(check)


def test_confirmed_upstream_flag_excluded_with_both_verdicts(
        seam_project, seam_bundle, tmp_path):
    out = tmp_path / "fixture"
    proc = helpers.build_fixture(seam_project, seam_bundle, out)
    assert proc.returncode == 0, helpers.combined(proc)

    # Excluded under the existing flagged-secret rules.
    assert not (out / "src/keys.py").exists()
    manifest = helpers.fixture_manifest(out)
    flagged = {e["path"]: e for e in manifest["excluded_flagged"]}
    assert "src/keys.py" in flagged, manifest["excluded_flagged"]
    entry = flagged["src/keys.py"]
    assert "aws-access-key" in (entry.get("types") or [])
    # The record names the upstream verdict as well as Fixture's.
    assert entry["upstream_kinds"] == ["aws-access-key"]
    assert entry["upstream_redactions"] == 1
    assert entry["upstream_confirmed"] is True

    # A confirmed flag is an agreement, never a disagreement: the
    # only disagreement in this build is the unconfirmed store.py.
    disagreement_paths = [d["path"] for d in manifest["upstream_disagreements"]]
    assert disagreement_paths == ["src/store.py"]
    assert manifest["totals"]["files_upstream_disagreements"] == 1
    # Both recorded files reached the scan.
    assert manifest["totals"]["files_upstream_flagged"] == 2

    summary = (out / "FIXTURE.md").read_text(encoding="utf-8")
    assert "also flagged by the bundle's guard (aws-access-key)" in summary

    # The canary appears in no output byte and no CLI output.
    assert CANARY.encode() not in helpers.all_output_bytes(out)
    assert CANARY not in helpers.combined(proc)


def test_override_copy_keeps_both_records_no_disagreement(
        seam_project, seam_bundle, tmp_path):
    out = tmp_path / "fixture"
    proc = helpers.build_fixture(
        seam_project, seam_bundle, out, extra=["--include-flagged"])
    assert proc.returncode == 0, helpers.combined(proc)
    assert (out / "src/keys.py").is_file()
    manifest = helpers.fixture_manifest(out)
    flagged = {e["path"]: e for e in manifest["excluded_flagged"]}
    entry = flagged["src/keys.py"]
    assert entry.get("included_by_override") is True
    assert entry["upstream_kinds"] == ["aws-access-key"]
    assert entry["upstream_confirmed"] is True
    # Only the unconfirmed store.py is a disagreement.
    disagreements = manifest["upstream_disagreements"]
    assert [d["path"] for d in disagreements] == ["src/store.py"]


def test_no_upstream_records_behaves_exactly_as_before(
        seam_project, tmp_path):
    bundle = _write_bundle(seam_project, tmp_path / "plain_bundle")
    out = tmp_path / "fixture"
    proc = helpers.build_fixture(seam_project, bundle, out)
    assert proc.returncode == 0, helpers.combined(proc)

    manifest = helpers.fixture_manifest(out)
    assert manifest["upstream_disagreements"] == []
    assert manifest["totals"]["files_upstream_flagged"] == 0
    assert manifest["totals"]["files_upstream_disagreements"] == 0
    for entry in manifest["included"]:
        assert "upstream_kinds" not in entry
        assert "upstream_redactions" not in entry
    for entry in manifest["excluded_flagged"]:
        assert "upstream_kinds" not in entry
    # The shape scan alone still excludes the secret-shaped file,
    # and the benign file is still copied.
    assert (out / "src/store.py").is_file()
    assert not (out / "src/keys.py").exists()
    summary = (out / "FIXTURE.md").read_text(encoding="utf-8")
    assert "Upstream guard" not in summary
    assert "upstream disagreement" not in helpers.combined(proc)
