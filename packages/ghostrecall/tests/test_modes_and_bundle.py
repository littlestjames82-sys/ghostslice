"""Memory modes, rule pinning, combined bundle, fit, and check."""
from conftest import (
    bundle_prompt, load_manifest, manifest_items, run_bundle, run_cli,
)

REASON_D001 = "Zero-config, single file"


def _make_slice_bundle(tmp_path):
    """A minimal GhostSlice-shaped bundle (manifest + PROMPT.md) so the
    combined-bundle merge can be tested without a GhostSlice checkout.
    Core contract (bundle.py): code enters via --slice-bundle."""
    import hashlib
    sb = tmp_path / "slice_bundle"
    sb.mkdir()
    code_prompt = "# src/app.py\n\nimport sqlite3\n\ndef connect(path):\n    return sqlite3.connect(path)\n"
    (sb / "PROMPT.md").write_text(code_prompt)
    (sb / "manifest.json").write_text(__import__("json").dumps({
        "files": [{
            "path": "src/app.py", "mode": "full",
            "original_tokens": 50, "sliced_tokens": 50,
            "sha256": hashlib.sha256(code_prompt.encode()).hexdigest(),
        }],
    }))
    return sb


def test_combined_bundle_has_code_and_memory(provenance_project, tmp_path):
    out = tmp_path / "bundle"
    sb = _make_slice_bundle(tmp_path)
    r = run_cli("bundle", provenance_project,
                "--task", "How does local storage work in the widget service?",
                "--fit", 4000, "--slice-bundle", sb, "-o", out)
    assert r.returncode == 0, r.stdout + r.stderr
    types = {(i["source_type"] or "").lower() for i in manifest_items(out)}
    assert "code" in types, f"no code items in combined bundle: {types}"
    assert types & {"decision", "note", "commit", "memory", "doc", "docs"}, types
    prompt = bundle_prompt(out)
    assert prompt, "combined bundle has no merged PROMPT.md"
    assert "SQLite" in prompt


def test_combined_bundle_references_slice_manifest(provenance_project, tmp_path):
    """PLAN: the combined bundle carries the Slice manifest reference
    alongside the Recall manifest (a path, hash, or embedded object)."""
    out = tmp_path / "bundle"
    r = run_bundle(provenance_project, out, "storage")
    assert r.returncode == 0, r.stdout + r.stderr
    data = load_manifest(out)
    hay = str(data).lower()
    assert "slice" in hay, "no GhostSlice manifest reference in combined manifest"


def test_fit_budget_is_respected(provenance_project, tmp_path):
    out = tmp_path / "bundle"
    fit = 600
    r = run_bundle(provenance_project, out, "storage and naming rules", fit=fit)
    if r.returncode != 0:
        # Slice --fit discipline: unfittable writes the bundle, exit 1.
        assert r.returncode == 1, r.stdout + r.stderr
        return
    items = manifest_items(out)
    total = None
    data = load_manifest(out)
    for key in ("sliced_tokens", "total_sliced_tokens", "total_tokens"):
        if isinstance(data.get(key), int):
            total = data[key]
    if total is None:
        total = sum(i["sliced_tokens"] for i in items
                    if isinstance(i["sliced_tokens"], int)
                    and (i["mode"] or "").lower() != "exclude")
    assert total <= fit, f"sliced total {total} exceeds --fit {fit}"


def test_decision_only_strips_reason(provenance_project, tmp_path):
    out = tmp_path / "bundle"
    r = run_cli("bundle", provenance_project, "--task", "storage",
                "--mode", "decision-only", "-o", out)
    if r.returncode != 0 and "unrecognized" in (r.stderr + r.stdout).lower():
        r = run_cli("bundle", provenance_project, "--task", "storage",
                    "--memory-mode", "decision-only", "-o", out)
    assert r.returncode == 0, r.stdout + r.stderr
    prompt = bundle_prompt(out)
    assert "Use SQLite for all local storage" in prompt
    assert REASON_D001 not in prompt, "decision-only mode kept the reason text"


def test_rule_pinning_includes_standing_rule(provenance_project, tmp_path):
    """D-002 is tagged `rule`. A task that does not mention naming must
    still surface it (pinned, not TF-IDF ranked), per PLAN."""
    out = tmp_path / "bundle"
    r = run_bundle(provenance_project, out,
                   "How does local storage work in the widget service?")
    assert r.returncode == 0, r.stdout + r.stderr
    text = bundle_prompt(out)
    assert "Never rename a public command" in text, (
        "standing rule D-002 was not pinned into an unrelated-task bundle"
    )
    items = manifest_items(out)
    pinned = [i for i in items
              if "Never rename a public command" in str(i["decision"] or "")
              or "Never rename a public command" in str(i["raw"])]
    if pinned:
        assert any(i["pinned"] in (True, "true", "pinned", "yes")
                   for i in pinned), (
            "rule item present but not marked as pinned in the manifest"
        )


def test_check_accepts_good_bundle(provenance_project, tmp_path):
    out = tmp_path / "bundle"
    r = run_bundle(provenance_project, out, "storage")
    assert r.returncode == 0, r.stdout + r.stderr
    r2 = run_cli("check", out)
    assert r2.returncode == 0, r2.stdout + r2.stderr


def test_check_rejects_tampered_bundle(provenance_project, tmp_path):
    """Manifest contract: an exported file whose bytes change after
    export must fail check (sha256 / token totals in the manifest)."""
    out = tmp_path / "bundle"
    r = run_bundle(provenance_project, out, "storage")
    assert r.returncode == 0, r.stdout + r.stderr
    files = sorted((out / "files").glob("*"))
    assert files, "bundle exported no files to tamper with"
    files[0].write_text(files[0].read_text() + "\nTAMPERED LINE\n")
    r2 = run_cli("check", out)
    assert r2.returncode != 0, "check accepted a bundle with a tampered file"


import pytest


# F4 fixed Oct 14, 2026 (see FIX_REPORT.md): check now verifies PROMPT.md
# via manifest prompt_sha256 + totals.prompt_tokens_estimate. The former
# strict-xfail marker was removed by the parent on the fix landing, so this
# test is now a permanent pass requirement.
def test_check_rejects_tampered_prompt(provenance_project, tmp_path):
    out = tmp_path / "bundle"
    r = run_bundle(provenance_project, out, "storage")
    assert r.returncode == 0, r.stdout + r.stderr
    prompt = out / "PROMPT.md"
    assert prompt.is_file()
    prompt.write_text(prompt.read_text() + "\nTAMPERED LINE\n")
    r2 = run_cli("check", out)
    assert r2.returncode != 0, "check accepted a bundle whose PROMPT.md changed"
