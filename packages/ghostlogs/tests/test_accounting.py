"""Manifest line accounting must reconcile exactly on the fixture:
lines in = lines kept + lines collapsed + lines dropped, with the
fixture's known multiplicities behind the collapsed figure."""
from conftest import (
    CACHE_WARN_COUNT,
    ERROR_COUNT,
    HEARTBEAT_COUNT,
    TOTAL_LINES,
    build_pack,
    find_accounting,
    load_manifest,
)


def test_pack_succeeds_and_writes_manifest(log_copy, tmp_path):
    proc, out = build_pack(log_copy, tmp_path / "pack")
    assert proc.returncode == 0, proc.stderr
    manifest = load_manifest(out)
    assert isinstance(manifest, dict) and manifest


def test_line_accounting_reconciles_exactly(log_copy, tmp_path):
    proc, out = build_pack(log_copy, tmp_path / "pack")
    assert proc.returncode == 0, proc.stderr
    lines_in, kept, collapsed, dropped = find_accounting(load_manifest(out))
    assert lines_in == TOTAL_LINES
    assert kept + collapsed + dropped == lines_in, (
        f"accounting does not reconcile: kept={kept} collapsed={collapsed} "
        f"dropped={dropped} in={lines_in}"
    )


def test_dropped_breakdown_sums_to_dropped(log_copy, tmp_path):
    """Regression test for REPORT_B.md defect D2. Against the core as
    first landed, any pack with dropped lines had a dropped_by_reason
    breakdown that did not sum to dropped and reported reconciles:
    false on a shipped pack. Agent A fixed the attribution mid-run;
    this test now passes and keeps the bar pinned at two budgets,
    including the over-budget path (exit 1 there is legitimate)."""
    for budget in ("850", "150"):
        proc, out = build_pack(
            log_copy, tmp_path / f"pack-{budget}", ["--budget", budget]
        )
        manifest = load_manifest(out)
        counts = manifest["counts"]
        reasons = counts["dropped_by_reason"]
        assert sum(reasons.values()) == counts["dropped"], (
            f"budget {budget}: dropped={counts['dropped']} but reasons "
            f"sum to {sum(reasons.values())}: {reasons}"
        )
        assert counts["reconciles"] is True


def test_collapsed_covers_known_repeats(log_copy, tmp_path):
    """The routine repeated lines contribute at least (n - 1) collapsed
    lines each: heartbeat 39 + cache warn 11 = 50 collapsed minimum if
    each group keeps exactly one exemplar. The repeated ERROR lines sit
    inside the merged error window on this fixture, where the core
    keeps window lines verbatim, so they are not counted here; the
    error line's own count rule is pinned in test_dedupe.py."""
    proc, out = build_pack(log_copy, tmp_path / "pack")
    assert proc.returncode == 0, proc.stderr
    _, _, collapsed, _ = find_accounting(load_manifest(out))
    minimum = (HEARTBEAT_COUNT - 1) + (CACHE_WARN_COUNT - 1)
    assert collapsed >= minimum, (
        f"collapsed={collapsed}, expected at least {minimum} from the "
        "fixture's known routine repeat groups"
    )
