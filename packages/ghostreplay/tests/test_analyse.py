"""Analyse contract tests (PLAN verification bar: planted waste).

- the re-read finding names src/hot.py with a count of 5;
- the never-referenced finding names src/legacy.py, its token figure
  equals the manifest's sliced_tokens for that file, and the human
  report uses the qualified label "not referenced in transcript"
  (never "not needed": a transcript can miss silent reads);
- REPLAY.md and replay-report.json are both produced.
"""
from conftest import (HOT, NEVER, entry_mentions, find_entries, load_report,
                      manifest_entry)


def test_analyse_writes_md_and_json_reports(analyse_planted):
    assert (analyse_planted / "REPLAY.md").is_file()
    assert (analyse_planted / "replay-report.json").is_file()


def test_reread_finding_names_hot_file_with_count_five(analyse_planted):
    report = load_report(analyse_planted)
    rereads = find_entries(report, "re_reads", "rereads", "reReads")
    hits = [e for e in rereads if entry_mentions(e, HOT)]
    assert hits, f"no re-read finding for {HOT} in report keys {sorted(report)}"
    counts = []
    for e in hits:
        if not isinstance(e, dict):
            continue
        for key in ("distinct_turns", "count", "reads", "times"):
            if isinstance(e.get(key), int):
                counts.append(e[key])
        if isinstance(e.get("turns"), list):
            counts.append(len(e["turns"]))
    assert 5 in counts, (
        f"{HOT} must be reported as read across 5 distinct turns; "
        f"got {hits}"
    )


def test_never_referenced_finding_names_legacy_with_manifest_tokens(analyse_planted):
    report = load_report(analyse_planted)
    never = find_entries(report, "not_referenced_in_transcript",
                         "never_referenced", "not_referenced",
                         "unreferenced", "unused")
    hits = [e for e in never if entry_mentions(e, NEVER)]
    assert hits, f"no never-referenced finding for {NEVER}"
    expected = manifest_entry(NEVER)["sliced_tokens"]
    token_values = [
        v for e in hits if isinstance(e, dict)
        for k, v in e.items() if "token" in k and isinstance(v, int)
    ]
    assert expected in token_values, (
        f"finding for {NEVER} must carry the manifest sliced_tokens "
        f"({expected}); got {hits}"
    )


def test_human_report_uses_qualified_label(analyse_planted):
    md = (analyse_planted / "REPLAY.md").read_text(encoding="utf-8")
    assert "not referenced in transcript" in md.lower(), (
        "REPLAY.md must use the qualified label 'not referenced in "
        "transcript' for bundle files the session never touched"
    )
    assert NEVER in md
    assert HOT in md
