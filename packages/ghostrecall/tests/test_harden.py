"""Harden lane (Oct 18, 2026): regression tests for bugs found by
auditing weak error handling and boundary cases. Each test names the
bug it pins down; all of these failed on the pre-harden code.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from conftest import PLANTED_SECRET, run_cli  # noqa: E402

SECRET_LINE = f"api_key={PLANTED_SECRET}ExtraLong123"


def _decision_item(item_id="decision-x", tags=(), blocked=False, status="active"):
    from ghostrecall.model import Item, Provenance
    it = Item(id=item_id, title=f"Title {item_id}",
              text=f"storage text {SECRET_LINE if blocked else 'clean'}",
              source_type="decision",
              provenance=Provenance(path="DECISIONS.md", line=1, date="2026-01-01"),
              tags=list(tags), status=status)
    if blocked:
        it.secret_findings = [{"path": "DECISIONS.md", "line": 1,
                                "type": "generic-secret-assignment"}]
    return it


# --- F1: pinned + secret-blocked items were SELECTED (secret leak) ---

def test_pinned_blocked_item_is_never_selected():
    from ghostrecall.recall import select
    pinned_secret = _decision_item("decision-secret", tags=["rule"], blocked=True)
    clean = _decision_item("decision-clean")
    selected, not_selected, _ = select([pinned_secret, clean], "storage", {})
    assert [e["item"].id for e in selected] == ["decision-clean"]
    reasons = {e["item"].id: e["reason"] for e in not_selected}
    assert "secret" in reasons["decision-secret"]


def test_mcp_recall_search_never_previews_pinned_secret(tmp_path):
    from ghostrecall.mcp_server import _call
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "DECISIONS.md").write_text(
        "# Decisions\n\n## D-001 (2026-01-01)\n"
        "Decision: Use the secret rule for storage.\n"
        f"Reason: {SECRET_LINE}\n"
        "Supersedes: none\nStatus: current\nTags: rule, storage\n")
    res = _call("recall_search", {"project": str(proj), "task": "storage"})
    assert PLANTED_SECRET not in json.dumps(res)
    assert res["selected"] == []


def test_recall_cli_does_not_list_pinned_secret_as_selected(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "DECISIONS.md").write_text(
        "# Decisions\n\n## D-001 (2026-01-01)\n"
        "Decision: Use the secret rule for storage.\n"
        f"Reason: {SECRET_LINE}\n"
        "Supersedes: none\nStatus: current\nTags: rule, storage\n")
    r = run_cli("recall", proj, "--task", "storage", "--json")
    assert r.returncode == 0, r.stdout + r.stderr
    data = json.loads(r.stdout)
    assert data["selected"] == []
    assert PLANTED_SECRET not in (r.stdout + r.stderr)


# --- F2: IGNORE_DIRS matched absolute paths, emptying projects ---

def test_project_under_build_named_ancestor_still_collects(tmp_path):
    from ghostrecall.sources import collect_items
    proj = tmp_path / "build" / "myproj"
    proj.mkdir(parents=True)
    (proj / "notes.md").write_text("# Notes\n\nCaching is important.\n")
    (proj / "build").mkdir()
    (proj / "build" / "gen.md").write_text("# Gen\n\nGenerated, ignored.\n")
    items = collect_items(proj, include_git=False)
    titles = [i.title for i in items]
    assert "Notes" in titles          # ancestor "build" must not empty it
    assert "Gen" not in titles       # in-project build/ still ignored


# --- F3: project root inside / containing private memory refused ---

def test_root_inside_forbidden_memory_is_refused(tmp_path, monkeypatch):
    import ghostrecall.sources as sources
    fake_mem = tmp_path / "memory"
    proj = fake_mem / "proj"
    proj.mkdir(parents=True)
    monkeypatch.setattr(sources, "_forbidden_roots", lambda: [
        (tmp_path / "MEMORY.md"), fake_mem, (tmp_path / ".MEMORY.md")])
    with pytest.raises(ValueError):
        sources.assert_project_root(proj)
    with pytest.raises(ValueError):
        sources.assert_project_root(tmp_path)  # contains the forbidden root


# --- F4: check_bundle crashed on malformed manifests ---

def test_check_bundle_malformed_manifests_report_problems(tmp_path):
    from ghostrecall.bundle import check_bundle
    b = tmp_path / "bundle"
    b.mkdir()
    (b / "PROMPT.md").write_text("hi")
    (b / "manifest.json").write_text(json.dumps(["not", "a", "dict"]))
    ok, problems = check_bundle(b)
    assert not ok and problems
    (b / "manifest.json").write_text(json.dumps({"items": {"a": 1}}))
    ok, problems = check_bundle(b)
    assert not ok and problems
    (b / "manifest.json").write_text(json.dumps({
        "items": [{"id": "x", "exported_file": "files/a.md",
                   "sha256": "0" * 64, "sliced_tokens": 1,
                   "provenance": {"path": "a.md", "line": 1}}],
        "totals": {}}))
    (b / "files").mkdir()
    (b / "files" / "a.md").mkdir()  # exported file is a directory
    ok, problems = check_bundle(b)
    assert not ok and problems


def test_check_cli_on_malformed_manifest_is_clean_fail(tmp_path):
    b = tmp_path / "bundle"
    b.mkdir()
    (b / "manifest.json").write_text('["x"]')
    (b / "PROMPT.md").write_text("hi")
    r = run_cli("check", b)
    assert r.returncode != 0
    assert "Traceback" not in r.stderr


# --- F5: malformed slice-bundle manifests crashed with AttributeError ---

def test_slice_bundle_malformed_manifest_raises_valueerror(tmp_path):
    from ghostrecall.bundle import _load_slice_bundle
    sb = tmp_path / "sb"
    sb.mkdir()
    for payload in ('{"files": "notalist"}', '{"files": [123]}', '{not json'):
        (sb / "manifest.json").write_text(payload)
        with pytest.raises(ValueError):
            _load_slice_bundle(sb)


# --- F6: profile accepted wrong-typed / out-of-range values ---

@pytest.mark.parametrize("recall", [
    {"max_items": -5}, {"max_items": "fifty"}, {"max_items": True},
    {"recent_n": 0}, {"recent_n": -3},
    {"git_limit": -1}, {"git_limit": 2.5},
    {"pinned_rules": "Never rename"}, {"pinned_rules": [123]},
    {"include_git": "yes"}, {"memory_budget_fraction": True},
])
def test_profile_rejects_bad_recall_values(tmp_path, recall):
    from ghostrecall.profile import load_profile
    (tmp_path / ".ghostslice.json").write_text(json.dumps({"recall": recall}))
    with pytest.raises(ValueError):
        load_profile(tmp_path)


def test_profile_valid_values_still_load(tmp_path):
    from ghostrecall.profile import load_profile
    (tmp_path / ".ghostslice.json").write_text(json.dumps({"recall": {
        "max_items": 10, "recent_n": 3, "git_limit": 0,
        "pinned_rules": ["D-001"], "include_git": False}}))
    cfg = load_profile(tmp_path)
    assert cfg["max_items"] == 10 and cfg["git_limit"] == 0


def test_select_rejects_nonpositive_limits_directly():
    from ghostrecall.recall import select
    it = _decision_item()
    with pytest.raises(ValueError):
        select([it], "storage", {"recent_n": -1}, mode="recent")
    with pytest.raises(ValueError):
        select([it], "storage", {"max_items": 0})


# --- F7: fit=0 silently ignored, negative fit silently emptied ---

def test_fit_must_be_positive(tmp_path):
    from ghostrecall.bundle import build_bundle
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "notes.md").write_text("# Notes\n\nstorage notes here.\n")
    for bad in (0, -100):
        with pytest.raises(ValueError):
            build_bundle(proj, tmp_path / f"out{bad}", task="storage", fit=bad)


# --- F8: CLI dumped tracebacks on plain filesystem errors ---

def test_cli_bundle_out_path_is_file_is_clean_error(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "notes.md").write_text("# N\n\nhi storage\n")
    afile = tmp_path / "afile"
    afile.write_text("x")
    r = run_cli("bundle", proj, "-o", afile)
    assert r.returncode == 2
    assert "Traceback" not in r.stderr


# --- F9: non-current decision statuses were served as current ---

@pytest.mark.parametrize("status", [
    "archived", "withdrawn", "deprecated", "revoked", "obsolete",
    "superseded.", "Superseded",
])
def test_noncurrent_status_maps_to_superseded(status):
    from ghostrecall.sources import parse_decisions
    items = parse_decisions(
        f"# D\n\n## X1 (2026-01-01)\nDecision: Do thing.\nReason: r\n"
        f"Supersedes: none\nStatus: {status}\n", "DECISIONS.md")
    assert items[0].status == "superseded"


def test_current_and_active_statuses_stay_active():
    from ghostrecall.sources import parse_decisions
    for status in ("current", "active"):
        items = parse_decisions(
            f"# D\n\n## X1 (2026-01-01)\nDecision: Do thing.\nReason: r\n"
            f"Supersedes: none\nStatus: {status}\n", "DECISIONS.md")
        assert items[0].status == "active"


# --- F10: identical decision headings produced identical item ids ---

def test_duplicate_headings_get_unique_ids():
    from ghostrecall.sources import parse_decisions
    items = parse_decisions(
        "# Decisions\n\n## Storage rule\nDecision: first unique alpha.\n"
        "Reason: a\n\n## Storage rule\nDecision: second unique beta.\n"
        "Reason: b\n", "DECISIONS.md")
    assert len(items) == 2
    assert items[0].id != items[1].id


# --- F11: placeholder word anywhere in a line exempted real secrets ---

def test_placeholder_elsewhere_in_line_does_not_exempt_secret():
    from ghostrecall.secrets import scan_text
    assert scan_text(f"{SECRET_LINE}  # example of a real key", "x.md")
    assert scan_text(f"token: {PLANTED_SECRET}LongValue123 fake", "x.md")


def test_placeholder_inside_the_value_still_exempts():
    from ghostrecall.secrets import scan_text
    # AWS's own documented example key carries EXAMPLE inside the key.
    assert scan_text("key = AKIAIOSFODNN7EXAMPLE", "x.md") == []
    assert scan_text('api_key = "your-api-key-here-1234567890"', "x.md") == []
