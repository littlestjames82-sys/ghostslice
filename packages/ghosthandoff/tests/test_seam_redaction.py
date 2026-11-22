"""Seam fix (Oct 14, 2026): Handoff's redaction shapes aligned with
GhostSlice's canonical secret guard.

The ecosystem pass found that Slice's canonical AWS pattern covers
``AKIA`` and ``ASIA`` (temporary session keys) while Handoff's
redactor used an AKIA-only pattern, so an ASIA key quoted in a
marker line or a report excerpt would have shipped in the clear.
These tests pin the seam shut: end-to-end, an ASIA canary planted
in a marker line and in a report excerpt must be redacted in both
HANDOFF.md and handoff.json, and at unit level each aligned shape
must behave the way the canonical guard's spelling implies.

Existing tests are untouched; the pre-existing AKIA marker test in
test_cli_pack.py remains the AKIA anchor.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pytest  # noqa: E402

import helpers  # noqa: E402

REDACTED = "[redacted-secret-shape]"
ASIA_CANARY = "ASIA1234567890ABCDEF"  # ASIA + 16 [0-9A-Z], the seam shape
AKIA_CANARY = "AKIA1234567890ABCDEF"
AWS_SECRET_40 = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"  # exactly 40

needs_cli = pytest.mark.skipif(
    not helpers.cli_available(),
    reason="ghosthandoff CLI not discoverable (see REPORT_B.md)")


def _redact_module():
    src = Path(__file__).resolve().parents[1] / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    import ghosthandoff.redact as redact
    return redact


def build_pack(project: Path, tmp_path: Path, name: str = "pack-out"):
    outdir = tmp_path / name
    proc = helpers.run_cli(
        ["pack", str(project), "-o", str(outdir)], cwd=tmp_path)
    assert proc.returncode == 0, (
        f"pack exited {proc.returncode}\n{proc.stdout}\n{proc.stderr}")
    return outdir


def write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ------------------------------------------------------ end-to-end

@needs_cli
def test_asia_canary_in_marker_line_is_redacted_in_both_pack_files(
        tmp_path):
    proj = tmp_path / "asia-marker"
    write(proj, "app.py",
          '"""App."""\n\n'
          f"# TODO: purge the leaked temp session key {ASIA_CANARY} "
          "from the deploy notes\n")
    outdir = build_pack(proj, tmp_path)
    md_text = helpers.pack_text(outdir)
    json_text = (outdir / "handoff.json").read_text(encoding="utf-8")
    assert ASIA_CANARY not in md_text
    assert ASIA_CANARY not in json_text
    # The marker itself is still listed, with the shape named as
    # redacted rather than the line being dropped.
    assert "purge the leaked temp session key" in md_text
    assert REDACTED in md_text
    data = helpers.load_pack_json(outdir)
    item_texts = [it.get("text", "")
                  for it in data["markers"]["items"]]
    assert any(REDACTED in t for t in item_texts), item_texts


@needs_cli
def test_asia_canary_in_report_excerpt_is_redacted_in_both_pack_files(
        tmp_path):
    proj = tmp_path / "asia-report"
    write(proj, "main.py",
          '"""Finished module."""\n\n\ndef done():\n    return True\n')
    # VERIFY.md's first non-empty line is quoted into the pack as the
    # report excerpt (summary) on both surfaces.
    write(proj, "VERIFY.md",
          f"# Verify run used temp key {ASIA_CANARY} for staging\n\n"
          "Verdict: failed\n")
    outdir = build_pack(proj, tmp_path)
    md_text = helpers.pack_text(outdir)
    json_text = (outdir / "handoff.json").read_text(encoding="utf-8")
    assert ASIA_CANARY not in md_text
    assert ASIA_CANARY not in json_text
    assert REDACTED in md_text
    data = helpers.load_pack_json(outdir)
    summaries = [r.get("summary", "") for r in data["reports"]]
    assert any(REDACTED in s for s in summaries), summaries


# --------------------------------------------------------- unit pins

def test_asia_and_akia_both_redacted():
    redact = _redact_module()
    for canary in (ASIA_CANARY, AKIA_CANARY):
        out = redact.redact_text(f"leaked {canary} in the log")
        assert canary not in out and REDACTED in out
        out = redact.redact_text(f"key={canary}; rotate now")
        assert canary not in out and REDACTED in out


def test_canonical_github_prefixes_and_underscore_body_redacted():
    redact = _redact_module()
    # Canonical gh[pousr]_ goes beyond the old ghp_/gho_ pair, and
    # the body charset includes underscores.
    for token in ("ghs_" + "a" * 30, "ghu_" + "a" * 30,
                  "ghp_abcd_efgh_ijkl_mnop_qrst"):
        out = redact.redact_text(f"token {token} seen")
        assert token not in out and REDACTED in out, token


def test_canonical_sk_variants_redacted():
    redact = _redact_module()
    # sk-ant- / sk-proj- prefixes and the canonical 16-char floor:
    # the old Handoff spelling (sk- + 20 alnum) missed all of these.
    for token in ("sk-ant-abcdefghijklmnopqrstuvwxyz0123456789",
                  "sk-proj-" + "a" * 30,
                  "sk-" + "b" * 18):
        out = redact.redact_text(f"key {token} seen")
        assert token not in out and REDACTED in out, token


def test_password_in_url_redacts_password_only():
    redact = _redact_module()
    url = "postgres://svc:hunter2pass@db.internal:5432/app"
    out = redact.redact_text(f"dsn {url} end")
    assert "hunter2pass" not in out
    assert "postgres://svc:" in out and "@db.internal:5432/app" in out


def test_aws_secret_shape_is_context_gated_like_the_guard():
    redact = _redact_module()
    gated = redact.redact_text(f"the aws secret is {AWS_SECRET_40} ok")
    assert AWS_SECRET_40 not in gated and REDACTED in gated
    # Same 40-char shape with no AWS+secret context on the line: the
    # canonical guard deliberately does not flag it, and neither
    # does the redactor (documented divergence control).
    plain = redact.redact_text(f"checksum {AWS_SECRET_40} done")
    assert AWS_SECRET_40 in plain


def test_named_assignment_still_redacts_including_credential():
    redact = _redact_module()
    out = redact.redact_text("password = hunter2")
    assert "hunter2" not in out and "password" in out
    out = redact.redact_text("credential: abcdefghij")
    assert "abcdefghij" not in out and "credential" in out


def test_benign_line_passes_through_unchanged():
    redact = _redact_module()
    line = "TODO: rotate the staging key this week, then update the docs"
    assert redact.redact_text(line) == line
