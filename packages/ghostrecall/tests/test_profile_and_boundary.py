"""Profile discipline, project-local boundary, explain visibility."""
import json

from conftest import bundle_all_text, run_bundle, run_cli


def test_unknown_recall_profile_key_fails_loudly(provenance_project, tmp_path):
    profile = provenance_project / ".ghostslice.json"
    profile.write_text(json.dumps(
        {"recall": {"definitely_not_a_real_key": True}}))
    out = tmp_path / "bundle"
    r = run_bundle(provenance_project, out, "storage")
    assert r.returncode != 0, (
        "unknown key in the recall profile section was silently accepted"
    )
    assert "definitely_not_a_real_key" in (r.stdout + r.stderr) or \
        "unknown" in (r.stdout + r.stderr).lower()


def test_sources_outside_project_are_not_imported(tmp_path):
    """PLAN boundary rule: Recall reads project-local sources only.
    A DECISIONS.md in a *sibling* folder must never leak into a bundle
    built for this project (and Muse private memory stays out by the
    same mechanism: it is simply outside the project root)."""
    proj = tmp_path / "proj"
    (proj / "docs").mkdir(parents=True)
    (proj / "DECISIONS.md").write_text(
        "# Decisions\n\n## D-100 (2026-05-01)\n"
        "Decision: Inside project decision about caching.\n"
        "Reason: Local to this project.\nSupersedes: none\n"
        "Status: current\nTags: rule\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = "OUTSIDE_PROJECT_MARKER_DECISION"
    (outside / "DECISIONS.md").write_text(
        "# Decisions\n\n## D-999 (2026-05-02)\n"
        f"Decision: {marker} about other project.\n"
        "Reason: Must never be imported.\nSupersedes: none\n"
        "Status: current\nTags: rule\n")
    out = tmp_path / "bundle"
    r = run_bundle(proj, out, "caching decision")
    assert r.returncode == 0, r.stdout + r.stderr
    assert marker not in bundle_all_text(out)
    assert marker not in (r.stdout + r.stderr)


def test_explain_shows_what_was_not_selected(provenance_project):
    """PLAN risk note: TF-IDF misses must be visible. An explain view
    (command or --explain flag) must list non-selected items too."""
    r = run_cli("explain", provenance_project, "--task",
                "How does local storage work?")
    if r.returncode != 0:
        r = run_cli("recall", provenance_project, "--task",
                    "How does local storage work?", "--explain")
    assert r.returncode == 0, r.stdout + r.stderr
    hay = (r.stdout + r.stderr).lower()
    assert ("not selected" in hay or "excluded" in hay
            or "skipped" in hay or "not included" in hay), (
        "explain output names nothing that was left out"
    )


def test_recall_ranks_with_token_costs(provenance_project):
    """PLAN: TF-IDF ranking is shown with token costs per item."""
    r = run_cli("recall", provenance_project, "--task",
                "How does local storage work in the widget service?")
    assert r.returncode == 0, r.stdout + r.stderr
    out = r.stdout + r.stderr
    # The CLI ranks by title/id, not body text: the task-relevant note
    # ("Storage notes") or the storage decision (D-001) must rank in.
    assert "Storage notes" in out or "D-001" in out, out
    low = out.lower()
    assert "token" in low or " est" in low, (
        "recall output shows no token costs"
    )
