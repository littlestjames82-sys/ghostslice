"""Space reclaim (polish round, Oct 14, 2026).

Before this round, deleting rows only moved sqlite pages onto the
freelist: `remove` dropped a root's content but the database file
kept every byte (measured: 217,088 bytes before and after removing
every indexed file). These tests pin the fixed behaviour:

- `remove` vacuums, and the file actually shrinks.
- Space freed by `update` removals stays in the file until the
  standalone `vacuum` command runs; `stats` reports the reclaimable
  amount in between, and search stays correct throughout.
- `vacuum` against a database that does not exist is exit 2 and
  creates nothing.
"""
from __future__ import annotations

import json
from pathlib import Path


def _big_project(tmp_path: Path) -> Path:
    proj = tmp_path / "bigproj"
    proj.mkdir()
    lines = [
        f"line {i} lorem ipsum dolor sit amet consectetur "
        f"adipiscing elit segment{i % 89} token{i % 37}"
        for i in range(1500)
    ]
    (proj / "big.txt").write_text("\n".join(lines) + "\nbigfileterm\n")
    (proj / "small.txt").write_text("a small file with keptterm inside\n")
    return proj


def test_remove_vacuums_and_reclaims_space(cli, tmp_path, db):
    proj = _big_project(tmp_path)
    proc = cli.index_roots(db, [proj])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    before = db.stat().st_size
    assert before > 100_000, "fixture index should be sizeable"

    proc = cli.run_cli(["remove", str(proj)], db=db)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "reclaimed" in proc.stdout
    after = db.stat().st_size
    assert after < before // 2, (
        f"remove did not reclaim space: {before} -> {after}")
    # The root is really gone, not just the space.
    proc = cli.run_cli(["list"], db=db)
    assert "bigproj" not in proc.stdout


def test_vacuum_command_reclaims_space_freed_by_update(cli, tmp_path, db):
    proj = _big_project(tmp_path)
    proc = cli.index_roots(db, [proj])
    assert proc.returncode == 0, proc.stdout + proc.stderr

    (proj / "big.txt").unlink()
    proc = cli.update_roots(db, [proj])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    counts = cli.parse_update_counts(proc.stdout)
    assert counts["removed"] == 1

    freed = db.stat().st_size
    # stats names the reclaimable amount while it is still held.
    proc = cli.run_cli(["stats", "--json"], db=db)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    stats = json.loads(proc.stdout)
    assert stats["reclaimable_bytes"] > 0

    proc = cli.run_cli(["vacuum"], db=db)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    after = db.stat().st_size
    assert after < freed // 2, (
        f"vacuum did not reclaim space: {freed} -> {after}")

    proc = cli.run_cli(["stats", "--json"], db=db)
    stats = json.loads(proc.stdout)
    assert stats["reclaimable_bytes"] == 0

    # Search is correct on both sides of the removal.
    assert cli.search(db, "keptterm").returncode == 0
    assert cli.search(db, "bigfileterm").returncode == 1


def test_doctor_reports_database_size(cli, tmp_path, db):
    # PLAN.md and the README both say doctor reports the database
    # size; before this round it printed only the path.
    proj = _big_project(tmp_path)
    proc = cli.index_roots(db, [proj])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    proc = cli.run_cli(["doctor", "--json"], db=db)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads(proc.stdout)
    assert report["db_bytes"] == db.stat().st_size
    assert report["db_bytes"] > 100_000


def test_vacuum_with_no_database_is_exit_2_and_creates_nothing(cli, db):
    proc = cli.run_cli(["vacuum"], db=db)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert not db.exists()
