"""Lost-coverage detection: test cover the diff itself removed.

Before this pass, a changed symbol whose only covering test was
deleted in the same diff read as a generic "no covering test":
head-side covering tests are built from the post-change tree, where
the deleted test no longer exists, so nothing linked the deletion
to the symbol that lost its cover. README.md promises the precise
reason ("no covering test (covering test deleted in this diff)");
these tests pin that promise end to end, plus the false-positive
guards: an unrelated deleted test, a still-covering edited test,
and surviving partial cover must not be misreported.
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ghostscope.graphbuild import outline_cover  # noqa: E402
from ghostscope.outline import build_outline, resolve_imports  # noqa: E402

from tests.helpers import (  # noqa: E402
    FIXTURES, apply_change, build_git_project, find_pack_file, git,
    load_json_recursive, run_pack,
)


def _outline(path, source, all_paths):
    out = build_outline(path, source, "python")
    resolve_imports(out, set(all_paths))
    return out


class TestOutlineCover(unittest.TestCase):
    """Unit: the shared covering semantics both sides rely on."""

    def test_call_hit_is_symbol_proven(self):
        out = _outline("tests/test_billing.py",
                       "from billing import charge\n\n"
                       "def test_charge():\n    assert charge(1)\n",
                       ["billing.py", "tests/test_billing.py"])
        cover = outline_cover(out, "billing.py", ["charge", "refund"])
        self.assertEqual(cover["symbols"], ["charge"])
        self.assertIn("calls charge", cover["reasons"])
        self.assertEqual(cover["method"], "python-ast")

    def test_import_only_is_file_level_not_symbol(self):
        out = _outline("tests/test_billing.py",
                       "import billing\n\n"
                       "def test_smoke():\n    assert billing is not None\n",
                       ["billing.py", "tests/test_billing.py"])
        cover = outline_cover(out, "billing.py", ["charge"])
        self.assertTrue(cover["reasons"], "import must prove file-level cover")
        self.assertEqual(cover["symbols"], [],
                         "an import alone must not be guessed onto a symbol")

    def test_unrelated_test_covers_nothing(self):
        out = _outline("tests/test_other.py",
                       "from other import thing\n\n"
                       "def test_thing():\n    assert thing()\n",
                       ["billing.py", "other.py", "tests/test_other.py"])
        cover = outline_cover(out, "billing.py", ["charge"])
        self.assertEqual(cover["reasons"], [])
        self.assertEqual(cover["symbols"], [])


def _changed(scope, path):
    for rep in scope["changed"]:
        if rep["path"] == path:
            return rep
    raise AssertionError(f"{path} not in scope.changed: "
                         f"{[c['path'] for c in scope['changed']]}")


def _notes(scope, kind=None, path=None):
    out = scope["notes"]
    if kind is not None:
        out = [n for n in out if n["kind"] == kind]
    if path is not None:
        out = [n for n in out if n["path"] == path]
    return out


class FixturePackCase(unittest.TestCase):
    fixture = None

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = Path(self._tmp.name)
        root = FIXTURES / self.fixture
        self.proj = build_git_project(root / "base", tmp)
        apply_change(self.proj, root / "change", root / "deletions.txt")
        self.out = tmp / "pack"
        run_pack(self.proj, self.out)
        self.scope = load_json_recursive(
            find_pack_file(self.out, self.proj, "scope.json"))
        self.review = find_pack_file(
            self.out, self.proj, "REVIEW.md").read_text()


class TestDeletedCoveringTestLinkage(FixturePackCase):
    fixture = "deleted_covering_test"

    def test_lost_entry_links_deleted_test_to_symbol(self):
        rep = _changed(self.scope, "billing.py")
        lost = rep["lost_covering_tests"]
        self.assertEqual(len(lost), 1)
        entry = lost[0]
        self.assertEqual(entry["path"], "tests/test_billing.py")
        self.assertEqual(entry["how"], "deleted")
        self.assertEqual(entry["symbols"], ["charge"])
        self.assertFalse(entry["file_level_only"])
        self.assertEqual(entry["method"], "python-ast")
        self.assertIn("calls charge", entry["reasons"])

    def test_symbol_reason_is_the_promised_wording(self):
        rep = _changed(self.scope, "billing.py")
        charge = rep["symbols"][0]
        self.assertIn(
            "covering test deleted in this diff (tests/test_billing.py)",
            charge["risk_reasons"])
        # The lost cover raises the symbol above its pre-feature
        # score (1 caller 5 + exported 20 + no cover 20 = 45).
        self.assertEqual(charge["risk_score"], 55)
        self.assertEqual(rep["risk_score"], 55)

    def test_note_cites_file_symbol_and_test(self):
        hits = _notes(self.scope, kind="covering-test-deleted",
                      path="billing.py")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["symbol"], "charge")
        self.assertIn("tests/test_billing.py", hits[0]["text"])
        self.assertIn("charge", hits[0]["text"])

    def test_generic_note_not_duplicated_for_that_symbol(self):
        generic = [n for n in _notes(self.scope, kind="no-covering-test",
                                     path="billing.py")
                   if n["symbol"] == "charge"]
        self.assertEqual(generic, [],
                         "the precise lost-cover note replaces the "
                         "generic one for the same symbol")

    def test_review_and_totals_carry_the_loss(self):
        self.assertIn("Lost covering test: tests/test_billing.py",
                      self.review)
        self.assertIn("covering test deleted in this diff", self.review)
        self.assertEqual(self.scope["totals"]["lost_covering_tests"], 1)

    def test_deleted_test_itself_has_no_lost_entry(self):
        rep = _changed(self.scope, "tests/test_billing.py")
        self.assertEqual(rep["lost_covering_tests"], [])


class TestNoDeletionNoLoss(FixturePackCase):
    fixture = "high_blast_radius"

    def test_no_lost_entries_anywhere(self):
        for rep in self.scope["changed"]:
            self.assertEqual(rep["lost_covering_tests"], [], rep["path"])
        self.assertEqual(self.scope["totals"]["lost_covering_tests"], 0)
        self.assertEqual(_notes(self.scope, kind="covering-test-deleted"), [])
        self.assertEqual(_notes(self.scope, kind="covering-test-removed"), [])
        self.assertNotIn("Lost covering test:", self.review)


def _inline_project(tmp: Path, base_files: dict, change_files: dict,
                    deletions=()):
    proj = tmp / "proj"
    proj.mkdir()
    subprocess.run(["git", "init", "-q", str(proj)], check=True)
    git(proj, "config", "user.email", "test@example.com")
    git(proj, "config", "user.name", "GhostScope Tests")
    for rel, text in base_files.items():
        dest = proj / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text)
    git(proj, "add", "-A")
    git(proj, "commit", "-qm", "base")
    for rel, text in change_files.items():
        dest = proj / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text)
    for rel in deletions:
        (proj / rel).unlink()
    git(proj, "add", "-A")
    git(proj, "commit", "-qm", "change")
    out = tmp / "pack"
    run_pack(proj, out)
    scope = load_json_recursive(find_pack_file(out, proj, "scope.json"))
    review = find_pack_file(out, proj, "REVIEW.md").read_text()
    return scope, review


LIB = "__all__ = ['compute']\n\n\ndef compute(x):\n    return x + 1\n"
LIB_CHANGED = "__all__ = ['compute']\n\n\ndef compute(x):\n    return x + 2\n"
TEST_COMPUTE = ("from lib import compute\n\n\n"
                "def test_compute():\n    assert compute(1) == 2\n")


class TestRemovedAndPartialCover(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_covering_function_edited_away_is_removed(self):
        scope, review = _inline_project(
            self.tmp,
            {"lib.py": LIB,
             "tests/test_lib.py": TEST_COMPUTE +
             "\ndef test_other():\n    assert True\n"},
            {"lib.py": LIB_CHANGED,
             "tests/test_lib.py":
             "def test_other():\n    assert True\n"})
        rep = _changed(scope, "lib.py")
        self.assertEqual(len(rep["lost_covering_tests"]), 1)
        entry = rep["lost_covering_tests"][0]
        self.assertEqual(entry["how"], "removed")
        self.assertEqual(entry["symbols"], ["compute"])
        hits = _notes(scope, kind="covering-test-removed", path="lib.py")
        self.assertEqual(len(hits), 1)
        self.assertIn("covering test removed in this diff", review)

    def test_partial_cover_survives_and_is_not_called_missing(self):
        scope, _review = _inline_project(
            self.tmp,
            {"lib.py": LIB,
             "tests/test_a.py": TEST_COMPUTE,
             "tests/test_b.py": TEST_COMPUTE},
            {"lib.py": LIB_CHANGED},
            deletions=("tests/test_a.py",))
        rep = _changed(scope, "lib.py")
        self.assertEqual([e["path"] for e in rep["lost_covering_tests"]],
                         ["tests/test_a.py"])
        compute = rep["symbols"][0]
        self.assertIn("tests/test_b.py", rep["covering_tests"][0]["path"]
                      if rep["covering_tests"] else "")
        self.assertNotIn("no covering test", compute["risk_reasons"])
        self.assertIn(
            "covering test deleted in this diff (tests/test_a.py)",
            compute["risk_reasons"])

    def test_unrelated_deleted_test_is_not_linked(self):
        scope, _review = _inline_project(
            self.tmp,
            {"lib.py": LIB,
             "other.py": "def thing():\n    return 1\n",
             "tests/test_lib.py": TEST_COMPUTE,
             "tests/test_other.py":
             "from other import thing\n\n\n"
             "def test_thing():\n    assert thing() == 1\n"},
            {"lib.py": LIB_CHANGED},
            deletions=("tests/test_other.py",))
        rep = _changed(scope, "lib.py")
        self.assertEqual(rep["lost_covering_tests"], [])
        # The deletion is still reported, just not linked to lib.py.
        self.assertTrue(_notes(scope, kind="test-deleted",
                               path="tests/test_other.py"))

    def test_still_covering_edited_test_reports_no_loss(self):
        scope, _review = _inline_project(
            self.tmp,
            {"lib.py": LIB, "tests/test_lib.py": TEST_COMPUTE},
            {"lib.py": LIB_CHANGED,
             "tests/test_lib.py": TEST_COMPUTE +
             "\ndef test_compute_negative():\n    assert compute(-1) == 0\n"})
        rep = _changed(scope, "lib.py")
        self.assertEqual(rep["lost_covering_tests"], [])


if __name__ == "__main__":
    unittest.main()
