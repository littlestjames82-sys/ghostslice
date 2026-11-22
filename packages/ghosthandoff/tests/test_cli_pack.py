"""CLI pack contract (PLAN MVP item 1 and the verification bar).

The pack built from the fixture repo must state, in both HANDOFF.md
and handoff.json: the branch, the HEAD hash, the 2 in-window commits
(and not the old one), the staged / unstaged / untracked files, the
stash entry, the 3 markers, and the failing verify verdict. And the
described project must be byte-identical after the run.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pytest  # noqa: E402

import helpers  # noqa: E402

pytestmark = pytest.mark.skipif(
    not helpers.cli_available(),
    reason="ghosthandoff CLI not discoverable (see REPORT_B.md)")


def build_pack(project: Path, tmp_path: Path, *extra: str):
    outdir = tmp_path / "pack-out"
    proc = helpers.run_cli(
        ["pack", str(project), "-o", str(outdir), *extra],
        cwd=tmp_path)
    assert proc.returncode == 0, (
        f"pack exited {proc.returncode}\n{proc.stdout}\n{proc.stderr}")
    return outdir


def test_pack_writes_both_files(fixture_repo, tmp_path):
    outdir = build_pack(fixture_repo, tmp_path)
    md, js = helpers.find_pack(outdir)
    assert md is not None and js is not None


def test_pack_names_branch_and_head(fixture_repo, tmp_path):
    outdir = build_pack(fixture_repo, tmp_path)
    head = helpers.head_short(fixture_repo)
    text = helpers.pack_text(outdir)
    strings = helpers.all_strings(helpers.load_pack_json(outdir))
    assert helpers.BRANCH in text
    assert any(helpers.BRANCH in s for s in strings)
    assert head in text
    assert any(head in s for s in strings)


def test_pack_session_commits_are_the_two_recent_ones(fixture_repo, tmp_path):
    outdir = build_pack(fixture_repo, tmp_path)
    data = helpers.load_pack_json(outdir)
    strings = helpers.all_strings(data)
    text = helpers.pack_text(outdir)
    for subject in helpers.SESSION_SUBJECTS:
        assert subject in text
        assert any(subject in s for s in strings)
    # The 3-day-old commit is outside the default 12h window: it must
    # not be presented as a session commit in the machine pack.
    commit_lists = helpers.values_for_key(data, "commit")
    session_subjects = set()
    for value in commit_lists:
        if isinstance(value, list):
            for entry in value:
                if isinstance(entry, dict):
                    subj = entry.get("subject") or entry.get("message") or ""
                    session_subjects.add(subj)
                elif isinstance(entry, str):
                    session_subjects.add(entry)
    if session_subjects:
        assert helpers.OLD_SUBJECT not in session_subjects


def test_pack_lists_staged_unstaged_untracked(fixture_repo, tmp_path):
    outdir = build_pack(fixture_repo, tmp_path)
    data = helpers.load_pack_json(outdir)
    text = helpers.pack_text(outdir)
    staged = helpers.names_in(helpers.values_for_key(data, "staged"))
    unstaged = helpers.names_in(helpers.values_for_key(
        data, "unstaged", "modified", "unstaged_changes"))
    untracked = helpers.names_in(helpers.values_for_key(data, "untracked"))
    assert helpers.STAGED_FILE in staged
    assert helpers.MODIFIED_FILE in unstaged
    assert helpers.UNTRACKED_FILE in untracked
    # And the human pack names all three files too.
    for name in (helpers.STAGED_FILE, helpers.MODIFIED_FILE,
                 helpers.UNTRACKED_FILE):
        assert name in text


def test_pack_reports_the_stash(fixture_repo, tmp_path):
    outdir = build_pack(fixture_repo, tmp_path)
    text = helpers.pack_text(outdir).lower()
    strings = [s.lower() for s in
               helpers.all_strings(helpers.load_pack_json(outdir))]
    assert "stash" in text
    assert any("stash" in s for s in strings)


def marker_files_in(data) -> set[str]:
    """Files of marker items in the JSON pack: dicts carrying a file
    plus a marker kind (TODO / FIXME / XXX / HACK)."""
    found = set()

    def walk(obj):
        if isinstance(obj, dict):
            kind = str(obj.get("kind", ""))
            name = helpers.entry_name(obj)
            if kind in ("TODO", "FIXME", "XXX", "HACK") and name:
                found.add(name)
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for value in obj:
                walk(value)

    walk(data)
    return found


def test_pack_lists_all_three_markers(fixture_repo, tmp_path):
    outdir = build_pack(fixture_repo, tmp_path)
    data = helpers.load_pack_json(outdir)
    text = helpers.pack_text(outdir)
    # The core renders a marker as "file:line [KIND]: <text after the
    # marker word>", so assert file + kind + marker body text.
    bodies = {
        "pricing.py": "handle tax rounding at checkout",
        "app.py": "retry the pricing call on failure",
        "scratch.py": "decide whether this scratch file ships",
    }
    for rel, body in bodies.items():
        assert rel in text and body in text
    assert marker_files_in(data) == set(helpers.MARKER_FILES)


def test_pack_quotes_the_failing_verify_verdict(fixture_repo, tmp_path):
    outdir = build_pack(fixture_repo, tmp_path)
    text = helpers.pack_text(outdir)
    lowered = text.lower()
    assert "verify-report.json" in text
    assert "fail" in lowered


def test_pack_leaves_project_byte_identical(fixture_repo, tmp_path):
    before_status = helpers.porcelain(fixture_repo)
    before_head = helpers.git(fixture_repo, "rev-parse", "HEAD").stdout.strip()
    before = helpers.tree_hashes(fixture_repo)
    build_pack(fixture_repo, tmp_path)
    after = helpers.tree_hashes(fixture_repo)
    assert after == before, (
        "project tree changed during pack run: "
        f"added={sorted(set(after) - set(before))}, "
        f"removed={sorted(set(before) - set(after))}, "
        f"changed={sorted(k for k in before if k in after and before[k] != after[k])}")
    assert helpers.porcelain(fixture_repo) == before_status
    # Propose-only also means: no new commit was made on our behalf.
    head_after = helpers.git(fixture_repo, "rev-parse", "HEAD").stdout.strip()
    assert head_after == before_head


def test_pack_json_and_md_agree_on_files(fixture_repo, tmp_path):
    """Agreement bar, checked one way: every file the JSON pack puts
    in a git-state or marker list also appears in HANDOFF.md."""
    outdir = build_pack(fixture_repo, tmp_path)
    data = helpers.load_pack_json(outdir)
    text = helpers.pack_text(outdir)
    names = set()
    for needles in (("staged",), ("unstaged", "modified"), ("untracked",),
                    ("marker", "todo")):
        names |= helpers.names_in(helpers.values_for_key(data, *needles))
    assert names, "expected the JSON pack to carry file lists"
    for name in names:
        assert name in text, f"{name} is in handoff.json but not HANDOFF.md"


def test_pack_default_output_is_callers_cwd_not_project(fixture_repo, tmp_path):
    before = helpers.tree_hashes(fixture_repo)
    proc = helpers.run_cli(["pack", str(fixture_repo)], cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    default_out = tmp_path / "handoff-out"
    md, js = helpers.find_pack(default_out)
    assert md is not None and js is not None
    assert helpers.tree_hashes(fixture_repo) == before


def test_pack_since_window_widens_with_duration(fixture_repo, tmp_path):
    """--since 4d reaches back past the 3-day-old commit, so the old
    commit joins the session list (the default 12h window excludes
    it; see the session-commits test above)."""
    outdir = build_pack(fixture_repo, tmp_path, "--since", "4d")
    data = helpers.load_pack_json(outdir)
    subjects = set()
    for value in helpers.values_for_key(data, "commit"):
        if isinstance(value, list):
            for entry in value:
                if isinstance(entry, dict):
                    subjects.add(entry.get("subject") or "")
    assert helpers.OLD_SUBJECT in subjects
    for subject in helpers.SESSION_SUBJECTS:
        assert subject in subjects


def test_pack_redacts_secret_shaped_marker_text(plain_folder, tmp_path):
    """Quoted lines pass through a secret-shape redaction pass
    (PLAN safety rules): an AKIA-shaped string inside a marker line
    must not reach either pack file in the clear."""
    canary = "AKIAIOSFODNN7EXAMPLE"
    (plain_folder / "secret_note.py").write_text(
        f"# TODO: rotate the staging key {canary} this week\n",
        encoding="utf-8")
    outdir = tmp_path / "pack-out"
    proc = helpers.run_cli(
        ["pack", str(plain_folder), "-o", str(outdir)], cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    md_text = helpers.pack_text(outdir)
    json_text = (outdir / "handoff.json").read_text(encoding="utf-8")
    assert canary not in md_text
    assert canary not in json_text
    assert "rotate the staging key" in md_text
    assert "redact" in md_text.lower()


def test_pack_missing_project_exits_2(tmp_path):
    proc = helpers.run_cli(
        ["pack", str(tmp_path / "no-such-project"), "-o",
         str(tmp_path / "out")], cwd=tmp_path)
    assert proc.returncode == 2, (
        f"expected exit 2 for a missing project, got {proc.returncode}\n"
        f"{proc.stdout}\n{proc.stderr}")
