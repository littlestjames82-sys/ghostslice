"""Polish-round pins (Oct 14, 2026): tier wording a stranger can
read, the pack file itself stating an over-budget outcome, and the
documented exactness of the secret shapes.

These tests were ADDED in the polish round; no existing assertion
was changed. The shape-exactness tests pin current, deliberate
behaviour (the AWS shape is the same exact shape GhostSlice's
guard uses), so the README's precise limits stay true under test.
"""
from conftest import all_output_text, build_pack, load_manifest, pack_text

# Synthetic, non-secret values built to exact lengths for the shape
# probes. AKIA_EXACT is AKIA + 16 chars = the real 20-char shape.
# AKIA_LONG is AKIA + 18 chars = 22 total, a look-alike that is not
# the shape.
AKIA_EXACT = "AKIA" + "BCDFGHJKLMNPQRS1"
AKIA_LONG = "AKIA" + "BCDFGHJKLMNPQRSTV2"


def test_over_budget_pack_says_so_in_incident_md(log_copy, tmp_path):
    """The pack file itself (the artefact handed to a reader or an
    agent) must state the over-budget outcome, not only the
    manifest and the terminal."""
    proc, out = build_pack(log_copy, tmp_path / "pack", ["--budget", "150"])
    assert proc.returncode != 0, proc.stdout
    manifest = load_manifest(out)
    assert manifest["over_budget"] is True
    assert manifest["budget_tier"] == "anchors"
    text = pack_text(out)
    assert "## Pack status" in text
    assert "OVER BUDGET" in text
    # accounting still reconciles exactly on the over-budget tier
    c = manifest["counts"]
    assert c["reconciles"] is True
    assert c["total_lines"] == c["kept"] + c["collapsed"] + c["dropped"]
    assert sum(c["dropped_by_reason"].values()) == c["dropped"]


def test_budget_tier_is_named_and_explained(log_copy, tmp_path):
    """A pack that descends the ladder states its tier on the face
    of INCIDENT.md, and the manifest explains the tier name in
    plain words (budget_tier_meaning). A full-tier pack carries
    the meaning in the manifest but needs no tier line."""
    proc, out = build_pack(log_copy, tmp_path / "pack500", ["--budget", "500"])
    manifest = load_manifest(out)
    assert manifest["budget_tier"] == "anchors", manifest["budget_tier"]
    meaning = manifest.get("budget_tier_meaning", "")
    assert "timeline anchors" in meaning
    assert "Budget tier: anchors" in pack_text(out)
    assert "budget tier: anchors" in proc.stdout

    proc2, out2 = build_pack(log_copy, tmp_path / "pack-default")
    assert proc2.returncode == 0, proc2.stderr
    manifest2 = load_manifest(out2)
    assert manifest2["budget_tier"] == "full"
    assert manifest2.get("budget_tier_meaning")
    text2 = pack_text(out2)
    assert "Budget tier:" not in text2
    assert "OVER BUDGET" not in text2


def _shape_log(tmp_path):
    log = tmp_path / "shapes.log"
    log.write_text(
        "2026-10-14T08:00:00Z INFO boot complete\n"
        f"2026-10-14T08:00:01Z ERROR upstream rejected key {AKIA_EXACT}\n"
        f"2026-10-14T08:00:02Z ERROR upstream rejected key {AKIA_LONG}\n"
        "2026-10-14T08:00:03Z ERROR cfg password=abc123 retry scheduled\n"
        "2026-10-14T08:00:04Z ERROR cfg password=abc12345 retry scheduled\n"
        "2026-10-14T08:01:00Z INFO shutdown complete\n"
    )
    return log


def test_aws_shape_is_exact_length_by_design(tmp_path):
    """The 20-char AWS shape is redacted; the 22-char look-alike is
    not that shape (documented limit, same shape as GhostSlice's
    guard) and is therefore shown. Pinning the miss is deliberate:
    it keeps the README's exactness statement honest."""
    log = _shape_log(tmp_path)
    proc, out = build_pack(log, tmp_path / "pack")
    assert proc.returncode == 0, proc.stderr
    everything = all_output_text(out, proc)
    assert AKIA_EXACT not in everything
    manifest = load_manifest(out)
    assert manifest["redaction"]["counts"].get("aws-access-key", 0) >= 1
    assert AKIA_LONG in pack_text(out)


def test_generic_assignment_minimums(tmp_path):
    """A generic assignment is redacted only at 8+ value chars:
    the 6-char value stays visible (documented minimum), the
    8-char value is replaced and appears nowhere."""
    log = _shape_log(tmp_path)
    proc, out = build_pack(log, tmp_path / "pack")
    assert proc.returncode == 0, proc.stderr
    text = pack_text(out)
    assert "password=abc123 retry" in text
    assert "abc12345" not in all_output_text(out, proc)
    assert "[REDACTED:generic-assignment]" in text
