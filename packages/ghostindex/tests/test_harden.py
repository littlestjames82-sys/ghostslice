"""Hardening regressions (Oct 18, 2026 improvement pass, HARDEN lane).

Each test pins a defect found by probing the built tool:

- a symlink inside a root used to smuggle in content the walker
  would never index at the target's own path (a .gitignore'd file,
  a node_modules file, a binary-extension file), breaking the hard
  rule that ignored and binary files stay unsearchable;
- the .gitignore glob translator inverted ``[!...]`` character
  classes and let ``**/`` match a partial path segment;
- non-positive CLI limits were silently mishandled (--limit 0
  reported "no matches" for files that match, a negative --context
  produced empty excerpts labelled L2-L0, a negative --max-bytes
  indexed nothing and reported success);
- a corrupt (non-sqlite) database file made every command die with
  a traceback instead of the contracted exit 2 with a plain error;
- the indexer's size cap trusted the walker's stat, so content that
  grew after being statted could enter the index over the cap.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def _project(tmp_path: Path, files: dict[str, str]) -> Path:
    proj = tmp_path / "proj"
    proj.mkdir(exist_ok=True)
    for rel, text in files.items():
        path = proj / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return proj


# ------------------------------------------------------------------
# Symlink smuggling: ignored/binary content must stay unsearchable
# however it is reached.
# ------------------------------------------------------------------

def test_symlink_to_gitignored_file_is_not_searchable(cli, tmp_path, db):
    proj = _project(tmp_path, {
        ".gitignore": "secret_cfg.py\n",
        "secret_cfg.py": 'TOKEN = "leakedtermxyz"\n',
        "normal.py": 'X = "ordinaryterm"\n',
    })
    (proj / "alias.py").symlink_to(proj / "secret_cfg.py")
    proc = cli.index_roots(db, [proj])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    result = cli.search(db, "leakedtermxyz")
    assert result.returncode == 1, (
        "content of a .gitignore'd file became searchable through a "
        "symlink alias:\n" + result.stdout)
    assert cli.search(db, "ordinaryterm").returncode == 0


def test_symlink_to_default_ignored_dir_is_not_searchable(cli, tmp_path, db):
    proj = _project(tmp_path, {
        "node_modules/lib/dep.py": 'Y = "nodemodleakterm"\n',
        "normal.py": 'X = "ordinaryterm"\n',
    })
    (proj / "alias.py").symlink_to(proj / "node_modules" / "lib" / "dep.py")
    proc = cli.index_roots(db, [proj])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    result = cli.search(db, "nodemodleakterm")
    assert result.returncode == 1, (
        "node_modules content became searchable through a symlink "
        "alias:\n" + result.stdout)


def test_symlink_to_binary_extension_target_is_not_searchable(cli, tmp_path,
                                                              db):
    proj = _project(tmp_path, {
        # .db is a binary extension; the file holds plain text so the
        # content sniff alone would let it through under a .txt name.
        "data.db": 'Z = "binaryleakterm"\n',
        "normal.py": 'X = "ordinaryterm"\n',
    })
    (proj / "alias.txt").symlink_to(proj / "data.db")
    proc = cli.index_roots(db, [proj])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    result = cli.search(db, "binaryleakterm")
    assert result.returncode == 1, (
        "binary-extension content became searchable through a "
        "symlink alias:\n" + result.stdout)


def test_symlink_to_legit_file_stays_searchable(cli, tmp_path, db):
    """Over-blocking guard: a link to an ordinary in-root file is a
    legitimate project shape and must keep working."""
    proj = _project(tmp_path, {"real.py": 'R = "legittermxyz"\n'})
    (proj / "alias.py").symlink_to(proj / "real.py")
    proc = cli.index_roots(db, [proj])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    result = cli.search(db, "legittermxyz")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "alias.py" in result.stdout and "real.py" in result.stdout


def test_symlink_loop_and_broken_link_do_not_crash_indexing(cli, tmp_path,
                                                            db):
    proj = _project(tmp_path, {"a.py": 'Q = "quixotic"\n'})
    (proj / "loop.py").symlink_to(proj / "loop.py")
    (proj / "broken.py").symlink_to(proj / "missing.py")
    proc = cli.index_roots(db, [proj])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "Traceback" not in proc.stderr
    assert cli.search(db, "quixotic").returncode == 0


# ------------------------------------------------------------------
# .gitignore glob translation
# ------------------------------------------------------------------

def test_gitignore_negated_character_class(cli, tmp_path, db):
    proj = _project(tmp_path, {
        ".gitignore": "data[!0-9].txt\n",
        "datax.txt": 'A = "classleakterm"\n',   # x is not a digit: ignored
        "data5.txt": 'B = "classkeptterm"\n',   # 5 is a digit: kept
    })
    proc = cli.index_roots(db, [proj])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert cli.search(db, "classleakterm").returncode == 1, (
        "data[!0-9].txt should ignore datax.txt")
    assert cli.search(db, "classkeptterm").returncode == 0, (
        "data[!0-9].txt must not ignore data5.txt")


def test_gitignore_double_star_matches_whole_segments_only(cli, tmp_path, db):
    proj = _project(tmp_path, {
        ".gitignore": "**/hidden.txt\na/**/gen.py\n",
        "hidden.txt": 'A = "rootleakterm"\n',
        "sub/hidden.txt": 'B = "subleakterm"\n',
        "xhidden.txt": 'C = "partialkeptterm"\n',
        "a/gen.py": 'D = "agenleakterm"\n',
        "a/x/gen.py": 'E = "axgenleakterm"\n',
        "a/xgen.py": 'F = "axkeptterm"\n',
    })
    proc = cli.index_roots(db, [proj])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    for term in ("rootleakterm", "subleakterm", "agenleakterm",
                 "axgenleakterm"):
        assert cli.search(db, term).returncode == 1, (
            f"{term} should have been ignored")
    for term in ("partialkeptterm", "axkeptterm"):
        assert cli.search(db, term).returncode == 0, (
            f"{term} must not be ignored: ** only matches whole "
            "path segments")


def test_glob_to_regex_units():
    from ghostindex.scanner import _glob_to_regex

    cases = [
        ("**/foo", "foo", True), ("**/foo", "a/foo", True),
        ("**/foo", "afoo", False),
        ("a/**/b", "a/b", True), ("a/**/b", "a/x/y/b", True),
        ("a/**/b", "a/xb", False),
        ("foo/**", "foo/bar", True), ("foo/**", "foo", False),
        ("file[!0-9].txt", "filex.txt", True),
        ("file[!0-9].txt", "file5.txt", False),
        ("file[0-9].txt", "file5.txt", True),
        ("src/*.py", "src/sub/x.py", False),
        (r"\#notes", "#notes", True),
    ]
    for pattern, text, expected in cases:
        assert bool(_glob_to_regex(pattern).match(text)) is expected, (
            f"glob {pattern!r} vs {text!r}")


# ------------------------------------------------------------------
# CLI limit validation
# ------------------------------------------------------------------

@pytest.fixture()
def tiny_index(cli, tmp_path, db):
    proj = _project(tmp_path, {"a.py": 'Q = "quixotic hello"\n'})
    proc = cli.index_roots(db, [proj])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proj, db


@pytest.mark.parametrize("extra", [
    ["--limit", "0"], ["--limit", "-1"],
    ["--context", "-1"], ["--context", "-5"],
    ["--max-tokens", "0"], ["--max-tokens", "-10"],
])
def test_search_rejects_invalid_limits(cli, tiny_index, extra):
    _, db = tiny_index
    proc = cli.run_cli(["search", "quixotic"] + extra, db=db)
    assert proc.returncode == 2, (
        f"{extra} should be a usage error (exit 2), got "
        f"rc={proc.returncode}:\n{proc.stdout}\n{proc.stderr}")
    assert "Traceback" not in proc.stderr
    assert "no matches" not in proc.stdout, (
        "an invalid limit must never be reported as an empty result")


def test_index_rejects_negative_max_bytes(cli, tmp_path, db):
    proj = _project(tmp_path, {"a.py": 'Q = "quixotic"\n'})
    proc = cli.run_cli(["index", str(proj), "--max-bytes", "-1"], db=db)
    assert proc.returncode == 2, (
        f"negative --max-bytes should be a usage error, got "
        f"rc={proc.returncode}:\n{proc.stdout}\n{proc.stderr}")
    assert "Traceback" not in proc.stderr


def test_search_rejects_invalid_limits_via_api(tmp_path):
    """search() itself refuses nonsense limits, so API callers get
    the same protection as CLI users."""
    from ghostindex import indexer, search as search_mod, store

    proj = _project(tmp_path, {"a.py": 'Q = "quixotic"\n'})
    conn = store.open_store(tmp_path / "api.db")
    indexer.index_root(conn, proj)
    for kwargs in ({"limit": 0}, {"limit": -2}, {"context": -1},
                   {"per_hit_tokens": 0}, {"total_tokens": 0}):
        with pytest.raises(ValueError):
            search_mod.search(conn, "quixotic", **kwargs)
    conn.close()


# ------------------------------------------------------------------
# Corrupt index database: clean error + exit 2, never a traceback
# ------------------------------------------------------------------

@pytest.fixture()
def corrupt_db(tmp_path):
    bad = tmp_path / "state" / "index.db"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_bytes(b"this is not a sqlite database at all " * 8)
    return bad


@pytest.mark.parametrize("args", [
    ["search", "quixotic"], ["list"], ["stats"], ["vacuum"],
    ["index", "."], ["update"],
])
def test_corrupt_database_is_a_clean_exit_2(cli, corrupt_db, args, tmp_path):
    proc = cli.run_cli(args, db=corrupt_db, cwd=tmp_path)
    assert proc.returncode == 2, (
        f"{args} on a corrupt database should exit 2 (could not "
        f"run), got rc={proc.returncode}:\n{proc.stdout}\n{proc.stderr}")
    assert "Traceback" not in proc.stderr
    assert "corrupt" in (proc.stdout + proc.stderr) or \
        "not a database" in (proc.stdout + proc.stderr)


def test_corrupt_database_remove_is_a_clean_exit_2(cli, corrupt_db, tmp_path):
    proc = cli.run_cli(["remove", str(tmp_path)], db=corrupt_db)
    assert proc.returncode == 2
    assert "Traceback" not in proc.stderr


def test_doctor_reports_corrupt_database(cli, corrupt_db):
    proc = cli.run_cli(["doctor", "--json"], db=corrupt_db)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "Traceback" not in proc.stderr
    report = json.loads(proc.stdout)
    assert report["db_exists"] is True
    assert "error" in report, (
        "doctor must name the corruption it diagnosed")


# ------------------------------------------------------------------
# Size cap: enforced on the bytes actually read, not a stale stat
# ------------------------------------------------------------------

def test_size_cap_applies_to_bytes_actually_read(tmp_path, monkeypatch):
    from ghostindex import indexer, scanner, store

    proj = tmp_path / "proj"
    proj.mkdir()
    target = proj / "big.py"
    target.write_text("MARKER = 'growthtermxyz'\n" + "# padding\n" * 20)
    conn = store.open_store(tmp_path / "cap.db")
    # Simulate the race: the walker statted the file while it was
    # tiny; by the time the indexer reads it, it is over the cap.
    stale = scanner.Candidate(rel="big.py", abspath=target, size=1,
                              mtime=target.stat().st_mtime)
    monkeypatch.setattr(
        scanner, "walk",
        lambda root, extra_skip_paths=None: scanner.WalkResult(
            candidates=[stale]))
    report = indexer.index_root(conn, proj, max_bytes=16)
    conn.close()
    assert report.skipped_too_large == 1
    assert report.files_indexed == 0, (
        "content over the size cap entered the index on a stale stat")
