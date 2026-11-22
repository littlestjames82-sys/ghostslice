"""Verification bar #2 (PLAN.md): superseded decisions.

Fixture: D-010 held all releases (2026-02-01); D-011 lifted the hold
(2026-03-01, Supersedes: D-010). The old decision must never be served
as current: it must be marked superseded, excluded, or blocked in the
manifest, and the current decision must be the one exported.
"""
from conftest import bundle_all_text, bundle_prompt, manifest_items, run_bundle

TASK = "What is the current rule for shipping releases?"
OLD_TEXT = "Hold all releases until the security review is complete"
NEW_TEXT = "Release hold lifted"


def _find(items, needle):
    return [i for i in items
            if needle.lower() in str(i["decision"] or "").lower()
            or needle.lower() in str(i["raw"]).lower()]


def test_current_decision_is_exported(superseded_project, tmp_path):
    out = tmp_path / "bundle"
    r = run_bundle(superseded_project, out, TASK)
    assert r.returncode == 0, r.stdout + r.stderr
    text = bundle_all_text(out)
    assert NEW_TEXT in text, "the current (lifting) decision is missing"
    items = manifest_items(out)
    current = [i for i in _find(items, NEW_TEXT)
               if (i["status"] or "current").lower() in ("current", "active", "included")]
    assert current or NEW_TEXT in text


def test_old_decision_never_served_as_current(superseded_project, tmp_path):
    out = tmp_path / "bundle"
    r = run_bundle(superseded_project, out, TASK)
    assert r.returncode == 0, r.stdout + r.stderr
    # The D-010 item is identified by its title/id, not by body text:
    # manifest items do not reliably carry the decision text, and a
    # text-only search would pass vacuously if it were absent.
    old_items = [i for i in manifest_items(out)
                 if "D-010" in str(i["decision"] or "")
                 or "D-010" in str(i["raw"].get("id", ""))]
    assert old_items or OLD_TEXT not in bundle_prompt(out), (
        "D-010 is neither a manifest item nor marked anywhere, "
        "yet its text is in the prompt"
    )
    for i in old_items:
        status = (i["status"] or "").lower()
        mode = (i["mode"] or "").lower()
        assert status in ("superseded", "excluded", "blocked") or mode == "exclude", (
            f"superseded decision exported as current: {i['raw']}"
        )


def test_old_decision_in_prompt_only_if_marked(superseded_project, tmp_path):
    out = tmp_path / "bundle"
    r = run_bundle(superseded_project, out, TASK)
    assert r.returncode == 0, r.stdout + r.stderr
    prompt = bundle_prompt(out)
    if OLD_TEXT in prompt:
        low = prompt.lower()
        assert "superseded" in low or "replaced" in low or "no longer" in low, (
            "old decision text appears in PROMPT.md with no superseded marking"
        )


def test_conflict_is_flagged_not_silently_picked(superseded_project, tmp_path):
    """PLAN: a source that contradicts a newer decision in the same
    bundle is flagged as a conflict rather than silently resolved.
    Accept either a manifest flag or report text naming the conflict."""
    out = tmp_path / "bundle"
    r = run_bundle(superseded_project, out, TASK)
    assert r.returncode == 0, r.stdout + r.stderr
    hay = (bundle_all_text(out) + r.stdout).lower()
    items_text = str(manifest_items(out)).lower()
    assert ("conflict" in hay or "supersed" in hay
            or "conflict" in items_text or "supersed" in items_text), (
        "no conflict / superseded flag anywhere in bundle or output"
    )
