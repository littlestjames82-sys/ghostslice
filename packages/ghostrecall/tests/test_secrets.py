"""Verification bar #3 (PLAN.md): secrets in memory sources.

Fixture docs/private-note.md plants a fake key on a known line.
The item must be blocked by default, and the planted value must be
redacted in ALL output: bundles, manifests, prompts, and CLI text
may carry path + line + type only (Slice v0.4 guard behaviour).
"""
from conftest import (
    PLANTED_SECRET, bundle_all_text, manifest_items, run_bundle, run_cli,
)

TASK = "Write a first reply about a billing question using the support template"


def test_planted_secret_never_appears_in_bundle(secret_project, tmp_path):
    out = tmp_path / "bundle"
    r = run_bundle(secret_project, out, TASK)
    assert r.returncode == 0, r.stdout + r.stderr
    assert PLANTED_SECRET not in bundle_all_text(out)
    assert PLANTED_SECRET not in (r.stdout + r.stderr)


def test_secret_item_is_blocked_or_excluded(secret_project, tmp_path):
    out = tmp_path / "bundle"
    r = run_bundle(secret_project, out, TASK)
    assert r.returncode == 0, r.stdout + r.stderr
    hits = [i for i in manifest_items(out)
            if "private-note" in str(i["source"] or "")]
    if hits:
        for i in hits:
            status = (i["status"] or "").lower()
            mode = (i["mode"] or "").lower()
            assert status in ("blocked", "excluded") or mode == "exclude", (
                f"secret-bearing item exported unblocked: {i['raw']}"
            )
    else:
        # Fully omitted from the manifest is acceptable only if the
        # exclusion is still auditable somewhere in the output.
        hay = (bundle_all_text(out) + r.stdout + r.stderr).lower()
        assert "private-note" in hay, (
            "secret-bearing file silently vanished: no manifest entry, "
            "no blocked/excluded mention anywhere"
        )


def test_clean_sources_still_export(secret_project, tmp_path):
    """The guard blocks the dirty item, not the whole project."""
    out = tmp_path / "bundle"
    r = run_bundle(secret_project, out, TASK)
    assert r.returncode == 0, r.stdout + r.stderr
    text = bundle_all_text(out)
    assert "friendly template v2" in text


def test_recall_output_is_redacted(secret_project):
    r = run_cli("recall", secret_project, "--task", TASK)
    assert PLANTED_SECRET not in (r.stdout + r.stderr), (
        "planted secret leaked into `recall` CLI output"
    )
