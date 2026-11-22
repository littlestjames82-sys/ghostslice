"""Budget discipline and source safety: the pack respects its stated
token budget (default and tight), and the source log is byte-identical
after a run."""
from conftest import (
    build_pack,
    find_budget,
    load_manifest,
    sha256_of,
)


def test_default_pack_respects_its_stated_budget(log_copy, tmp_path):
    proc, out = build_pack(log_copy, tmp_path / "pack")
    assert proc.returncode == 0, proc.stderr
    budget, estimate = find_budget(load_manifest(out))
    assert budget is not None, "manifest states no token budget"
    assert estimate is not None, "manifest states no pack token estimate"
    assert estimate <= budget, (
        f"pack estimate {estimate} exceeds stated budget {budget}"
    )


def test_pack_is_never_silently_over_budget(log_copy, tmp_path):
    """Across budgets, the pack either lands at or under the stated
    budget with a clean exit, or it is marked over_budget in the
    manifest AND exits nonzero. Silently shipping an over-budget pack
    as if it fit is the one outcome that must never happen. (Whether a
    fittable tier is always chosen is a separate question, pinned as
    defect D3 below.)"""
    for budget in (500, 600, 850, 2000):
        proc, out = build_pack(
            log_copy, tmp_path / f"pack-{budget}", ["--budget", str(budget)]
        )
        manifest = load_manifest(out)
        stated, estimate = find_budget(manifest)
        assert stated == budget
        assert estimate is not None
        if proc.returncode == 0:
            assert estimate <= budget, (
                f"budget {budget}: clean exit but estimate {estimate} over"
            )
            assert manifest.get("over_budget") is False
        else:
            assert manifest.get("over_budget") is True, (
                f"budget {budget}: nonzero exit but manifest does not "
                "mark the pack over budget"
            )


def test_tight_budget_shrinks_pack_even_when_it_cannot_fit(log_copy, tmp_path):
    """At a budget below every fittable tier, the core still emits a
    strictly smaller pack than the default (fewer kept lines) on the
    plan's over-budget path, rather than ignoring the budget."""
    proc1, out1 = build_pack(log_copy, tmp_path / "pack-default")
    assert proc1.returncode == 0, proc1.stderr
    _, est_default = find_budget(load_manifest(out1))
    proc2, out2 = build_pack(log_copy, tmp_path / "pack-tight", ["--budget", "500"])
    manifest2 = load_manifest(out2)
    _, est_tight = find_budget(manifest2)
    assert est_default is not None and est_tight is not None
    assert est_tight < est_default
    assert manifest2["counts"]["kept"] < load_manifest(out1)["counts"]["kept"]


import pytest


# D3 fixed Oct 14, 2026 (see FIX_REPORT.md): the builder now descends a
# tier ladder and only reports over_budget when even the anchors tier
# cannot fit. The former strict-xfail marker was removed by the parent
# on the fix landing, so this test is now a permanent pass requirement.
def test_budget_600_lands_at_or_under_budget(log_copy, tmp_path):
    proc, out = build_pack(log_copy, tmp_path / "pack", ["--budget", "600"])
    assert proc.returncode == 0, proc.stderr
    budget, estimate = find_budget(load_manifest(out))
    assert budget == 600 and estimate is not None and estimate <= 600


def test_over_budget_path_is_honest(log_copy, tmp_path):
    """Plan-sanctioned path: a budget below the mandatory content still
    writes the pack, marks it over budget in the manifest, and says so
    with the exit code. It must never pretend the pack fits."""
    proc, out = build_pack(log_copy, tmp_path / "pack", ["--budget", "150"])
    assert proc.returncode != 0, "over-budget pack exited 0"
    manifest = load_manifest(out)
    assert manifest.get("over_budget") is True
    budget, estimate = find_budget(manifest)
    assert budget == 150 and estimate is not None and estimate > 150


def test_source_log_byte_identical_after_run(log_copy, tmp_path):
    before = sha256_of(log_copy)
    proc, out = build_pack(log_copy, tmp_path / "pack")
    assert proc.returncode == 0, proc.stderr
    assert sha256_of(log_copy) == before, "source log changed during the run"
    # and nothing was written next to the source besides what existed
    siblings = {p.name for p in tmp_path.iterdir()}
    assert siblings <= {"noisy.log", "pack"}, f"unexpected files written: {siblings}"
